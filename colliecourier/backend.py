"""The bridge between the window (QML) and the rest of the app.

The window calls the slots here and shows the properties. Anything that touches the network runs on a worker thread,
so the window never freezes; results are handed back to the main thread through `_deliver`.
"""

import dataclasses
import os
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PySide6.QtCore import Property, QFileSystemWatcher, QObject, QProcess, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from . import assets, checker, config, icons, integration, packages, scan, sources, updater
from .account import Account
from .updating import (Updating, _can_clone, _can_update, _head, _is_appimage, _is_clone, _is_flatpak, _is_package, _is_program,
                       _needs_password, _newest_version)
from .config import FOLLOW_BRANCH, FOLLOW_RELEASES, NOT_INSTALLED, Config, ConfigError, TrackedRepo
from .sources import RepoRef, SourceError

KIND_ICONS = {
    assets.KIND_GIT: "folder-git",
    assets.KIND_RPM: "application-x-rpm",
    assets.KIND_DEB: "application-vnd.debian.binary-package",
    assets.KIND_ARCH: "package-x-generic",
    assets.KIND_FLATPAK: "application-vnd.flatpak",
    assets.KIND_APPIMAGE: "application-vnd.appimage",
    assets.KIND_PROGRAM: "application-x-executable",
    assets.KIND_FILE: "application-x-executable",
    assets.KIND_VERSIONS: "tag",
}
FILTERS = ("all", "github", "gitlab")
# How your version compares with the newest, for the repo page's status box (colour and icon).
STATUS_UPDATE, STATUS_CURRENT, STATUS_NOT_INSTALLED = "update", "current", "notInstalled"
STATUS_AHEAD, STATUS_CHECKING, STATUS_PROBLEM = "ahead", "checking", "problem"
# The heading for repos that aren't in one of your categories.
UNCATEGORIZED = "Uncategorized"
# Releases a repo's page loads at first; Show Older Releases loads a full page (sources.RELEASES_PER_PAGE).
PAGE_RELEASES = 10


@dataclass
class Details:
    """What a repo's page fetched: kept in memory only, until the app closes (check results are kept in their own file,
    checker.py)."""

    state: str = "loading"  # "loading", "ready" or "error"
    error: str = ""
    releases: list[sources.Release] = field(default_factory=list)
    more_releases: bool = False  # the site may have older ones (Show Older Releases)
    loading_more: bool = False
    more_error: str = ""
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
    # A scanned clone's install scripts (updater.install_scripts), offered to run by hand.
    install_scripts: list[str] = field(default_factory=list)


def _version_text(version: str) -> str:
    """A version as shown: "commit abc1234" for a commit, else the tag as it is."""
    is_commit = len(version) == 40 and all(c in "0123456789abcdef" for c in version)
    return f"commit {version[:7]}" if is_commit else version


def _whole_number(value) -> int | None:
    """A number from the window (which may arrive as 24.0), or None for anything else."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _plus_hours(when: str, hours: int) -> str:
    try:
        return (datetime.fromisoformat(when) + timedelta(hours=hours)).isoformat()
    except ValueError:
        return ""


def _when_text(when: str) -> str:
    """"14:02" today, "yesterday 14:02", "tomorrow 14:02", else "12 Oct 14:02"."""
    try:
        moment = datetime.fromisoformat(when).astimezone()
    except ValueError:
        return ""
    days = (moment.date() - datetime.now().astimezone().date()).days
    day = {0: "", -1: "yesterday ", 1: "tomorrow "}.get(days, f"{moment:%-d %b} ")
    return f"{day}{moment:%H:%M}"


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


_MD_IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)[^)]*\)")
_HTML_IMAGE = re.compile(r"<img\b[^>]*?src=[\"']([^\"']+)[\"'][^>]*>", re.I)


def _without_images(notes: str) -> str:
    """Release notes with each picture replaced by a link to it: the window would otherwise download every picture in
    them from wherever it's hosted, just for opening the notes."""
    notes = _MD_IMAGE.sub(lambda m: f"[picture: {m.group(1) or 'image'}]({m.group(2)})", notes)
    return _HTML_IMAGE.sub(lambda m: f"[picture]({m.group(1)})", notes)


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
    if repo.follow != FOLLOW_RELEASES or d.state != "ready" or not d.releases or _is_clone(repo):
        return False  # a clone following releases follows the source at each release's tag, not a file
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


