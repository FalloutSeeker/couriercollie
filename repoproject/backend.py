"""The bridge between the window (QML) and the rest of the app.

The window calls the slots here and shows the properties. Anything that touches the network runs on a worker thread,
so the window never freezes; results are handed back to the main thread through `_deliver`.
"""

import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import Property, QObject, Signal, Slot

from . import assets, config, icons, scan, sources
from .config import FOLLOW_BRANCH, FOLLOW_RELEASES, NOT_INSTALLED, Config, ConfigError, TrackedRepo
from .sources import RepoRef, SourceError

HOST_LABELS = {"github": "GitHub", "gitlab": "GitLab"}
KIND_ICONS = {
    assets.KIND_GIT: "folder-git",
    assets.KIND_RPM: "application-x-rpm",
    assets.KIND_APPIMAGE: "application-vnd.appimage",
    assets.KIND_PROGRAM: "application-x-executable",
    assets.KIND_FILE: "application-x-executable",
    assets.KIND_VERSIONS: "tag",
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
    # How your version relates to the followed branch's newest commit, and the commits you don't have. Only used
    # while your version and the branch's newest are still `commits_base` and `commits_head`. None if it couldn't be
    # compared (e.g. your commit isn't on the site).
    comparison: sources.Comparison | None = None
    commits_base: str = ""
    commits_head: str = ""
    comparing: bool = False  # a comparison for a newly chosen branch is on its way
    compare_request: int = 0  # numbers each comparison request, so a late answer to an older one is ignored
    # A scanned repo that's no longer where the scan found it, and the branch checked out where it was found.
    local_missing: bool = False
    branch_on_disk: str = ""


def _whole_number(value) -> int | None:
    """A number from the window (which may arrive as 24.0), or None for anything else."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


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


def _newest_version(repo: TrackedRepo, d: Details) -> str:
    """The newest version of what the repo follows: the newest full release, or the latest commit on the branch."""
    if repo.follow == FOLLOW_BRANCH:
        return _head(repo, d)
    release = next((r for r in d.releases if not r.prerelease), d.releases[0] if d.releases else None)
    return release.tag if release else ""


def _head(repo: TrackedRepo, d: Details) -> str:
    """The newest commit on the branch the repo follows, or "" if it isn't known."""
    return next((b.sha for b in d.branches if b.name == (repo.branch or d.default_branch)), "")


def _set_baseline(repo: TrackedRepo, d: Details) -> bool:
    """If your version isn't known yet: a repo added by hand starts as "Not installed" (adding it doesn't mean you have
    it); you set your version once you do. A scanned repo's version comes from disk instead."""
    if repo.installed or d.state != "ready" or repo.source == config.SOURCE_SCANNED:
        return False
    repo.installed = NOT_INSTALLED
    return True


def _fit_files(repo: TrackedRepo, d: Details) -> bool:
    """Only files that run on this computer can be followed. A pick of any other file is dropped, and a project with
    nothing for this computer is tracked by version only. Returns True if the repo changed."""
    if repo.follow != FOLLOW_RELEASES or d.state != "ready" or not d.releases:
        return False
    before = (repo.asset_pattern, repo.kind)
    if repo.asset_pattern:
        picked = [a for r in d.releases for a in r.assets if assets.matches(repo.asset_pattern, a.name)]
        if picked and not any(assets.classify(a.name, a.url).suits for a in picked):
            repo.asset_pattern, repo.kind = "", ""
    newest = next((r for r in d.releases if not r.prerelease), d.releases[0])
    nothing_fits = not any(assets.classify(a.name, a.url).suits for a in newest.assets)
    if nothing_fits and not repo.asset_pattern:
        repo.kind = assets.KIND_VERSIONS
    elif repo.kind == assets.KIND_VERSIONS:
        repo.kind = ""  # a later release added something for this computer
    return (repo.asset_pattern, repo.kind) != before


def _match_tag(repo: TrackedRepo, d: Details) -> bool:
    """A version found on disk ("1.18.2", from an RPM or AppImage) as the release's tag ("v1.18.2")."""
    if repo.follow != FOLLOW_RELEASES or not repo.installed or repo.installed == NOT_INSTALLED or d.state != "ready":
        return False
    tags = [r.tag for r in d.releases]
    if repo.installed in tags:
        return False
    version = assets.version_of(repo.installed)
    tag = next((t for t in tags if version and assets.version_of(t) == version), None)
    if tag:
        repo.installed = tag
    return bool(tag)


def _join_folders(folders: list[str]) -> str:
    """"~", "/opt", "/usr/local" -> "the home folder, /opt, and /usr/local"."""
    names = ["the home folder" if f == "~" else f for f in folders]
    if len(names) <= 2:
        return " and ".join(names)
    return ", ".join(names[:-1]) + ", and " + names[-1]


def _compare(ref: RepoRef, host: str, yours: str, head: str) -> sources.Comparison | None:
    """How your version relates to a branch's newest commit. None if there's nothing to compare, or it couldn't be."""
    if not head or not yours or yours == NOT_INSTALLED:
        return None
    try:
        return sources.compare(ref, host, yours, head)
    except SourceError:
        return None


def _on_disk(scanned: bool, local_path: str) -> tuple[tuple[str, bool] | None, str]:
    """A scanned repo's (version, still there) and checked-out branch, read from disk."""
    if not scanned:
        return None, ""
    return scan.version_on_disk(local_path), scan.branch_on_disk(local_path)


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
    scanChanged = Signal()
    saveErrorChanged = Signal()
    _deliver = Signal(object)

    def __init__(self, config_path: Path | None = None, parent=None, find_icons: bool = False):
        """`find_icons`: look up icons for repos (icons.py). Off by default so tests don't reach the network; the
        app turns it on."""
        super().__init__(parent)
        self._find_icons = find_icons
        self._icons_pending: set[str] = set()
        self._path = config_path
        self._config_error = ""
        self._save_error = ""
        try:
            self._config = config.load(config_path)
        except ConfigError as e:
            # Start empty, and don't save, so the broken file isn't overwritten.
            self._config = Config()
            self._config_error = str(e)
        self._filter = "all"
        self._adding = False
        self._details: dict[str, Details] = {}
        self._scan_state = "idle"  # "idle", "scanning" or "done"
        self._scan_error = ""
        self._scan_items: list[dict] = []  # for the results dialog
        self._scan_finds: dict[int, scan.Found] = {}  # by item key
        self._scan_updated: list[str] = []  # names of tracked repos updated by the last scan
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
        if self._config_error:
            return
        try:
            config.save(self._config, self._path)
            error = ""
        except OSError as e:
            path = self._path or config.default_path()
            error = (f"Couldn\u2019t save to {path.parent} ({e.strerror or e}). Changes are kept while RepoProject is "
                     "open, and saved once that folder can be written to.")
        if error != self._save_error:
            self._save_error = error
            self.saveErrorChanged.emit()

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
        elif r.kind == assets.KIND_VERSIONS:
            follow_text = "Versions only (nothing for this computer)"
        else:
            follow_text = "No build file picked yet"
        return {
            "id": r.id,
            "name": r.name,
            "url": r.url,
            "hostLabel": HOST_LABELS.get(r.host, r.host),
            "domain": ref.domain,
            "path": ref.path,
            "follow": r.follow,
            "assetPattern": r.asset_pattern,
            "prereleases": r.prereleases,
            "icon": self._icon_source(r),
            "followText": follow_text,
            "scanned": r.source == config.SOURCE_SCANNED,
            "localPath": r.local_path,
        }

    @staticmethod
    def _icon_source(r: TrackedRepo) -> str:
        """What the window shows: the icon found for the repo, or the default for its kind (also if a found picture
        has since been deleted)."""
        if r.icon.startswith("theme:"):
            return r.icon.removeprefix("theme:")
        if r.icon.startswith("file:") and Path(r.icon.removeprefix("file:")).is_file():
            return "file://" + r.icon.removeprefix("file:")
        return KIND_ICONS.get(r.kind, "package-x-generic")

    # -- icons ------------------------------------------------------------------------------------------------------

    @Slot()
    def loadIcons(self):
        """Called when the list first shows: look up icons for repos that have never had one looked up."""
        for r in self._config.repos:
            self._find_icon(r.id)

    def _find_icon(self, repo_id: str, icon_url: str | None = None):
        """Look up a repo's icon, once: the result is saved, including "none found". If the site couldn't be
        reached, nothing is saved, so it's tried again the next time the window loads."""
        repo = self._config.find(repo_id)
        if not self._find_icons or not repo or repo.icon or repo_id in self._icons_pending:
            return
        self._icons_pending.add(repo_id)
        name, local_path = repo.name, repo.local_path

        def done(result, error):
            self._icons_pending.discard(repo_id)
            if error or not (repo := self._config.find(repo_id)):
                return  # unreachable (icons.Unreachable) or removed meanwhile
            repo.icon = result
            self._changed()

        self._run(lambda: icons.resolve(repo_id, name, local_path, icon_url), done)

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

    @Property(str, notify=saveErrorChanged)
    def saveError(self):
        return self._save_error

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
            "scanFolders": [
                {"path": f, "label": "Home folder (~)" if f == "~" else f,
                 "isDefault": f in config.DEFAULT_SCAN_FOLDERS}
                for f in s.scan_folders
            ],
            "scanFoldersAreDefault": s.scan_folders == config.DEFAULT_SCAN_FOLDERS,
            "scanFoldersText": _join_folders(s.scan_folders),
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
        if (hours := _whole_number(changes.get("checkIntervalHours"))) in config.CHECK_INTERVALS_HOURS:
            s.check_interval_hours = hours
        if (days := _whole_number(changes.get("deleteOldDays"))) in config.DELETE_AFTER_DAYS:
            s.delete_old_days = days
        self._save()
        self.settingsChanged.emit()

    @Slot(str)
    def addScanFolder(self, folder):
        """Add a folder to scan. Takes a path or a file:// link (from the folder picker)."""
        path = urllib.parse.unquote(folder.removeprefix("file://"))
        if not path:
            return
        home = str(Path.home())
        if path == home or path.startswith(home + "/"):
            path = "~" + path[len(home):]  # stays right if the home folder moves
        if path not in self._config.settings.scan_folders:
            self._config.settings.scan_folders.append(path)
            self._save()
            self.settingsChanged.emit()

    @Slot(str)
    def removeScanFolder(self, folder):
        if folder in self._config.settings.scan_folders:
            self._config.settings.scan_folders.remove(folder)
            self._save()
            self.settingsChanged.emit()

    @Slot()
    def resetScanFolders(self):
        self._config.settings.scan_folders = list(config.DEFAULT_SCAN_FOLDERS)
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
        if existing := self._config.find_any(ref.id):
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
            if existing := self._config.find_any(info.ref.id):
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
                # The typed address, if the site redirected (renamed or moved project).
                aliases=[ref.id] if ref.id.lower() != info.ref.id.lower() else [],
            )
            if rels:
                self._auto_pick(repo, rels)
            else:
                repo.follow, repo.kind = FOLLOW_BRANCH, assets.KIND_GIT
            details = Details(
                state="ready", releases=rels,
                default_branch=default or info.default_branch, branches=branches, branch_error=branch_error,
            )
            self._details[repo.id] = details
            _set_baseline(repo, details)
            _fit_files(repo, details)
            self._config.repos.append(repo)
            self._changed()
            self.addFinished.emit(repo.id)
            self._find_icon(repo.id, info.icon_url)

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
        if (repo := self._config.find(repo_id)) and repo.icon.startswith("file:"):
            picture = Path(repo.icon.removeprefix("file:"))
            if picture.parent == icons.cache_dir():
                picture.unlink(missing_ok=True)
        self._config.repos = [r for r in self._config.repos if r.id != repo_id]
        self._details.pop(repo_id, None)
        self._changed()

    # -- scanning ---------------------------------------------------------------------------------------------------

    @Property(str, notify=scanChanged)
    def scanState(self):
        return self._scan_state

    @Property(str, notify=scanChanged)
    def scanError(self):
        return self._scan_error

    @Property("QVariantList", notify=scanChanged)
    def scanItems(self):
        return self._scan_items

    @Property("QVariantList", notify=scanChanged)
    def scanUpdated(self):
        return self._scan_updated

    @Slot()
    def startScan(self):
        """Look through this computer (DESIGN.md §1). Repos already on the list are updated straight away; new finds
        are listed for the user to choose from."""
        if self._scan_state == "scanning" or not self._config.settings.scanning:
            return
        # Addresses already on the list: those finds need no request to their site.
        known = {r.id.lower() for r in self._config.repos} | {a.lower() for r in self._config.repos for a in r.aliases}

        folders = list(self._config.settings.scan_folders)

        def work():
            return scan.identify(scan.find_all(folders), known=lambda repo_id: repo_id.lower() in known)

        self._scan_state, self._scan_error = "scanning", ""
        self.scanChanged.emit()
        self._run(work, self._scan_done)

    def _scan_done(self, checked, error):
        self._scan_state = "done"
        self._scan_items, self._scan_finds, self._scan_updated = [], {}, []
        if error:
            self._scan_error = self._error_text(error)
            self.scanChanged.emit()
            return
        self._scan_error = ""
        on_list = []
        for key, c in enumerate(checked):
            f = c.found
            tracked = next((r for a in (f.id, *f.aliases) if (r := self._config.find_any(a))), None)
            if tracked and not c.problem:
                on_list.append(f)
                continue
            similar = None if c.problem else scan.looks_like(self._config, f)
            if similar:
                note = (f"Looks like \u201c{similar.name}\u201d, which you track from {similar.url}. "
                        "Tick it to link the two; it won’t be added twice.")
            elif c.problem:
                note = c.problem
            else:
                notes = []
                if f.other_paths:
                    notes.append("Also in 1 other place." if len(f.other_paths) == 1
                                 else f"Also in {len(f.other_paths)} other places.")
                if f.needs_password:
                    notes.append("Its folder belongs to the system, so updating it will ask for your password.")
                note = " ".join(notes)
            self._scan_finds[key] = f
            self._scan_items.append({
                "key": key,
                "name": f.name,
                "address": f.id,
                "path": f.path,
                "kind": f.kind,
                "icon": KIND_ICONS.get(f.kind, "package-x-generic"),
                "status": "problem" if c.problem else ("similar" if similar else "new"),
                "similarTo": similar.id if similar else "",
                "note": note,
            })
        if on_list:
            result = scan.merge(self._config, on_list)
            self._scan_updated = [r.name for r in result.updated]
            for r in result.updated:
                self._details.pop(r.id, None)  # reload with the version found on disk
            self._changed()
        self.scanChanged.emit()

    @Slot("QVariantList")
    def trackFound(self, keys):
        """Track the scan finds the user ticked. A find that looks like a tracked repo is linked to it, not added."""
        keys = {int(k) for k in keys}
        chosen = []
        for item in self._scan_items:
            if item["key"] not in keys or item["status"] == "problem":
                continue
            found = self._scan_finds[item["key"]]
            if item["similarTo"] and (repo := self._config.find(item["similarTo"])):
                found = scan.link_to(found, repo)
            chosen.append(found)
        if not chosen:
            return
        result = scan.merge(self._config, chosen)
        for r in result.added:
            self._find_icon(r.id)
        self._scan_items = [i for i in self._scan_items if i["key"] not in keys or i["status"] == "problem"]
        self._changed()
        self.scanChanged.emit()

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
        scanned, local_path = repo.source == config.SOURCE_SCANNED, repo.local_path
        follow, branch, installed = repo.follow, repo.branch, repo.installed

        # One API request for the releases, and one for what's new on a branch you're behind on. Branches and the
        # version on disk come from git, which doesn't count against API limits.
        def work():
            on_disk, branch_on_disk = _on_disk(scanned, local_path)
            rels = sources.releases(ref, host)
            default, branches, branch_error = _fetch_branches(ref)
            yours = on_disk[0] if on_disk and on_disk[0] else installed
            head = next((b.sha for b in branches if b.name == (branch or default)), "")
            comparison = _compare(ref, host, yours, head) if follow == FOLLOW_BRANCH else None
            return rels, default, branches, branch_error, on_disk, branch_on_disk, yours, head, comparison

        def done(result, error):
            if not self._config.find(repo_id):
                return  # removed while loading
            if error:
                self._details[repo_id] = Details(state="error", error=self._error_text(error))
            else:
                rels, default, branches, branch_error, on_disk, branch_on_disk, yours, head, comparison = result
                self._details[repo_id] = Details(
                    state="ready", releases=rels, default_branch=default, branches=branches, branch_error=branch_error,
                    comparison=comparison, commits_base=yours, commits_head=head,
                    local_missing=bool(on_disk) and not on_disk[1], branch_on_disk=branch_on_disk,
                )
                if repo := self._config.find(repo_id):
                    # A scanned repo's version is whatever's on disk now (e.g. after a `git pull` outside the app).
                    from_disk = bool(on_disk and on_disk[0] and on_disk[0] != repo.installed)
                    if from_disk:
                        repo.installed = on_disk[0]
                    baseline_set = _set_baseline(repo, self._details[repo_id])
                    tag_matched = _match_tag(repo, self._details[repo_id])
                    if _fit_files(repo, self._details[repo_id]) or baseline_set or tag_matched or from_disk:
                        self._changed()
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
                "isInstalled": bool(repo) and rel.tag == repo.installed,
            })
        current_branch = (repo.branch if repo else "") or d.default_branch
        # The one place to choose which file to follow: the newest release's files, those for this PC first.
        latest = releases[0] if releases else None
        # Only files that run on this computer can be chosen.
        choices = [f for f in latest["assets"] if f["suits"]] if latest else []
        version = self._version_info(repo, d, shown) if repo and d.state == "ready" else {}
        c = self._current_comparison(repo, d) if repo else None
        behind = c is not None and c.relation == sources.BEHIND
        return {
            "newCommits": [{"sha": x.sha[:7], "title": x.title} for x in c.commits[:5]] if behind else [],
            "newCommitsTotal": c.total if behind else 0,
            "branchOnDisk": d.branch_on_disk,
            "versionFromDisk": bool(repo) and repo.source == config.SOURCE_SCANNED,
            "localMissing": d.local_missing,
            **{"versionText": "", "installed": "", "status": "", "updateAvailable": False}, **version,
            "state": d.state,
            "error": d.error,
            "description": repo.description if repo else "",
            "hasReleases": bool(d.releases),
            "releases": releases,
            "latestTag": latest["tag"] if latest else "",
            "fileChoices": choices,
            # Nothing in the newest release runs on this computer: tracked by version only.
            "versionOnly": latest is not None and not choices,
            # A file was picked, but the newest release doesn't have it (renamed or dropped by the project).
            "yourFileMissing": bool(pattern) and latest is not None and not latest["hasSelected"],
            "branchError": d.branch_error,
            "branches": [
                {"name": b.name, "sha": b.sha[:7], "isDefault": b.name == d.default_branch,
                 "selected": b.name == current_branch}
                for b in d.branches
            ],
        }

    @staticmethod
    def _current_comparison(repo: TrackedRepo, d: Details) -> sources.Comparison | None:
        """The comparison, if it's for your version and the followed branch's newest commit as they are now."""
        if d.comparing or d.commits_base != repo.installed or d.commits_head != _head(repo, d):
            return None
        return d.comparison

    def _version_info(self, repo: TrackedRepo, d: Details, shown: list[sources.Release]) -> dict:
        """Your version as text, and a status line comparing it with the newest."""
        installed = repo.installed
        if repo.follow == FOLLOW_BRANCH:
            branch = repo.branch or d.default_branch
            newest = _head(repo, d)
            if not newest:
                return {}
            yours_text = f"commit {installed[:7]}"
            if installed and installed not in (NOT_INSTALLED, newest):
                return {"versionText": yours_text, "installed": installed,
                        **self._branch_status(repo, d, branch, yours_text)}
            newest_text, newer_text = f"commit {newest[:7]}", f"Newer commits on {branch}"
        else:
            if not shown:
                return {}
            newest = shown[0].tag
            newest_text, yours_text = newest, installed
            newer_text = f"Newer version available: {newest}"
        if installed == NOT_INSTALLED:
            text, status, update = "Not installed", f"The newest is {newest_text}.", False
        elif installed == newest:
            text, status, update = yours_text, "Up to date", False
        elif installed:
            text, status, update = yours_text, f"{newer_text} (you have {yours_text})", True
        else:
            text, status, update = "", "", False
        return {"versionText": text, "installed": installed, "status": status, "updateAvailable": update}

    def _branch_status(self, repo: TrackedRepo, d: Details, branch: str, yours_text: str) -> dict:
        """Status when your commit isn't the branch's newest: depends on how the two relate."""
        c = self._current_comparison(repo, d)
        if d.comparing:
            return {"status": "Checking\u2026", "updateAvailable": False}
        if c is None:
            site = RepoRef.from_id(repo.id).domain
            return {"status": f"Couldn\u2019t compare your version ({yours_text}) with {branch}. {site} may not have "
                              "that commit (for example, one that was never pushed), or couldn\u2019t be reached; "
                              "Refresh tries again.",
                    "updateAvailable": False}
        if c.relation == sources.BEHIND:
            return {"status": f"Newer commits on {branch} (you have {yours_text})", "updateAvailable": True}
        if c.relation == sources.AHEAD:
            return {"status": f"Your version is newer than {branch}", "updateAvailable": False}
        if c.relation == sources.SAME:
            return {"status": "Up to date", "updateAvailable": False}
        where = f"your clone is on {d.branch_on_disk}" if d.branch_on_disk and d.branch_on_disk != branch \
            else f"your version ({yours_text}) isn\u2019t part of it"
        return {"status": f"Not comparable with {branch}: {where}.", "updateAvailable": False}

    @Slot(str)
    def markUpToDate(self, repo_id):
        """Set your version to the newest one shown (the newest release, or the latest commit on the branch)."""
        repo, d = self._config.find(repo_id), self._details.get(repo_id)
        if not repo or not d or d.state != "ready":
            return
        if repo.follow == FOLLOW_BRANCH:
            newest = _newest_version(repo, d)
        else:
            shown = [r for r in d.releases if repo.prereleases or not r.prerelease]
            newest = shown[0].tag if shown else ""
        self.setInstalled(repo_id, newest)

    @Slot(str, str)
    def setInstalled(self, repo_id, version):
        if (repo := self._config.find(repo_id)) and version and version != repo.installed:
            repo.installed = version
            self._changed(repo_id)
            if repo.follow == FOLLOW_BRANCH:
                self._refresh_whats_new(repo_id)  # compare the new version with the branch

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
        repo.installed = ""
        _set_baseline(repo, self._details.get(repo_id, Details()))
        _fit_files(repo, self._details.get(repo_id, Details()))
        self._changed(repo_id)

    @Slot(str, str)
    def setBranch(self, repo_id, branch):
        """Choose which branch to compare against. Your version stays as it is: for a scanned repo it's re-read from
        disk, and the list of new commits is refreshed for the new branch."""
        repo = self._config.find(repo_id)
        if not repo or branch == repo.branch:
            return
        repo.branch = branch
        _set_baseline(repo, self._details.get(repo_id, Details()))  # only if your version isn't known yet
        self._changed(repo_id)
        self._refresh_whats_new(repo_id)

    def _refresh_whats_new(self, repo_id):
        repo, d = self._config.find(repo_id), self._details.get(repo_id)
        if not repo or not d or d.state != "ready":
            return
        ref, host = RepoRef.from_id(repo_id), repo.host
        scanned, local_path, installed = repo.source == config.SOURCE_SCANNED, repo.local_path, repo.installed
        head = _head(repo, d)
        d.comparing = True
        d.compare_request += 1
        request = d.compare_request
        self.detailsChanged.emit(repo_id)

        def work():
            on_disk, branch_on_disk = _on_disk(scanned, local_path)
            yours = on_disk[0] if on_disk and on_disk[0] else installed
            return on_disk, branch_on_disk, yours, _compare(ref, host, yours, head)

        def done(result, error):
            repo, d = self._config.find(repo_id), self._details.get(repo_id)
            if not repo or not d or d.compare_request != request:
                return  # removed, reloaded, or a newer comparison was asked for since
            d.comparing = False
            if error:
                self.detailsChanged.emit(repo_id)
                return
            on_disk, branch_on_disk, yours, comparison = result
            d.comparison, d.commits_base, d.commits_head = comparison, yours, head
            d.local_missing, d.branch_on_disk = bool(on_disk) and not on_disk[1], branch_on_disk
            if on_disk and on_disk[0] and on_disk[0] != repo.installed:
                repo.installed = on_disk[0]
                self._changed(repo_id)
            else:
                self.detailsChanged.emit(repo_id)

        self._run(work, done)

    @Slot(str, str, str)
    def pickAsset(self, repo_id, tag, asset_name):
        repo = self._config.find(repo_id)
        d = self._details.get(repo_id)
        rel = next((r for r in d.releases if r.tag == tag), None) if d else None
        asset = next((a for a in rel.assets if a.name == asset_name), None) if rel else None
        if not repo or not asset or not assets.classify(asset.name, asset.url).suits:
            return
        repo.asset_pattern = assets.pattern_for(asset.name, tag)
        repo.kind = assets.classify(asset.name, asset.url).kind
        self._changed(repo_id)

    @Slot(str, bool)
    def setPrereleases(self, repo_id, on):
        if (repo := self._config.find(repo_id)) and on != repo.prereleases:
            repo.prereleases = on
            self._changed(repo_id)
