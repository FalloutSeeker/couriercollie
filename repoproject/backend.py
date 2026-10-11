"""The bridge between the window (QML) and the rest of the app.

The window calls the slots here and shows the properties. Anything that touches the network runs on a worker thread,
so the window never freezes; results are handed back to the main thread through `_deliver`.
"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import Property, QObject, Signal, Slot

from . import assets, config, sources
from .config import FOLLOW_BRANCH, FOLLOW_RELEASES, Config, ConfigError, TrackedRepo
from .sources import RepoRef, SourceError

HOST_LABELS = {"github": "GitHub", "gitlab": "GitLab"}
KIND_ICONS = {
    assets.KIND_GIT: "folder-git",
    assets.KIND_RPM: "application-x-rpm",
    assets.KIND_APPIMAGE: "application-vnd.appimage",
    assets.KIND_PROGRAM: "application-x-executable",
    assets.KIND_FILE: "application-x-executable",
}
FILTERS = ("all", "github", "gitlab")


@dataclass
class Details:
    """What we fetched about a repo. Kept in memory only; checking for updates (stage 4) will store what it needs."""

    state: str = "loading"  # "loading", "ready" or "error"
    error: str = ""
    releases: list[sources.Release] = field(default_factory=list)
    default_branch: str = ""
    branches: list[sources.Branch] = field(default_factory=list)
    branch_error: str = ""


def _size_text(size: int | None) -> str:
    if not size:
        return ""
    for unit in ("bytes", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit in ("bytes", "KB") else f"{size:.1f} {unit}"
        size /= 1024
    return ""


def _date_text(date: datetime | None) -> str:
    return f"{date.astimezone():%-d %b %Y}" if date else ""


def _fetch_branches(ref: RepoRef) -> tuple[str, list[sources.Branch], str]:
    try:
        default, branches = sources.branches(ref)
        return default, branches, ""
    except SourceError as e:
        return "", [], str(e)


class Backend(QObject):
    reposChanged = Signal()
    filterChanged = Signal()
    addingChanged = Signal()
    addFinished = Signal(str)  # repo id
    addFailed = Signal(str)  # message for the user
    detailsChanged = Signal(str)  # repo id
    settingsChanged = Signal()
    _deliver = Signal(object)

    def __init__(self, config_path: Path | None = None, parent=None):
        super().__init__(parent)
        self._path = config_path
        self._config_error = ""
        try:
            self._config = config.load(config_path)
        except ConfigError as e:
            # Start empty, and don't save, so the broken file isn't overwritten.
            self._config = Config()
            self._config_error = str(e)
        self._filter = "all"
        self._adding = False
        self._details: dict[str, Details] = {}
        self._pool = ThreadPoolExecutor(max_workers=4)
        self._deliver.connect(lambda fn: fn())

    def shutdown(self):
        self._pool.shutdown(wait=False, cancel_futures=True)

    # -- helpers --------------------------------------------------------------------------------------------------

    def _run(self, work, done):
        """Run `work()` on a worker thread, then `done(result, error)` back on the main thread."""

        def task():
            try:
                result, error = work(), None
            except Exception as e:  # noqa: BLE001 - shown to the user, never crashes the window
                result, error = None, e
            self._deliver.emit(lambda: done(result, error))

        self._pool.submit(task)

    def _save(self):
        if not self._config_error:
            config.save(self._config, self._path)

    def _changed(self, repo_id: str | None = None):
        self._save()
        self.reposChanged.emit()
        if repo_id:
            self.detailsChanged.emit(repo_id)

    @staticmethod
    def _error_text(error: Exception) -> str:
        return str(error) if isinstance(error, (SourceError, ValueError)) else f"Something went wrong: {error}"

    def _repo_dict(self, r: TrackedRepo) -> dict:
        ref = RepoRef.from_id(r.id)
        if r.follow == FOLLOW_BRANCH:
            follow_text = f"Branch {r.branch}" if r.branch else "A branch"
        elif r.asset_pattern:
            follow_text = r.asset_pattern
        else:
            follow_text = "No build file picked yet"
        return {
            "id": r.id,
            "name": r.name,
            "url": r.url,
            "host": r.host,
            "hostLabel": HOST_LABELS.get(r.host, r.host),
            "domain": ref.domain,
            "path": ref.path,
            "follow": r.follow,
            "branch": r.branch,
            "assetPattern": r.asset_pattern,
            "prereleases": r.prereleases,
            "kind": r.kind,
            "icon": KIND_ICONS.get(r.kind, "package-x-generic"),
            "followText": follow_text,
        }

    # -- the list ---------------------------------------------------------------------------------------------------

    @Property("QVariantList", notify=reposChanged)
    def repos(self):
        shown = [r for r in self._config.repos if self._filter == "all" or r.host == self._filter]
        return [self._repo_dict(r) for r in sorted(shown, key=lambda r: r.name.lower())]

    @Property("QVariantMap", notify=reposChanged)
    def counts(self):
        hosts = [r.host for r in self._config.repos]
        return {"all": len(hosts), "github": hosts.count("github"), "gitlab": hosts.count("gitlab")}

    def _get_filter(self):
        return self._filter

    def _set_filter(self, value):
        if value in FILTERS and value != self._filter:
            self._filter = value
            self.filterChanged.emit()
            self.reposChanged.emit()

    filter = Property(str, _get_filter, _set_filter, notify=filterChanged)

    @Property(str, constant=True)
    def configError(self):
        return self._config_error

    @Property(bool, notify=addingChanged)
    def adding(self):
        return self._adding

    # -- settings ---------------------------------------------------------------------------------------------------

    @Property("QVariantMap", notify=settingsChanged)
    def settings(self):
        s = self._config.settings
        return {
            "firstLaunchDone": s.first_launch_done,
            "autoCheck": s.auto_check,
            "checkIntervalHours": s.check_interval_hours,
            "toasts": s.toasts,
            "scanning": s.scanning,
            "deleteOld": s.delete_old,
            "deleteOldDays": s.delete_old_days,
        }

    @Property("QVariantList", constant=True)
    def checkIntervals(self):
        return list(config.CHECK_INTERVALS_HOURS)

    @Property("QVariantList", constant=True)
    def deleteAfterDays(self):
        return list(config.DELETE_AFTER_DAYS)

    @Slot("QVariantMap")
    def updateSettings(self, changes):
        """Change any of the settings (same names as the `settings` property) and save. Unknown names and values
        outside the offered choices are ignored."""
        s = self._config.settings
        bools = {"firstLaunchDone": "first_launch_done", "autoCheck": "auto_check", "toasts": "toasts",
                 "scanning": "scanning", "deleteOld": "delete_old"}
        for key, attr in bools.items():
            if isinstance(changes.get(key), bool):
                setattr(s, attr, changes[key])
        if int(changes.get("checkIntervalHours", 0) or 0) in config.CHECK_INTERVALS_HOURS:
            s.check_interval_hours = int(changes["checkIntervalHours"])
        if int(changes.get("deleteOldDays", 0) or 0) in config.DELETE_AFTER_DAYS:
            s.delete_old_days = int(changes["deleteOldDays"])
        self._save()
        self.settingsChanged.emit()

    @Slot(str, result="QVariantMap")
    def repo(self, repo_id):
        r = self._config.find(repo_id)
        return self._repo_dict(r) if r else {}

    # -- adding and removing ----------------------------------------------------------------------------------------

    @Slot(str, str)
    def addRepo(self, name, url):
        if self._adding:
            return
        try:
            ref = sources.parse_url(url)
        except ValueError as e:
            self.addFailed.emit(str(e))
            return
        if existing := self._config.find(ref.id):
            self.addFailed.emit(f"Already tracking this as “{existing.name}”.")
            return

        def work():
            info = sources.project_info(ref)
            rels = sources.releases(info.ref, info.host)
            default, branches, branch_error = _fetch_branches(info.ref)
            return info, rels, default, branches, branch_error

        def done(result, error):
            self._adding = False
            self.addingChanged.emit()
            if error:
                self.addFailed.emit(self._error_text(error))
                return
            info, rels, default, branches, branch_error = result
            # The address may have redirected to a project we already track (renamed or moved).
            if existing := self._config.find(info.ref.id):
                self.addFailed.emit(f"Already tracking this as “{existing.name}”.")
                return
            repo = TrackedRepo(
                id=info.ref.id,
                name=name.strip() or info.name,
                url=info.ref.web_url,
                host=info.host,
                branch=default or info.default_branch,
                description=info.description,
                added_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            )
            if rels:
                self._auto_pick(repo, rels)
            else:
                repo.follow, repo.kind = FOLLOW_BRANCH, assets.KIND_GIT
            self._details[repo.id] = Details(
                state="ready", releases=rels,
                default_branch=default or info.default_branch, branches=branches, branch_error=branch_error,
            )
            self._config.repos.append(repo)
            self._changed()
            self.addFinished.emit(repo.id)

        self._adding = True
        self.addingChanged.emit()
        self._run(work, done)

    @staticmethod
    def _auto_pick(repo: TrackedRepo, rels: list[sources.Release]):
        """If the newest release has exactly one file that suits this computer, pick it. The user can change it."""
        latest = next((r for r in rels if not r.prerelease), rels[0])
        suitable = [a for a in latest.assets if assets.classify(a.name, a.url).suits]
        if len(suitable) == 1:
            a = suitable[0]
            repo.asset_pattern = assets.pattern_for(a.name, latest.tag)
            repo.kind = assets.classify(a.name, a.url).kind

    @Slot(str)
    def removeRepo(self, repo_id):
        self._config.repos = [r for r in self._config.repos if r.id != repo_id]
        self._details.pop(repo_id, None)
        self._changed()

    # -- the repo page ----------------------------------------------------------------------------------------------

    @Slot(str, bool)
    def loadDetails(self, repo_id, force):
        repo = self._config.find(repo_id)
        if not repo:
            return
        current = self._details.get(repo_id)
        if current and (current.state == "loading" or (current.state == "ready" and not force)):
            return
        self._details[repo_id] = Details(state="loading")
        self.detailsChanged.emit(repo_id)
        ref, host = RepoRef.from_id(repo_id), repo.host

        # One API request (the releases). Branches come from git, which doesn't count against API limits.
        def work():
            rels = sources.releases(ref, host)
            default, branches, branch_error = _fetch_branches(ref)
            return rels, default, branches, branch_error

        def done(result, error):
            if not self._config.find(repo_id):
                return  # removed while loading
            if error:
                self._details[repo_id] = Details(state="error", error=self._error_text(error))
            else:
                rels, default, branches, branch_error = result
                self._details[repo_id] = Details(
                    state="ready", releases=rels, default_branch=default, branches=branches, branch_error=branch_error,
                )
            self.detailsChanged.emit(repo_id)

        self._run(work, done)

    @Slot(str, result="QVariantMap")
    def details(self, repo_id):
        repo = self._config.find(repo_id)
        d = self._details.get(repo_id) or Details(state="loading")
        shown = [r for r in d.releases if repo and (repo.prereleases or not r.prerelease)]
        pattern = repo.asset_pattern if repo else ""
        releases = []
        for i, rel in enumerate(shown):
            files = []
            for a in rel.assets:
                info = assets.classify(a.name, a.url)
                details = [x for x in (_size_text(a.size), info.kind if info.kind != assets.KIND_OTHER else "",
                                       info.note) if x]
                files.append({
                    "name": a.name,
                    "details": " · ".join(details),
                    "suits": info.suits,
                    "selected": assets.matches(pattern, a.name),
                })
            releases.append({
                "tag": rel.tag,
                "title": rel.title,
                "date": _date_text(rel.date),
                "prerelease": rel.prerelease,
                "isLatest": i == 0,
                "notes": rel.notes,
                "url": rel.url,
                "assets": files,
                "hasSelected": any(f["selected"] for f in files),
            })
        current_branch = (repo.branch if repo else "") or d.default_branch
        # The one place to choose which file to follow: the newest release's files, those for this PC first.
        latest = releases[0] if releases else None
        choices = sorted(latest["assets"], key=lambda f: not f["suits"]) if latest else []
        return {
            "state": d.state,
            "error": d.error,
            "description": repo.description if repo else "",
            "hasReleases": bool(d.releases),
            "releases": releases,
            "latestTag": latest["tag"] if latest else "",
            "fileChoices": choices,
            "anyFileSuits": any(f["suits"] for f in choices),
            # A file was picked, but the newest release doesn't have it (renamed or dropped by the project).
            "yourFileMissing": bool(pattern) and latest is not None and not latest["hasSelected"],
            "hiddenPrereleases": sum(1 for r in d.releases if r.prerelease) if repo and not repo.prereleases else 0,
            "branchError": d.branch_error,
            "branches": [
                {"name": b.name, "sha": b.sha[:7], "isDefault": b.name == d.default_branch,
                 "selected": b.name == current_branch}
                for b in d.branches
            ],
        }

    @Slot(str, str)
    def setFollow(self, repo_id, follow):
        repo = self._config.find(repo_id)
        if not repo or follow not in (FOLLOW_RELEASES, FOLLOW_BRANCH) or follow == repo.follow:
            return
        repo.follow = follow
        if follow == FOLLOW_BRANCH:
            repo.kind = assets.KIND_GIT
            if not repo.branch:
                repo.branch = self._details.get(repo_id, Details()).default_branch
        else:
            repo.kind = ""
            if repo.asset_pattern and (d := self._details.get(repo_id)):
                for rel in d.releases:
                    if a := next((a for a in rel.assets if assets.matches(repo.asset_pattern, a.name)), None):
                        repo.kind = assets.classify(a.name, a.url).kind
                        break
        self._changed(repo_id)

    @Slot(str, str)
    def setBranch(self, repo_id, branch):
        if (repo := self._config.find(repo_id)) and branch != repo.branch:
            repo.branch = branch
            self._changed(repo_id)

    @Slot(str, str, str)
    def pickAsset(self, repo_id, tag, asset_name):
        repo = self._config.find(repo_id)
        d = self._details.get(repo_id)
        rel = next((r for r in d.releases if r.tag == tag), None) if d else None
        asset = next((a for a in rel.assets if a.name == asset_name), None) if rel else None
        if not repo or not asset:
            return
        repo.asset_pattern = assets.pattern_for(asset.name, tag)
        repo.kind = assets.classify(asset.name, asset.url).kind
        self._changed(repo_id)

    @Slot(str, bool)
    def setPrereleases(self, repo_id, on):
        if (repo := self._config.find(repo_id)) and on != repo.prereleases:
            repo.prereleases = on
            self._changed(repo_id)