def _folder_problem(folder: str) -> str:
    """Why a scan would skip this folder, or "". A scan runs as you and never asks for a password, so a folder you
    can't open is skipped; this says so rather than leaving it to look empty."""
    path = Path(folder).expanduser()
    if path.is_dir():
        return "" if os.access(path, os.R_OK | os.X_OK) else "You can\u2019t open this folder, so scans skip it."
    return "Not a folder, so scans skip it." if path.exists() else "Not found, so scans skip it."


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
    if yours == head:
        return sources.Comparison(sources.SAME)  # no need to ask
    try:
        return sources.compare(ref, host, yours, head)
    except SourceError:
        return None


def _on_disk(scanned: bool, local_path: str, releases: bool = False) -> tuple[tuple[str, bool] | None, str]:
    """A scanned repo's (version, still there) and checked-out branch, read from disk. A clone following releases is
    at a release tag, if it's at one."""
    if not scanned:
        return None, ""
    return scan.version_on_disk(local_path, releases), scan.branch_on_disk(local_path)


def _fetch_branches(ref: RepoRef) -> tuple[str, list[sources.Branch], str]:
    try:
        default, branches = sources.branches(ref)
        return default, branches, ""
    except SourceError as e:
        return "", [], str(e)


class Backend(QObject, Updating, Account):
    reposChanged = Signal()
    filterChanged = Signal()
    addingChanged = Signal()
    addFinished = Signal(str)  # repo id
    addFailed = Signal(str)  # message for the user
    updateFailed = Signal(str)  # repo id; why is in its details ("updateNote")
    detailsChanged = Signal(str)  # repo id
    settingsChanged = Signal()
    scanChanged = Signal()
    checksChanged = Signal()
    activateRequested = Signal()  # bring the window to the front (a second launch, or a notification was clicked)
    saveErrorChanged = Signal()
    githubChanged = Signal()
    _deliver = Signal(object)

    def __init__(self, config_path: Path | None = None, parent=None, find_icons: bool = False,
                 desktop: bool = False):
        """`find_icons`: look up icons for repos (icons.py). `desktop`: notifications, the taskbar badge, and the
        background-check timer (integration.py). Both off by default, so tests stay off the network and the desktop;
        the app turns them on."""
        super().__init__(parent)
        self._find_icons = find_icons
        # How long a branch must stay chosen before what's new on it is asked for (_refresh_whats_new).
        self.compare_delay_ms = 400
        self._init_updates()
        self._unsupported_hosts: set[str] = set()  # sites a scan found the app can't talk to, while it's open
        self._desktop = desktop
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
        # Check results live in their own file (checker.py); next to the settings file when one is given (tests).
        self._state_path = config_path.parent / "checks.json" if config_path else checker.state_path()
        self._checks = checker.load_state(self._state_path)
        self._init_account()
        self._checking = False
        self._check_error = ""
        self._notifications: list[QProcess] = []
        # The background checker writes the results file when the app isn't open; pick up changes made meanwhile.
        self._watcher = QFileSystemWatcher(self)
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._watcher.addPath(str(self._state_path.parent))
        self._watcher.directoryChanged.connect(self._reload_checks)
        if self._desktop and not self._config_error:
            integration.set_background_checks(self._config.settings.auto_check)
            self._update_badge()

    def shutdown(self):
        self._signin_cancel.set()  # a sign-in waiting for its code to be entered stops
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
            error = (f"Couldn\u2019t save to {path.parent} ({e.strerror or e}). Changes are kept while colliecourier "
                     "is open, and saved once that folder can be written to.")
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
        return str(error) if isinstance(error, (SourceError, ValueError, updater.UpdateError)) \
            else f"Something went wrong: {error}"

    def _repo_dict(self, r: TrackedRepo) -> dict:
        ref = RepoRef.from_id(r.id)
        if r.follow == FOLLOW_BRANCH:
            follow_text = f"Branch {r.branch}" if r.branch else "A branch"
        elif _is_clone(r):
            follow_text = "Release tags"
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
            "domain": ref.domain,
            "path": ref.path,
            "follow": r.follow,
            "assetPattern": r.asset_pattern,
            "prereleases": r.prereleases,
            "icon": self._icon_source(r),
            "followText": follow_text,
            "scanned": r.source == config.SOURCE_SCANNED,
            "localPath": r.local_path,
            "shownPath": updater.shown(r.local_path),  # as shown: ~ for your home folder
            "canUpdate": _can_update(r),
            "updateNeedsPassword": _needs_password(r),
            "updating": r.id in self._updating,
            **self._check_dict(r.id),
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

    # -- checking for updates (stage 4) ------------------------------------------------------------------------------

    def _check_dict(self, repo_id: str) -> dict:
        result = self._checks.results.get(repo_id)
        failed = bool(result) and result.status in (checker.FAILED, checker.UNREACHABLE)
        kept = bool(result) and result.not_rechecked
        # A row says it in a few words; why is in its tooltip.
        if failed:
            text, detail = "Couldn\u2019t check", result.text.removeprefix("Couldn\u2019t check: ")
        elif kept:
            text = f"{result.text} (not rechecked)"
            detail = ("The site\u2019s hourly limit for requests was reached" if result.retry_after
                      else "The site couldn\u2019t be reached") + "; this is the last check\u2019s result."
        else:
            text, detail = (result.text if result else ""), ""
        return {
            "checkStatus": result.status if result else "",
            "checkText": text,
            "checkDetail": detail,
            "updateAvailable": bool(result) and result.status == checker.UPDATE,
        }

    @Property(bool, notify=checksChanged)
    def checking(self):
        return self._checking

    @Property("QVariantMap", notify=checksChanged)
    def checks(self):
        """For the list's header: how many updates, when it last checked, when it checks next, and problems."""
        tracked = {r.id for r in self._config.repos}
        results = {k: v for k, v in self._checks.results.items() if k in tracked}
        limited = [v for v in results.values() if v.status == checker.RATE_LIMITED or (v.not_rechecked and v.retry_after)]
        reset = next((v.retry_after for v in limited if v.retry_after), "")
        s = self._config.settings
        return {
            "updates": sum(1 for v in results.values() if v.status == checker.UPDATE),
            # Not checked this time: a failure, or no answer (also when the last result was kept).
            "failed": sum(1 for v in results.values() if v.status in (checker.FAILED, checker.UNREACHABLE)
                          or (v.not_rechecked and not v.retry_after)),
            "checked": len(results),
            "lastChecked": _when_text(self._checks.last_run),
            "nextCheck": _when_text(_plus_hours(self._checks.last_run, s.check_interval_hours))
                         if s.auto_check and self._checks.last_run else "",
            "autoCheck": s.auto_check,
            "rateLimited": len(limited),
            "rateLimitEnds": _when_text(reset),
            "error": self._check_error,
        }

    @Slot()
    def checkNow(self):
        """Check every tracked repo (checker.py). Repos are copied, so changes made while it runs don't mix in."""
        if self._checking:
            return
        repos = [dataclasses.replace(r) for r in self._config.repos]
        previous = self._checks
        self._checking, self._check_error = True, ""
        self.checksChanged.emit()

        def done(result, error):
            self._checking = False
            if error:
                self._check_error = self._error_text(error)
            else:
                self._checks, fresh = result
                try:
                    checker.save_state(self._checks, self._state_path)
                except OSError:
                    pass  # the results still show; they're just not kept for next time
                self._announce(fresh)
                self._update_badge()
                # A check is a fresh look at everything: the last updates' notes ("Pulled 1 new commit.") go.
                for repo_id in [i for i in self._update_notes if i not in self._updating]:
                    self._update_notes.pop(repo_id)
                    self.detailsChanged.emit(repo_id)
                # Repo pages loaded before the check are reloaded when next shown, but only where the check found a
                # newer version than the page has; the rest are still current, so they cost no requests.
                for r in self._config.repos:
                    d, result = self._details.get(r.id), self._checks.results.get(r.id)
                    if d and d.state == "ready" and (not result or result.newest != _newest_version(r, d)):
                        self._details.pop(r.id)
            self.checksChanged.emit()
            self.reposChanged.emit()
            self.githubChanged.emit()  # GitHub may have turned the login down

        self._run(lambda: checker.check_all(repos, previous), done)

    def _version_changed(self, repo: TrackedRepo):
        """Your version changed (set by hand, or read from disk): bring the last check's result for this repo in line
        straight away, using the newest version that check found. No request needed."""
        old = self._checks.results.get(repo.id)
        if not old or not old.newest or old.status not in (checker.UPDATE, checker.UP_TO_DATE, checker.NOT_INSTALLED_YET):
            return
        new = checker.recheck_against(old, repo.installed, by_branch=repo.follow == FOLLOW_BRANCH,
                                      branch=repo.branch)
        if new == old:
            return
        self._checks.results[repo.id] = new
        self._save_checks()

    def _save_checks(self):
        """The check results were changed here (not by a check): keep them, and show them."""
        try:
            checker.save_state(self._checks, self._state_path)
        except OSError:
            pass  # they still show; they're just not kept for next time
        self.checksChanged.emit()
        self._update_badge()

    @Slot(str)
    def handleRequest(self, message):
        """From integration.tell_running_app: "show" (a second launch) or "check" (the background timer)."""
        if message == "show":
            self.activateRequested.emit()
        elif message == "check":
            self.checkNow()

    def _reload_checks(self, *_):
        """The results folder changed. Reloaded only if the results did: our own saves land here too."""
        if not self._checking and (state := checker.load_state(self._state_path)) != self._checks:
            self._checks = state
            self.checksChanged.emit()
            self.reposChanged.emit()
            self._update_badge()

    def _announce(self, fresh: list[str]):
        """A notification for newly found updates, only when the window isn't in front (KDE HIG); with the window in
        front, the list shows them. Clicking it brings the window forward."""
        if not fresh or not self._desktop or not self._config.settings.toasts:
            return
        if QGuiApplication.applicationState() == Qt.ApplicationState.ApplicationActive:
            return
        names = [r.name for r in self._config.repos if r.id in fresh]
        command = integration.notify_command(*integration.updates_message(names))
        if not command:
            return
        process = QProcess(self)
        self._notifications.append(process)

        def finished(*_):
            if bytes(process.readAllStandardOutput()).decode().strip() == "default":
                self.activateRequested.emit()
            self._notifications.remove(process)
            process.deleteLater()

        process.finished.connect(finished)
        process.start(command[0], command[1:])

    def _update_badge(self):
        """The number of repos with updates, on the app's taskbar icon. Plasma removes it when the app closes."""
        if not self._desktop:
            return
        from PySide6.QtDBus import QDBusConnection, QDBusMessage

        count = len([r for r in self._config.repos if self._check_dict(r.id)["updateAvailable"]])
        message = QDBusMessage.createSignal(f"/io/github/{integration.APP_ID}", "com.canonical.Unity.LauncherEntry",
                                            "Update")
        message.setArguments([f"application://{integration.APP_ID}.desktop",
                              {"count": count, "count-visible": count > 0}])
        QDBusConnection.sessionBus().send(message)

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

    def _sections(self) -> list[tuple[str, list[TrackedRepo]]]:
        """(category, repos shown in it) in the order they're listed: Uncategorized first, then your categories. Repos
        keep their order in the settings file, which dragging changes."""
        shown = [r for r in self._config.repos if self._filter == "all" or r.host == self._filter]
        return [(c, [r for r in shown if r.category == c]) for c in ["", *self._config.categories]]

    @Property("QVariantList", notify=reposChanged)
    def repos(self):
        return [self._repo_dict(r) for _, repos in self._sections() for r in repos]

    @Property("QVariantList", notify=reposChanged)
    def rows(self):
        """The list as the window shows it: a heading for each category, followed by its repos. Without categories
        there are no headings, so the list looks as it did before categories."""
        rows = []
        for category, repos in self._sections():
            if self._config.categories:
                rows.append({"kind": "category", "category": category, "label": category or UNCATEGORIZED,
                             "count": len(repos), "total": sum(r.category == category for r in self._config.repos)})
            rows += [{"kind": "repo", "category": category, **self._repo_dict(r)} for r in repos]
        return rows

    @Property("QVariantList", notify=reposChanged)
    def categories(self):
        return list(self._config.categories)

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

    # -- categories -------------------------------------------------------------------------------------------------

    @Slot(str, str, result=str)
    def categoryNameProblem(self, name, renaming=""):
        """Why `name` can't be used for a new category (or for `renaming` one), or "" if it can."""
        name = name.strip()
        if not name:
            return "Type a name for the category."
        if name.lower() == UNCATEGORIZED.lower():
            return f"\u201c{UNCATEGORIZED}\u201d is where repos without a category go. Choose another name."
        if taken := next((c for c in self._config.categories if c != renaming and c.lower() == name.lower()), None):
            return f"There\u2019s already a category called \u201c{taken}\u201d."
        return ""

    @Slot(str, result=str)
    def addCategory(self, name):
        """Adds a category at the end of the list. Returns why it couldn't, or "" if it was added."""
        if problem := self.categoryNameProblem(name):
            return problem
        self._config.categories.append(name.strip())
        self._changed()
        return ""

    @Slot(str, str, result=str)
    def renameCategory(self, name, new_name):
        """Renames a category, keeping its place and its repos. Returns why it couldn't, or "" if it was renamed (or
        the name didn't change)."""
        if name not in self._config.categories:
            return ""
        if problem := self.categoryNameProblem(new_name, name):
            return problem
        new_name = new_name.strip()
        if new_name == name:
            return ""
        cats = self._config.categories
        cats[cats.index(name)] = new_name
        for r in self._config.repos:
            if r.category == name:
                r.category = new_name
        self._changed()
        return ""

    @Slot(str)
    def deleteCategory(self, name):
        """Deletes a category. Its repos aren't removed: they move to the end of Uncategorized."""
        if name not in self._config.categories:
            return
        self._config.categories.remove(name)
        moved = [r for r in self._config.repos if r.category == name]
        self._config.repos = [r for r in self._config.repos if r.category != name] + moved
        for r in moved:
            r.category = ""
        self._changed()

    @Slot(str, str, str)
    def moveRepo(self, repo_id, category, before_id):
        """Moves a repo into `category` ("" for Uncategorized), just before the repo `before_id`, or to the end of the
        category if that's empty or not in it."""
        repo = self._config.find(repo_id)
        if not repo or (category and category not in self._config.categories) or before_id == repo_id:
            return
        repos = [r for r in self._config.repos if r is not repo]
        before = next((i for i, r in enumerate(repos) if r.id == before_id and r.category == category), None)
        if before is None:
            last = [i for i, r in enumerate(repos) if r.category == category]
            before = last[-1] + 1 if last else len(repos)
        repos.insert(before, repo)
        if repos == self._config.repos and repo.category == category:
            return
        repo.category = category
        self._config.repos = repos
        self._changed()

    @Slot(str, str)
    def moveCategory(self, name, before):
        """Moves a category to just before the category `before`, or to the end if that's empty."""
        cats = self._config.categories
        if name not in cats or name == before:
            return
        rest = [c for c in cats if c != name]
        rest.insert(rest.index(before) if before in rest else len(rest), name)
        if rest != cats:
            self._config.categories = rest
            self._changed()

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
                 "isDefault": f in config.DEFAULT_SCAN_FOLDERS, "problem": _folder_problem(f)}
                for f in s.scan_folders
            ],
            "scanFoldersAreDefault": s.scan_folders == config.DEFAULT_SCAN_FOLDERS,
            "scanFoldersText": _join_folders(s.scan_folders),
        }

    @Property("QVariantMap", notify=githubChanged)
    def github(self):
        """Signing in to GitHub, for Settings (account.py)."""
        return self._github_dict()

    @Property(bool, constant=True)
    def styleDrawsProgress(self):
        """Whether the desktop's widget style draws progress bars in the window: KDE's styles (Breeze, Kvantum, …) do;
        Fusion, Qt's own (outside KDE, and in windows off-screen), leaves them blank."""
        app = QApplication.instance()
        return isinstance(app, QApplication) and app.style().name().lower() not in ("fusion", "windows")

    @Property("QVariantList", constant=True)
    def checkIntervals(self):
        return list(config.CHECK_INTERVALS_HOURS)

    @Slot("QVariantMap")
    def updateSettings(self, changes):
        """Change any of the settings (same names as the `settings` property) and save. Unknown names and values
        outside the offered choices are ignored."""
        s = self._config.settings
        bools = {"firstLaunchDone": "first_launch_done", "autoCheck": "auto_check", "toasts": "toasts",
                 "scanning": "scanning"}
        auto_before = s.auto_check
        for key, attr in bools.items():
            if isinstance(changes.get(key), bool):
                setattr(s, attr, changes[key])
        if self._desktop and s.auto_check != auto_before:
            integration.set_background_checks(s.auto_check)
        if (hours := _whole_number(changes.get("checkIntervalHours"))) in config.CHECK_INTERVALS_HOURS:
            s.check_interval_hours = hours
        self._save()
        self.settingsChanged.emit()
        self.checksChanged.emit()  # "next check" depends on these

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
            rels = sources.newest_releases(info.ref, info.host, PAGE_RELEASES, False)
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
                state="ready", releases=rels, more_releases=len(rels) == PAGE_RELEASES,
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
        for kept in (self._details, self._update_notes, self._progress, self._program_choices, self._phases):
            kept.pop(repo_id, None)
        if self._checks.results.pop(repo_id, None):
            self._save_checks()
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
        unsupported = self._unsupported_hosts

        def lookup(ref):
            # A site already found to be unsupported isn't asked again while the app is open.
            if ref.domain in unsupported:
                raise sources.Unsupported(sources.unsupported_text(ref.domain))
            try:
                return sources.project_info(ref)
            except sources.Unsupported:
                unsupported.add(ref.domain)
                raise

        def work():
            return scan.identify(scan.find_all(folders), known=lambda repo_id: repo_id.lower() in known, lookup=lookup)

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
                    # Only a clone that belongs to the system can be updated as root (updater._as_root).
                    notes.append("Its folder belongs to the system, so updating it will ask for your password."
                                 if f.kind == assets.KIND_GIT and updater.needs_password(f.path)
                                 else "Its folder belongs to another user, so it can be tracked but not updated from "
                                      "here.")
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
        # Loaded the first time the page opens after the app starts; again only on Refresh, or when a check found
        # something newer than the page has.
        current = self._details.get(repo_id)
        if current and (current.state == "loading" or (current.state == "ready" and not force)):
            return
        self._update_notes.pop(repo_id, None)  # Refresh: back to the page as it is now, without the last update's note
        self._details[repo_id] = Details(state="loading")
        self.detailsChanged.emit(repo_id)
        ref, host = RepoRef.from_id(repo_id), repo.host
        scanned, local_path = repo.source == config.SOURCE_SCANNED, repo.local_path
        follow, branch, installed, prereleases = repo.follow, repo.branch, repo.installed, repo.prereleases

        # One API request for the releases, and one for what's new on a branch you're behind on. Branches and the
        # version on disk come from git, which doesn't count against API limits.
        def work():
            on_disk, branch_on_disk = _on_disk(scanned, local_path, follow == FOLLOW_RELEASES)
            rels = sources.newest_releases(ref, host, PAGE_RELEASES, prereleases)
            default, branches, branch_error = _fetch_branches(ref)
            yours = on_disk[0] if on_disk and on_disk[0] else installed
            head = next((b.sha for b in branches if b.name == (branch or default)), "")
            comparison = _compare(ref, host, yours, head) if follow == FOLLOW_BRANCH else None
            scripts = updater.install_scripts(local_path) if scanned and (Path(local_path) / ".git").exists() else []
            return rels, default, branches, branch_error, on_disk, branch_on_disk, yours, head, comparison, scripts

        def done(result, error):
            if not self._config.find(repo_id):
                return  # removed while loading
            if error:
                self._details[repo_id] = Details(state="error", error=self._error_text(error))
            else:
                rels, default, branches, branch_error, on_disk, branch_on_disk, yours, head, comparison, scripts = result
                self._details[repo_id] = Details(
                    state="ready", releases=rels, more_releases=len(rels) == PAGE_RELEASES, default_branch=default,
                    branches=branches, branch_error=branch_error,
                    comparison=comparison, commits_base=yours, commits_head=head,
                    local_missing=bool(on_disk) and not on_disk[1], branch_on_disk=branch_on_disk,
                    install_scripts=scripts,
                )
                if repo := self._config.find(repo_id):
                    # A scanned repo's version is whatever's on disk now (e.g. after a `git pull` outside the app).
                    from_disk = bool(on_disk and on_disk[0] and on_disk[0] != repo.installed)
                    if from_disk:
                        repo.installed = on_disk[0]
                        self._version_changed(repo)
                    baseline_set = _set_baseline(repo, self._details[repo_id])
                    tag_matched = _match_tag(repo, self._details[repo_id])
                    if _fit_files(repo, self._details[repo_id]) or baseline_set or tag_matched or from_disk:
                        self._changed()
            self.detailsChanged.emit(repo_id)

        self._run(work, done)

    def _read_disk_version(self, repo_id):
        """Your version for a scanned repo, read from disk again (no request): after switching what it follows, since
        a clone's version is then a commit or a release tag."""
        repo = self._config.find(repo_id)
        scanned, local_path, releases = True, repo.local_path, repo.follow == FOLLOW_RELEASES

        def done(result, error):
            repo, d = self._config.find(repo_id), self._details.get(repo_id)
            if error or not repo or not result[0] or not result[0][0]:
                return
            repo.installed = result[0][0]
            if d:
                _match_tag(repo, d)
            self._version_changed(repo)
            self._changed(repo_id)
            if repo.follow == FOLLOW_BRANCH:
                self._refresh_whats_new(repo_id)

        self._run(lambda: _on_disk(scanned, local_path, releases), done)

    @Slot(str)
    def loadOlderReleases(self, repo_id):
        """Show Older Releases: a full page of them, instead of the newest few the page loaded with."""
        repo, d = self._config.find(repo_id), self._details.get(repo_id)
        if not repo or not d or d.state != "ready" or not d.more_releases or d.loading_more:
            return
        d.loading_more, d.more_error = True, ""
        self.detailsChanged.emit(repo_id)
        ref, host = RepoRef.from_id(repo_id), repo.host

        def done(result, error):
            if self._details.get(repo_id) is not d:
                return  # refreshed or removed meanwhile
            d.loading_more = False
            if error:
                d.more_error = self._error_text(error)
            else:
                d.releases, d.more_releases = result, False
                # Your version may be one of the older releases.
                if (repo := self._config.find(repo_id)) and _match_tag(repo, d):
                    self._changed(repo_id)
            self.detailsChanged.emit(repo_id)

        self._run(lambda: sources.releases(ref, host), done)

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
                "notes": _without_images(rel.notes),
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
        follow_disk = d.branch_on_disk if (repo and _is_clone(repo) and repo.follow == FOLLOW_BRANCH and d.branch_on_disk
                                           and d.branch_on_disk != current_branch) else ""
        return {
            "newCommits": [{"sha": x.sha[:7], "title": x.title} for x in c.commits[:5]] if behind else [],
            "newCommitsTotal": c.total if behind else 0,
            "branchOnDisk": d.branch_on_disk,
            "versionFromDisk": bool(repo) and repo.source == config.SOURCE_SCANNED,
            "localMissing": d.local_missing,
            **{"versionText": "", "installed": "", "status": "", "updateAvailable": False, "newestText": "",
               "statusKind": "", "headline": ""}, **version,
            "state": d.state,
            "error": d.error,
            "description": repo.description if repo else "",
            "hasReleases": bool(d.releases),
            "moreReleases": d.more_releases,
            "loadingMore": d.loading_more,
            "moreError": d.more_error,
            "releases": releases,
            "latestTag": latest["tag"] if latest else "",
            "fileChoices": choices,
            # Nothing in the newest release runs on this computer: tracked by version only.
            "versionOnly": latest is not None and not choices,
            # A file was picked, but the newest release doesn't have it (renamed or dropped by the project).
            "yourFileMissing": bool(pattern) and latest is not None and not latest["hasSelected"],
            "branchError": d.branch_error,
            # Update can't pull a branch the clone isn't on (it would refuse): offered is following that one instead.
            "canUpdate": bool(repo) and _can_update(repo) and not d.local_missing and not follow_disk,
            "followDiskBranch": follow_disk,
            "isClone": bool(repo) and _is_clone(repo),
            # Install clones the project into clonesFolder.
            "installClones": bool(repo) and _can_clone(repo),
            "clonesFolder": updater.shown(updater.clones_dir()),
            "updateNeedsPassword": bool(repo) and _needs_password(repo),
            "isPackage": bool(repo) and _is_package(repo),
            # The package manager that installs it ("dnf", "apt", …).
            "packageTool": packages.tool_for(repo.kind) if repo and _is_package(repo) else "",
            "updatePhase": self._phases.get(repo_id, ""),
            "isProgram": bool(repo) and _is_program(repo),
            "isDownload": bool(repo) and (_is_appimage(repo) or _is_program(repo) or _is_package(repo)
                                          or _is_flatpak(repo)),
            "isFlatpak": bool(repo) and _is_flatpak(repo),
            "programChoices": self._program_choices.get(repo_id, []),
            "program": repo.program if repo else "",
            # The command an installed program is run as, and where its link is.
            "command": Path(repo.local_path).name if repo and _is_program(repo) and repo.local_path else "",
            "binFolder": updater.shown(updater.bin_dir()),
            "programsFolder": updater.shown(updater.programs_dir()),
            "progress": self._progress.get(repo_id, -1),
            # Where Install puts an AppImage you don't have yet.
            "installFolder": updater.shown(updater.apps_dir()),
            "updating": repo_id in self._updating,
            "updateNoteKind": self._update_notes.get(repo_id, ("", ""))[0],
            "updateNote": self._update_notes.get(repo_id, ("", ""))[1],
            "installScripts": d.install_scripts,
            # Whether you've started an install script from here: "" never, "current" at the version you have now,
            # "older" before the clone last changed (its update may need installing).
            "scriptRun": "" if not repo or not repo.script_run_at
                         else "current" if repo.script_run_at == repo.installed else "older",
            "scriptRunAt": _version_text(repo.script_run_at) if repo else "",
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
        """Your version as text, the newest, and how they compare: a status line, plus a kind (STATUS_*) and a short
        headline for the status box on the repo page."""
        installed = repo.installed
        if repo.follow == FOLLOW_BRANCH:
            branch = repo.branch or d.default_branch
            newest = _head(repo, d)
            if not newest:
                return {}
            yours_text, newest_text = f"commit {installed[:7]}", f"commit {newest[:7]}"
            if installed and installed not in (NOT_INSTALLED, newest):
                return {"versionText": yours_text, "installed": installed, "newestText": newest_text,
                        **self._branch_status(repo, d, branch, yours_text)}
            newer_text, update_headline = f"Newer commits on {branch}", f"New commits on {branch}"
        else:
            if not shown:
                return {}
            newest = shown[0].tag
            # A clone that isn't at a release tag: its commit.
            newest_text, yours_text = newest, _version_text(installed)
            newer_text, update_headline = f"Newer version available: {newest}", "Update available"
        if installed == NOT_INSTALLED:
            text, status, kind, headline = "Not installed", f"The newest is {newest_text}.", STATUS_NOT_INSTALLED, \
                "Not installed"
        elif installed == newest:
            text, status, kind, headline = yours_text, "Up to date", STATUS_CURRENT, "Up to date"
        elif installed:
            text, status, kind, headline = yours_text, f"{newer_text} (you have {yours_text})", STATUS_UPDATE, \
                update_headline
        else:
            text, status, kind, headline = "", "", "", ""
        return {"versionText": text, "installed": installed, "status": status, "updateAvailable": kind == STATUS_UPDATE,
                "newestText": newest_text, "statusKind": kind, "headline": headline}

    def _branch_status(self, repo: TrackedRepo, d: Details, branch: str, yours_text: str) -> dict:
        """Status when your commit isn't the branch's newest: depends on how the two relate."""
        c = self._current_comparison(repo, d)
        if d.comparing:
            return {"status": "Checking\u2026", "updateAvailable": False, "statusKind": STATUS_CHECKING,
                    "headline": "Checking\u2026"}
        if c is None:
            site = RepoRef.from_id(repo.id).domain
            return {"status": f"Couldn\u2019t compare your version ({yours_text}) with {branch}. {site} may not have "
                              "that commit (for example, one that was never pushed), or couldn\u2019t be reached; "
                              "Refresh tries again.",
                    "updateAvailable": False, "statusKind": STATUS_PROBLEM, "headline": "Couldn\u2019t compare"}
        # A clone that's on another branch than the one followed (Follow <it> is offered on the page).
        disk = d.branch_on_disk if d.branch_on_disk and d.branch_on_disk != branch else ""
        if c.relation == sources.BEHIND:
            status = f"Newer commits on {branch} (you have {yours_text})" if not disk else \
                f"{branch} has commits your clone doesn\u2019t, but your clone is on {disk}, so Update can\u2019t " \
                f"bring them in. Follow {disk} instead, or switch the clone to {branch} (git switch {branch})."
            return {"status": status, "updateAvailable": True, "statusKind": STATUS_UPDATE,
                    "headline": f"New commits on {branch}"}
        if c.relation == sources.AHEAD:
            if disk:
                return {"status": f"Everything on {branch} is already in your clone, which is on {disk} ({branch} "
                                  f"was probably merged into it). Follow {disk} to hear about its new commits.",
                        "updateAvailable": False, "statusKind": STATUS_AHEAD, "headline": f"Nothing new on {branch}"}
            return {"status": f"Your version has everything on {branch}, plus commits that aren\u2019t on it.",
                    "updateAvailable": False, "statusKind": STATUS_AHEAD, "headline": f"Ahead of {branch}"}
        if c.relation == sources.SAME:
            return {"status": "Up to date", "updateAvailable": False, "statusKind": STATUS_CURRENT,
                    "headline": "Up to date"}
        where = f"your clone is on {d.branch_on_disk}" if d.branch_on_disk and d.branch_on_disk != branch \
            else f"your version ({yours_text}) isn\u2019t part of it"
        return {"status": f"Not comparable with {branch}: {where}.", "updateAvailable": False,
                "statusKind": STATUS_PROBLEM, "headline": "Not comparable"}

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
            self._version_changed(repo)
            self._changed(repo_id)
            if repo.follow == FOLLOW_BRANCH:
                self._refresh_whats_new(repo_id)  # compare the new version with the branch

    @Slot(str, str)
    def setFollow(self, repo_id, follow):
        repo = self._config.find(repo_id)
        if not repo or follow not in (FOLLOW_RELEASES, FOLLOW_BRANCH) or follow == repo.follow:
            return
        clone = _is_clone(repo)
        repo.follow = follow
        # The last check's result and update message were about what it followed before.
        self._update_notes.pop(repo_id, None)
        if self._checks.results.pop(repo_id, None):
            self._save_checks()
        if follow == FOLLOW_BRANCH or clone:
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
        if repo.source == config.SOURCE_SCANNED:
            self._read_disk_version(repo_id)  # a commit for a branch, a release tag for releases

    @Slot(str, str)
    def setBranch(self, repo_id, branch):
        """Choose which branch to compare against. Your version stays as it is: for a scanned repo it's re-read from
        disk, and the list of new commits is refreshed for the new branch."""
        repo = self._config.find(repo_id)
        if not repo or branch == repo.branch:
            return
        repo.branch = branch
        self._update_notes.pop(repo_id, None)
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
                self._version_changed(repo)
                self._changed(repo_id)
            else:
                self.detailsChanged.emit(repo_id)

        def start():
            d = self._details.get(repo_id)
            if d and d.compare_request == request:  # not if another branch was clicked meanwhile
                self._run(work, done)

        # A short wait, so clicking quickly through branches asks the site about the last one only.
        if self.compare_delay_ms:
            QTimer.singleShot(self.compare_delay_ms, start)
        else:
            start()

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
