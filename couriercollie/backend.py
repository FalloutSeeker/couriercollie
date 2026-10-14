"""The bridge between the window (QML) and the rest of the app.

The window calls the slots here and shows the properties. Anything that touches the network runs on a worker thread,
so the window never freezes; results are handed back to the main thread through `_deliver`.
"""

import copy
import dataclasses
import hashlib
import os
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PySide6.QtCore import (Property, QEventLoop, QFileSystemWatcher, QObject, QProcess, QTimer, Signal, Slot,
                            qVersion)
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from . import (applying, assets, checker, config, feedback, flatpaks, github_login, icons, integration, packages, scan,
               sources, updater)
from .account import Account
from .updating import (Updating, _can_clone, _can_update, _head, _is_appimage, _is_clone, _is_flatpak,
                       _is_package, _is_program, _needs_password, _new_copy, _newest_version)
from .config import FOLLOW_BRANCH, FOLLOW_RELEASES, NOT_INSTALLED, Config, ConfigError, TrackedRepo
from .sources import RepoRef, SourceError

# The way icons are looked up now (icons.py); saved icons from an older way are looked up again.
ICON_LOOKUP = 2
# Monogram colours (a repo without a picture shows its first letter on one): each carries a white letter on light and
# dark themes alike, and a repo always gets the same one.
MONOGRAM_COLORS = ("#3b78b8", "#2b8a68", "#b9532b", "#7d52b5", "#b53d71", "#4a7f2a", "#8f6e00", "#525fb3")
FILTERS = ("all", "github", "gitlab")
# How your version compares with the newest, for the repo page's status box (colour and icon).
STATUS_UPDATE, STATUS_CURRENT, STATUS_NOT_INSTALLED = "update", "current", "notInstalled"
STATUS_AHEAD, STATUS_CHECKING, STATUS_PROBLEM = "ahead", "checking", "problem"
STATUS_MANAGED = "managed"  # not yours to update: the package manager (or Flatpak) installed it
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
    builds: list[applying.Build] = field(default_factory=list)  # a scanned clone's build folders (CMake, Meson)
    # The project is also installed from a repository the package manager or Flatpak updates (_managed_elsewhere):
    # the page's note, and that installed version.
    managed_elsewhere: str = ""
    managed_version: str = ""


def _monogram(name: str, repo_id: str) -> dict:
    """A picture-less repo's icon: its first letter or digit, on a colour picked from its address."""
    letter = next((c for c in name if c.isalnum()), "?").upper()
    color = MONOGRAM_COLORS[int(hashlib.sha1(repo_id.lower().encode()).hexdigest(), 16) % len(MONOGRAM_COLORS)]
    return {"monogram": letter, "monogramColor": color}


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
    if d.state != "ready" or not d.releases:
        return False
    newest = next((r for r in d.releases if not r.prerelease), d.releases[0])
    builds = [info for a in newest.assets if (info := assets.classify(a.name, a.url)).build]
    other_systems = bool(builds) and not any(info.suits for info in builds)
    changed, repo.other_systems = repo.other_systems != other_systems, other_systems
    if repo.follow != FOLLOW_RELEASES or _is_clone(repo):
        return changed  # a clone following releases follows the source at each release's tag, not a file
    before = (repo.asset_pattern, repo.kind)
    if repo.asset_pattern:
        picked = [a for r in d.releases for a in r.assets if assets.matches(repo.asset_pattern, a.name)]
        if picked and not any(assets.classify(a.name, a.url).suits for a in picked):
            repo.asset_pattern, repo.kind = "", ""
    nothing_fits = not any(assets.classify(a.name, a.url).suits for a in newest.assets)
    if nothing_fits and not repo.asset_pattern:
        repo.kind = assets.KIND_VERSIONS
    elif repo.kind == assets.KIND_VERSIONS:
        repo.kind = ""  # a later release added something for this computer
    return changed or (repo.asset_pattern, repo.kind) != before


# Packages for another distro's package manager, by the distros that use them.
_PACKAGE_SYSTEMS = {"Debian package": "Debian/Ubuntu", "RPM": "Fedora/openSUSE", "Arch package": "Arch Linux"}


def _and(items: list[str]) -> str:
    return (", ".join(items[:-1]) + " and " + items[-1]) if len(items) > 1 else "".join(items)


def _other_systems_note(d: Details) -> str:
    """For a project built only for other systems (TrackedRepo.other_systems): what its builds are for, said once on
    its page: "…builds are for Android", or "…for Windows and macOS"."""
    if d.state != "ready" or not d.releases:
        return ""
    newest = next((r for r in d.releases if not r.prerelease), d.releases[0])
    systems: list[str] = []
    processors: list[str] = []
    for a in newest.assets:
        info = assets.classify(a.name, a.url)
        if not info.build or info.suits:
            continue
        # The note says why: "for Android", "for riscv64 processors", "Debian package: not supported on your distro".
        if info.note.endswith(" processors"):
            what, into = info.note.removeprefix("for ").removesuffix(" processors"), processors
        else:
            what = info.note.removeprefix("for ") if info.note.startswith("for ") else info.note.split(":", 1)[0]
            what, into = _PACKAGE_SYSTEMS.get(what, what), systems
        if what and what not in into:
            into.append(what)
    if processors:
        systems.append(_and(processors) + " processors")
    listed = _and(systems)
    builds = f"this project\u2019s builds are for {listed}" if listed else "none of this project\u2019s builds run here"
    return f"Not supported on this computer: {builds}. Only its versions are tracked."


def _match_tag(repo: TrackedRepo, d: Details) -> bool:
    """A version found on disk ("1.18.2", from an RPM or AppImage) as the release's tag ("v1.18.2")."""
    if repo.follow != FOLLOW_RELEASES or not repo.installed or repo.installed == NOT_INSTALLED or d.state != "ready":
        return False
    tags = [r.tag for r in d.releases]
    if repo.installed in tags:
        return False
    tag = next((t for t in tags if assets.version_of(repo.installed) and assets.same_version(t, repo.installed)), None)
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


def _compare(ref: RepoRef, host: str, yours: str, head: str, clone: str = "") -> sources.Comparison | None:
    """How your version relates to a branch's newest commit. None if there's nothing to compare, or it couldn't be.
    `clone`: where yours is on disk: asked first (updater.compare_here), then the site."""
    if not head or not yours or yours == NOT_INSTALLED:
        return None
    if yours == head:
        return sources.Comparison(sources.SAME)  # no need to ask
    if found := updater.compare_here(clone, yours, head):
        return found
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


def _scan_note(f: scan.Found, problem: str, similar: TrackedRepo | None) -> str:
    """The line under a scan find: why it can't be added, what it seems to duplicate, or what to expect of it."""
    if similar:
        return (f"Looks like \u201c{similar.name}\u201d, which you track from {similar.url}. Tick it to link the two; "
                "it won\u2019t be added twice.")
    if problem:
        return problem
    notes = []
    if f.other_paths:
        notes.append("Also in 1 other place." if len(f.other_paths) == 1 else
                     f"Also in {len(f.other_paths)} other places.")
    if f.needs_password:
        # Only a clone that belongs to the system is updated as root (updater._as_root); someone else's isn't touched.
        notes.append("Its folder belongs to the system, so updating it will ask for your password."
                     if f.kind == assets.KIND_GIT and updater.needs_password(f.path) else
                     "Its folder belongs to another user, so it can be tracked but not updated from here.")
    return " ".join(notes)


def _homepage_of(ref: RepoRef, host: str) -> str:
    """The project's own website, as it gives it on GitHub; "-" if it gives none (GitLab has no such field), "" if
    the site couldn't be asked (asked again next time). One request, once per repo (TrackedRepo.homepage)."""
    if host != "github":
        return "-"
    try:
        return sources.project_info(ref).homepage or "-"
    except SourceError:
        return ""


def _managed_elsewhere(repo_ids: list[str], website: str = "") -> tuple[str, str, str]:
    """If the project is installed in a way something else keeps up to date (a package from a repository you have
    enabled, or a Flatpak from a Flatpak repository): (a note for its page, what keeps it updated, the installed
    version). couriercollie then never updates it (_can_update): two updaters would fight over the same files.
    `website`: the project's own (TrackedRepo.homepage), which a package may give as its homepage."""
    if found := packages.managed_by_system(repo_ids, website=website):
        tool, _name, version = found
        return "Your package manager keeps this up to date.", tool, version
    if found := flatpaks.managed_by_flatpak(repo_ids):
        _app_id, version = found
        return "Flatpak keeps this up to date.", "Flatpak", version
    return "", "", ""


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
    # A clone's page should ask what runs after Update downloads: (repo id, why: "update" before the first Update,
    # "installed" once it's cloned, "changed" when an update changed what was approved).
    askStep = Signal(str, str)
    detailsChanged = Signal(str)  # repo id
    settingsChanged = Signal()
    scanChanged = Signal()
    checksChanged = Signal()
    activateRequested = Signal()  # bring the window to the front (a second launch, or a notification was clicked)
    saveErrorChanged = Signal()
    configErrorChanged = Signal()
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
        # Whether the desktop shows tray icons (set by the app, tray.py): "keep running in the tray" needs one.
        self.tray_available = False
        self._icons_pending: set[str] = set()
        self._path = config_path
        self._config_error = ""
        self._save_error = ""
        # The file as last read or written here, and the settings it held: what a change by hand is told from, and
        # merged against (_sync_from_disk).
        self._saved_text = self._settings_text()
        try:
            self._config = config.load(config_path)
        except ConfigError as e:
            # Start empty, and don't save, so the broken file isn't overwritten.
            self._config = Config()
            self._config_error = str(e)
        self._synced = copy.deepcopy(self._config)
        if self._config.settings.icon_lookup < ICON_LOOKUP and not self._config_error:
            # Looked up an older way (which guessed): look them up again.
            for r in self._config.repos:
                r.icon = ""
            self._config.settings.icon_lookup = ICON_LOOKUP
        self._filter = "all"
        self._adding = False
        self._details: dict[str, Details] = {}
        self._scan_state = "idle"  # "idle", "scanning" or "done"
        self._scan_started: dict[str, int] = {}  # updates finished when the scan started (Updating._finished)
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
        # The settings file edited by hand while the app is open: read again, rather than overwritten by the next save.
        # A moment after it changes, as an editor may write it in more than one go. Both the file (written in place)
        # and its folder (replaced, as most editors and our own saves do, which ends the file's watch) are watched.
        settings_file = config_path or config.default_path()
        settings_file.parent.mkdir(parents=True, exist_ok=True)
        self._watcher.addPath(str(settings_file.parent))
        self._settings_timer = QTimer(self, singleShot=True, interval=300)
        self._settings_timer.timeout.connect(self._reload_settings)
        self._watcher.directoryChanged.connect(lambda folder: self._settings_timer.start()
                                               if Path(folder) == settings_file.parent else None)
        self._watcher.fileChanged.connect(lambda file: self._settings_timer.start())
        self._watch_settings_file()
        # Run from a clone: the commit it started at (an update pulling it doesn't change what runs).
        clone = integration.PROJECT
        self._started_at = (updater.git_out(str(clone), "rev-parse", "HEAD")
                            if self._desktop and not integration.INSTALLED and (clone / ".git").exists() else "")
        self._started = False
        if not self._config_error:
            self._start()

    def _start(self):
        """Once the settings are read (at start, or once a broken settings file is fixed)."""
        self._started = True
        if self._desktop:
            # What an update cut short left behind (the app killed, the computer turned off), off the main thread.
            self._run(updater.clean_leftovers, lambda _done, _error: None)
            self._track_myself()
            integration.set_background_checks(self._config.settings.auto_check)
            integration.set_start_at_login(self._config.settings.start_at_login)  # rewritten if couriercollie moved
            self._update_badge()

    # couriercollie's own project, and its release files: the one for each package manager (devtools/build_package.sh
    # names them), so each finds only its own.
    MYSELF = "github.com/FalloutSeeker/couriercollie"
    MY_FILES = {"dnf": (assets.KIND_RPM, "couriercollie-*.fc*.noarch.rpm"),
                "zypper": (assets.KIND_RPM, "couriercollie-*-1.noarch.rpm"),
                "apt": (assets.KIND_DEB, "couriercollie_*_all.deb"),
                "pacman": (assets.KIND_ARCH, "couriercollie-*-1-any.pkg.tar.zst")}

    def _track_myself(self):
        """On the first start, couriercollie adds itself to the list, so you hear about its own updates; once only,
        so if you stop tracking it, it stays gone. Followed as it's installed: its package (Update installs the new
        one with your package manager), or, run from a git clone, the clone's branch (Update pulls it)."""
        s = self._config.settings
        if s.tracked_itself:
            return
        s.tracked_itself = True
        if not self._config.find_any(self.MYSELF):
            from . import __version__

            repo = TrackedRepo(id=self.MYSELF, name="couriercollie", url=f"https://{self.MYSELF}", host="github",
                               installed=__version__, icon=f"theme:{integration.ICON}", homepage="-",
                               added_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
            clone = integration.PROJECT
            if not integration.INSTALLED and (clone / ".git").exists():
                repo.follow, repo.branch, repo.kind = FOLLOW_BRANCH, "main", assets.KIND_GIT
                repo.source, repo.local_path = config.SOURCE_SCANNED, str(clone)
                repo.installed = updater.git_out(str(clone), "rev-parse", "HEAD") or __version__
            else:
                tool = next((t for t in self.MY_FILES if assets.has(t)), "")
                kind, pattern = self.MY_FILES.get(tool, ("", ""))
                if kind and packages.installed_version(kind, "couriercollie")[1]:
                    repo.kind, repo.asset_pattern = kind, pattern
                    repo.source, repo.local_path = config.SOURCE_SCANNED, packages.place(kind, "couriercollie")
            self._config.repos.insert(0, repo)
        self._save()

    def finish_updates(self):
        """Quitting while something updates (Quit in the tray, or the window closed): it's left to finish first, out of
        sight, so what it did is recorded. Cutting a package manager or a clone short would leave it half done, and the
        work goes on anyway; without this, the app would forget it (an install would still say "Not installed")."""
        if not self._updating:
            return
        loop = QEventLoop()

        def over():
            if not self._updating:
                loop.quit()
        self.reposChanged.connect(over)
        loop.exec()
        self.reposChanged.disconnect(over)

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
        # Changed by hand since it was last read or written here, and not read again yet: merged first, so the
        # edit isn't overwritten.
        if (text := self._settings_text()) is not None and text != self._saved_text and not self._sync_from_disk(text):
            return
        try:
            self._saved_text = config.save(self._config, self._path)
            self._synced = copy.deepcopy(self._config)
            error = ""
        except OSError as e:
            path = self._path or config.default_path()
            error = (f"Couldn\u2019t save to {path.parent} ({e.strerror or e}). Changes are kept while couriercollie "
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
        """Our own errors are written for you, so they're shown as they are; anything else is a surprise, and says
        so."""
        ours = (SourceError, ValueError, updater.UpdateError, github_login.LoginError)
        return str(error) if isinstance(error, ours) else f"Something went wrong: {error}"

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
            "branch": r.branch,
            "assetPattern": r.asset_pattern,
            "prereleases": r.prereleases,
            "icon": self._icon_source(r),
            **_monogram(r.name, r.id),
            "followText": follow_text,
            "scanned": r.source == config.SOURCE_SCANNED,
            "shownPath": updater.shown(r.local_path),  # as shown: ~ for your home folder
            # Not for a copy of yours added by hand: one click in the list shouldn't quietly install a second copy.
            "canUpdate": _can_update(r) and not _new_copy(r) and not self._part_of(r),
            "updateNeedsPassword": _needs_password(r),
            "updating": r.id in self._updating,
            "category": r.category,
            **self._check_dict(r.id, r),
        }

    @staticmethod
    def _icon_source(r: TrackedRepo) -> str:
        """The repo's picture for the window, or "" for none (also if a found picture has since been deleted): the
        window then shows its monogram."""
        if r.icon.startswith("theme:"):
            return r.icon.removeprefix("theme:")
        if r.icon.startswith("file:") and Path(r.icon.removeprefix("file:")).is_file():
            return "file://" + r.icon.removeprefix("file:")
        return ""

    # -- checking for updates ----------------------------------------------------------------------------------------

    def _check_dict(self, repo_id: str, repo: TrackedRepo | None = None) -> dict:
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
        if repo and repo.other_systems:
            text = text.replace("Not installed", "Version not set", 1)  # it can't be installed here, only noted
        return {
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
        limited = [v for v in results.values()
                   if v.status == checker.RATE_LIMITED or (v.not_rechecked and v.retry_after)]
        reset = next((v.retry_after for v in limited if v.retry_after), "")
        s = self._config.settings
        return {
            "updates": sum(1 for v in results.values() if v.status == checker.UPDATE),
            # Not checked this time: a failure, or no answer (also when the last result was kept).
            "failed": sum(1 for v in results.values() if v.status in (checker.FAILED, checker.UNREACHABLE)
                          or (v.not_rechecked and not v.retry_after)),
            "checked": len(results),
            # Removed outside the app since (checker.GONE).
            "gone": sum(1 for v in results.values() if v.text == checker.GONE),
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
        at_start = dict(previous.results)
        self._checking, self._check_error = True, ""
        self.checksChanged.emit()

        def done(result, error):
            self._checking = False
            if error:
                self._check_error = self._error_text(error)
            else:
                self._checks, fresh = result
                # While it ran, a repo may have been updated, or its page found a newer result: the check's result is
                # for the version it had then. The page's is kept; an update's is redone for the version it has now
                # (no request), and isn't announced.
                yours = {r.id: r.installed for r in repos}
                for r in self._config.repos:
                    new, now = self._checks.results.get(r.id), previous.results.get(r.id)
                    if new and r.id in yours and r.installed != yours[r.id] and new.newest:
                        self._checks.results[r.id] = checker.recheck_against(
                            new, r.installed, by_branch=r.follow == FOLLOW_BRANCH, branch=r.branch)
                    elif now is not at_start.get(r.id) and now is not None:
                        self._checks.results[r.id] = now
                    else:
                        continue
                    fresh = [i for i in fresh if i != r.id]
                self._save_checks()
                # What the package manager or Flatpak installed, as the check found (checker.find_managed).
                managed = {r.id: r.managed_by for r in repos}
                changed = [r for r in self._config.repos if r.id in managed and r.managed_by != managed[r.id]]
                for r in changed:
                    r.managed_by = managed[r.id]
                    self._details.pop(r.id, None)
                if changed:
                    self._save()
                self._announce(fresh)
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
        if not old or not old.newest or \
                old.status not in (checker.UPDATE, checker.UP_TO_DATE, checker.NOT_INSTALLED_YET):
            return
        new = checker.recheck_against(old, repo.installed, by_branch=repo.follow == FOLLOW_BRANCH,
                                      branch=repo.branch)
        if new == old:
            return
        self._checks.results[repo.id] = new
        self._save_checks()

    def _check_from_page(self, repo: TrackedRepo):
        """A repo's page has just asked the site. If it learned something the last check didn't (a newer release, new
        commits), the list says so too, without another request; and since you've seen it, it isn't announced in a
        notification later."""
        d = self._details.get(repo.id)
        if not d or d.state != "ready":
            return
        if repo.follow == FOLLOW_BRANCH:
            head, c = _head(repo, d), self._current_comparison(repo, d)
            if not head or (c is None and repo.installed not in ("", NOT_INSTALLED, head)):
                return  # not compared (yet): nothing better to say than the last check
            new = checker.branch_result(repo.branch or d.default_branch, head, repo.installed, c, d.branch_on_disk,
                                        repo.managed_by)
        else:
            shown = [r for r in d.releases if repo.prereleases or not r.prerelease]
            if not shown:
                return
            new = checker.releases_result(shown, repo.installed, repo.managed_by,
                                          repo.source == config.SOURCE_SCANNED, repo.asset_pattern)
        if d.local_missing and not repo.managed_by:
            new = checker.Result(checker.NOT_INSTALLED_YET, checker.GONE, new.newest)  # removed outside the app
        old = self._checks.results.get(repo.id)
        if old and (old.status, old.text, old.newest) == (new.status, new.text, new.newest) and not old.not_rechecked:
            return
        new.checked_at = checker.stamp()
        self._checks.results[repo.id] = new
        if new.status == checker.UPDATE:
            self._checks.notified[repo.id] = new.newest
        self._save_checks()
        self.reposChanged.emit()

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

    def _settings_text(self) -> str | None:
        """The settings file as it is now, or None if there's none (or it can't be read)."""
        try:
            return (self._path or config.default_path()).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

    def _watch_settings_file(self):
        """Watch the settings file itself, if it's there and not watched yet (a file replaced is watched no more)."""
        path = str(self._path or config.default_path())
        if path not in self._watcher.files() and os.path.exists(path):
            self._watcher.addPath(path)

    def _sync_from_disk(self, text: str) -> bool:
        """The settings file holds `text`, written by something else (edited by hand): merged with the app's own
        changes since it last read or wrote it (config.merge), so neither is lost. If it's broken, nothing is saved
        until it's fixed (the window says so); then what the app did meanwhile is merged in. False if it's broken."""
        self._saved_text = text
        try:
            theirs = config.loads(text, self._path)
            error = ""
        except ConfigError as e:
            theirs, error = None, str(e)
        if error != self._config_error:
            self._config_error = error
            self.configErrorChanged.emit()
        if theirs is None:
            return False
        before = self._config.settings
        self._config = config.merge(self._synced, self._config, theirs)
        self._synced = theirs
        s = self._config.settings
        if not self._started:
            self._start()  # broken since the app started: what it does at start, now
        elif self._desktop:
            # Turned on or off by hand: the timer and the login entry follow.
            if s.auto_check != before.auto_check:
                integration.set_background_checks(s.auto_check)
            if s.start_at_login != before.start_at_login:
                integration.set_start_at_login(s.start_at_login)
        self.settingsChanged.emit()
        self.reposChanged.emit()
        self.checksChanged.emit()  # (the next check's time)
        for r in self._config.repos:
            self.detailsChanged.emit(r.id)
        self._update_badge()
        return True

    def _reload_settings(self):
        """The settings file changed: if not by the app (edited by hand), merged with the app's own settings, and
        saved if the app had changes of its own that the file doesn't have yet."""
        self._watch_settings_file()
        text = self._settings_text()
        if text is None or text == self._saved_text:
            return  # our own save, or the file is gone (being replaced: it's read once it's back)
        if self._sync_from_disk(text) and config.dumps(self._config) != text:
            self._save()

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
        # In front: a window of ours is shown and has the focus. (Qt's application state isn't enough: with the window
        # closed to the tray, it can stay "active" with no window at all, and nothing would ever be announced.)
        window = QGuiApplication.focusWindow()
        if window is not None and window.isVisible() and window.isActive():
            return
        names = [r.name for r in self._config.repos if r.id in fresh]
        command = integration.notify_command(*integration.updates_message(names))
        if not command:
            return
        process = QProcess(self)
        self._notifications.append(process)

        def finished(*_):
            if process not in self._notifications:
                return  # (a process that couldn't start reports that, and may report finishing too)
            if bytes(process.readAllStandardOutput()).decode().strip() == "default":
                self.activateRequested.emit()
            self._notifications.remove(process)
            process.deleteLater()

        process.finished.connect(finished)
        # One that can't start (notify-send gone) never finishes: without this it would be kept forever.
        process.errorOccurred.connect(
            lambda error: finished() if error == QProcess.ProcessError.FailedToStart else None)
        process.start(command[0], command[1:])

    def _update_badge(self):
        """The number of repos with updates, on the app's taskbar icon. Plasma removes it when the app closes."""
        if not self._desktop:
            return
        from PySide6.QtDBus import QDBusConnection, QDBusMessage

        count = sum(1 for r in self._config.repos
                    if (result := self._checks.results.get(r.id)) and result.status == checker.UPDATE)
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
        local_path = repo.local_path

        def done(result, error):
            self._icons_pending.discard(repo_id)
            if error or not (repo := self._config.find(repo_id)):
                return  # unreachable (icons.Unreachable) or removed meanwhile
            repo.icon = result
            self._changed()

        self._run(lambda: icons.resolve(repo_id, local_path, icon_url), done)

    # -- the list ---------------------------------------------------------------------------------------------------

    def _sections(self) -> list[tuple[str, list[TrackedRepo]]]:
        """(category, repos shown in it) in the order they're listed: Uncategorized first, then your categories. Repos
        keep their order in the settings file, which dragging changes."""
        shown = [r for r in self._config.repos if self._filter == "all" or r.host == self._filter]
        return [(c, [r for r in shown if r.category == c]) for c in ["", *self._config.categories]]

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

    @Property(str, notify=configErrorChanged)
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
        """The settings, as the welcome screen and Settings page show them (names as in QML)."""
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
            "startAtLogin": s.start_at_login,
            "keepInTray": s.keep_in_tray,
            "trayAvailable": self.tray_available,
            "areDefault": self._defaults() == s,
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
                 "scanning": "scanning", "startAtLogin": "start_at_login", "keepInTray": "keep_in_tray"}
        auto_before, login_before = s.auto_check, s.start_at_login
        for key, attr in bools.items():
            if isinstance(changes.get(key), bool):
                setattr(s, attr, changes[key])
        if self._desktop and s.auto_check != auto_before:
            integration.set_background_checks(s.auto_check)
        if self._desktop and s.start_at_login != login_before:
            integration.set_start_at_login(s.start_at_login)
        if (hours := _whole_number(changes.get("checkIntervalHours"))) in config.CHECK_INTERVALS_HOURS:
            s.check_interval_hours = hours
        self._save()
        self.settingsChanged.emit()
        self.checksChanged.emit()  # "next check" depends on these

    def _defaults(self) -> config.Settings:
        """The settings as on a fresh start, with the welcome screen's answers (automatic checks on, daily), and what
        isn't a setting kept: the GitHub sign-in, and how icons were looked up."""
        s = self._config.settings
        return config.Settings(first_launch_done=True, auto_check=True, github_login=s.github_login,
                               github_user=s.github_user, icon_lookup=s.icon_lookup)

    @Slot()
    def restoreDefaults(self):
        """Settings back to a fresh start (asked first, in Settings). Tracked repos and categories are kept."""
        before, self._config.settings = self._config.settings, self._defaults()
        s = self._config.settings
        if self._desktop:
            if s.auto_check != before.auto_check:
                integration.set_background_checks(s.auto_check)
            if s.start_at_login != before.start_at_login:
                integration.set_start_at_login(s.start_at_login)
        self._save()
        self.settingsChanged.emit()
        self.checksChanged.emit()

    @Slot(bool, result=str)
    def feedbackUrl(self, include_repos):
        """Send Feedback's new GitHub issue (opened in the browser), with the tracked repos' addresses if asked."""
        repos = [r.url for r in self._config.repos] if include_repos else None
        return feedback.issue_url(repos, qVersion())

    @Slot(str)
    def addScanFolder(self, folder):
        """Add a folder to scan. Takes a path or a file:// link (from the folder picker)."""
        path = urllib.parse.unquote(folder.removeprefix("file://"))
        if not os.path.isabs(os.path.expanduser(path)):  # nothing, or relative to wherever the app was started
            return
        path = updater.shown(path)  # "~/…": stays right if the home folder moves
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
        """Add a project by its address (Add): asked of its site once, which gives everything its page needs, so the
        page opens straight away. If the newest release has just one file for this computer, it's picked. Adding
        isn't installing: your version starts as "Not installed" (_set_baseline)."""
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
            # As the page would: something your package manager (or Flatpak) installed isn't offered for install.
            managed = _managed_elsewhere([info.ref.id, ref.id], info.homepage or "")
            return info, rels, default, branches, branch_error, managed

        def done(result, error):
            self._adding = False
            self.addingChanged.emit()
            if error:
                self.addFailed.emit(self._error_text(error))
                return
            info, rels, default, branches, branch_error, (managed_note, managed_by, managed_version) = result
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
                homepage=info.homepage or "-",
                managed_by=managed_by,
            )
            if rels:
                self._auto_pick(repo, rels)
            else:
                repo.follow, repo.kind = FOLLOW_BRANCH, assets.KIND_GIT
            details = Details(
                state="ready", releases=rels, more_releases=len(rels) == PAGE_RELEASES,
                default_branch=default or info.default_branch, branches=branches, branch_error=branch_error,
                managed_elsewhere=managed_note, managed_version=managed_version,
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

    # A name is for the list: long enough for any project's, short enough to fit a row.
    NAME_MAX = 80

    @Slot(str, str, result=str)
    def renameRepo(self, repo_id, name):
        """Your own name for a repo, shown in the list and on its page. Returns why it can't be, or ""."""
        repo, name = self._config.find(repo_id), " ".join(name.split())  # one line, no stray spaces
        if not repo:
            return "This repo isn\u2019t tracked any more."
        if not name:
            return "Type a name."
        if len(name) > self.NAME_MAX:
            return f"That\u2019s too long: keep it to {self.NAME_MAX} characters."
        if name != repo.name:
            repo.name = name
            self._changed(repo_id)
        return ""

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
        self._scan_started = dict(self._finished)
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
            if tracked and tracked.id.lower() == self.MYSELF.lower():
                # couriercollie itself, on the list since the first start (_track_myself): shown, greyed out, as such.
                self._scan_items.append({"key": key, "name": f.name, "address": f.id, "path": f.path, "kind": f.kind,
                                         **_monogram(f.name, f.id), "status": "default", "similarTo": "",
                                         "note": "Added by default"})
                continue
            if tracked and not c.problem:
                # (Not one updated while the scan ran: it found the version from before.)
                if tracked.id not in self._updating and \
                        self._finished.get(tracked.id, 0) == self._scan_started.get(tracked.id, 0):
                    on_list.append(f)
                continue
            if not tracked and not f.host and not c.problem:
                continue  # tracked when the scan started (so not looked up), removed since: found by the next scan
            similar = None if c.problem else scan.looks_like(self._config, f)
            self._scan_finds[key] = f
            self._scan_items.append({
                "key": key,
                "name": f.name,
                "address": f.id,
                "path": f.path,
                "kind": f.kind,
                **_monogram(f.name, f.id),
                "status": "problem" if c.problem else ("similar" if similar else "new"),
                "similarTo": similar.id if similar else "",
                "note": _scan_note(f, c.problem, similar),
            })
        if on_list:
            result = scan.merge(self._config, on_list)
            self._scan_updated = [r.name for r in result.updated]
            for r in result.updated:
                self._details.pop(r.id, None)  # reload with the version found on disk
            self._changed()
            if result.updated:
                self.checkNow()  # what they say now (found moved, say): cheap, as unchanged release lists cost nothing
        self.scanChanged.emit()

    @Slot("QVariantList")
    def trackFound(self, keys):
        """Track the scan finds the user ticked. A find that looks like a tracked repo is linked to it, not added."""
        keys = {int(k) for k in keys if str(k).isdigit()}
        chosen = []
        for item in self._scan_items:
            if item["key"] not in keys or item["status"] in ("problem", "default"):
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
        self._scan_items = [i for i in self._scan_items
                            if i["key"] not in keys or i["status"] in ("problem", "default")]
        self._changed()
        self.scanChanged.emit()
        # So the list says straight away what's out of date. Cheap: unchanged release lists don't count against the
        # sites' hourly limits (sources.py, ETags).
        self.checkNow()

    # -- the repo page ----------------------------------------------------------------------------------------------

    @Slot(str, bool)
    def loadDetails(self, repo_id, force):
        """Ask the site for what a repo's page shows (`force`: Refresh). Also reads your version from disk for a
        scanned repo, and whether the package manager or Flatpak installed it, since either may have changed since
        the page last loaded."""
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
        finished = self._finished.get(repo_id, 0)
        addresses, homepage, pattern = [repo.id, *repo.aliases], repo.homepage, repo.asset_pattern

        # One API request for the releases, and one for what's new on a branch you're behind on. Branches and the
        # version on disk come from git, which doesn't count against API limits.
        def work():
            here = scan.locate(local_path, pattern) if scanned else local_path  # (replaced by hand, say)
            on_disk, branch_on_disk = _on_disk(scanned, here, follow == FOLLOW_RELEASES)
            rels = sources.newest_releases(ref, host, PAGE_RELEASES, prereleases)
            default, branches, branch_error = _fetch_branches(ref)
            yours = on_disk[0] if on_disk and on_disk[0] else installed
            head = next((b.sha for b in branches if b.name == (branch or default)), "")
            comparison = _compare(ref, host, yours, head, local_path if scanned else "") \
                if follow == FOLLOW_BRANCH else None
            clone = scanned and (Path(local_path) / ".git").exists()
            scripts = updater.install_scripts(local_path) if clone else []
            built = applying.builds(local_path) if clone else []
            website = homepage or _homepage_of(ref, host)  # once
            note, managed_by, managed_version = _managed_elsewhere(addresses, website)
            return here, on_disk, managed_by, website, Details(managed_elsewhere=note, managed_version=managed_version,
                state="ready", releases=rels, more_releases=len(rels) == PAGE_RELEASES, default_branch=default,
                branches=branches, branch_error=branch_error, comparison=comparison, commits_base=yours,
                commits_head=head, local_missing=bool(on_disk) and not on_disk[1], branch_on_disk=branch_on_disk,
                install_scripts=scripts, builds=built)

        def done(result, error):
            if not self._config.find(repo_id):
                return  # removed while loading
            if repo_id in self._updating or self._finished.get(repo_id, 0) != finished:
                # Updated while this loaded: what it read from disk (your version, where it is) is from before. Loaded
                # again, after the update. (Its "loading" goes, or loading again would think it's under way.)
                if self._details.get(repo_id) and self._details[repo_id].state == "loading":
                    self._details.pop(repo_id)
                if repo_id in self._updating:
                    self._load_after.add(repo_id)
                else:
                    QTimer.singleShot(0, lambda: self.loadDetails(repo_id, True))
                return
            self._approved.pop(repo_id, None)  # (the step's scripts read again, too)
            if error:
                self._details[repo_id] = Details(state="error", error=self._error_text(error))
            else:
                here, on_disk, managed_by, website, self._details[repo_id] = result
                if repo := self._config.find(repo_id):
                    managed_changed = managed_by != repo.managed_by or website != repo.homepage
                    if here != repo.local_path:  # found beside where it was: followed there from now on
                        repo.local_path, managed_changed = here, True
                    repo.managed_by, repo.homepage = managed_by, website
                    # A scanned repo's version is whatever's on disk now (e.g. after a `git pull` outside the app).
                    from_disk = bool(on_disk and on_disk[0] and on_disk[0] != repo.installed)
                    if from_disk:
                        repo.installed = on_disk[0]
                        self._version_changed(repo)
                    baseline_set = _set_baseline(repo, self._details[repo_id])
                    tag_matched = _match_tag(repo, self._details[repo_id])
                    if _fit_files(repo, self._details[repo_id]) or baseline_set or tag_matched or from_disk \
                            or managed_changed:
                        self._changed()
                    self._check_from_page(repo)
            self.detailsChanged.emit(repo_id)

        self._run(work, done)

    def _read_disk_version(self, repo_id):
        """Your version for a scanned repo, read from disk again (no request): after switching what it follows, since
        a clone's version is then a commit or a release tag."""
        repo = self._config.find(repo_id)
        local_path, releases = repo.local_path, repo.follow == FOLLOW_RELEASES

        def done(found, error):
            repo, d = self._config.find(repo_id), self._details.get(repo_id)
            version = found[0] if found and not error else ""
            if not repo or not version:
                return
            repo.installed = version
            if d:
                _match_tag(repo, d)
            self._version_changed(repo)
            self._changed(repo_id)
            if repo.follow == FOLLOW_BRANCH:
                self._refresh_whats_new(repo_id)

        self._run(lambda: scan.version_on_disk(local_path, releases), done)

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
        """Everything a repo's page shows, worked out from what's known (nothing is asked of the site here): its
        releases and files, which file is yours, how your version compares, and what the page may offer. The page
        asks again after every change (detailsChanged), up to a hundred times during a download, so it stays cheap:
        under a millisecond for a project with 30 releases."""
        repo = self._config.find(repo_id)
        d = self._details.get(repo_id) or Details(state="loading")
        shown = [r for r in d.releases if repo and (repo.prereleases or not r.prerelease)]
        pattern = repo.asset_pattern if repo else ""
        releases = []
        for i, rel in enumerate(shown):
            files = []
            yours = assets.pick(pattern, [a.name for a in rel.assets]) if pattern else None
            for a in rel.assets:
                info = assets.classify(a.name, a.url)
                details = [x for x in (_size_text(a.size), info.kind if info.kind != assets.KIND_OTHER else "",
                                       info.note) if x]
                files.append({
                    "name": a.name,
                    "details": " · ".join(details),
                    "suits": info.suits,
                    "selected": a.name == yours,
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
                "isInstalled": bool(repo) and assets.same_version(rel.tag, repo.installed) and not d.local_missing,
            })
        current_branch = (repo.branch if repo else "") or d.default_branch
        # The one place to choose which file to follow: the newest release's files, those for this PC first.
        latest = releases[0] if releases else None
        # Only files that run on this computer can be chosen.
        choices = [f for f in latest["assets"] if f["suits"]] if latest else []
        version = self._version_info(repo, d, shown) if repo and d.state == "ready" else {}
        part_of = self._part_of(repo) if repo else None
        if repo and d.local_missing and version and not repo.managed_by:
            # Removed outside the app: not "Up to date", whatever version it last had. A download can be put back
            # (Install); a clone is left be, as it may only be on a drive that isn't plugged in.
            clone = _is_clone(repo)
            was = f"It was at {updater.shown(repo.local_path)}. "
            version.update(statusKind=STATUS_NOT_INSTALLED, updateAvailable=False, headline=checker.GONE,
                           versionText="Not found", status=was + ("If it moved, scan again; if you removed it, stop "
                           "tracking it." if clone else f"Install puts the newest ({version.get('newestText', '')}) "
                           "back."))
        # A file was picked, but the newest release doesn't have it (renamed or dropped by the project): nothing to
        # update to, whatever the versions say. The page says to choose it again.
        file_missing = bool(pattern) and latest is not None and not latest["hasSelected"]
        if file_missing and version.get("statusKind") == STATUS_UPDATE:
            version.update(statusKind=STATUS_PROBLEM, updateAvailable=False, headline="Your file isn\u2019t in the "
                           "newest release", status=f"{latest['tag']} doesn\u2019t include {pattern}.")
        c = self._current_comparison(repo, d) if repo else None
        behind = c is not None and c.relation == sources.BEHIND
        # A clone on another branch than the one followed: Follow <that branch> is offered instead of Update.
        on_other_branch = bool(repo) and _is_clone(repo) and repo.follow == FOLLOW_BRANCH \
            and d.branch_on_disk and d.branch_on_disk != current_branch
        follow_disk = d.branch_on_disk if on_other_branch else ""
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
            "yourFileMissing": file_missing,
            "branchError": d.branch_error,
            "canUpdate": bool(repo) and _can_update(repo) and not (d.local_missing and _is_clone(repo))
                         and not follow_disk and not part_of,
            "followDiskBranch": follow_disk,
            "isClone": bool(repo) and _is_clone(repo),
            # Another person's clone: shown, but its updates are theirs.
            "theirs": updater.someone_elses(repo.local_path) if repo and _is_clone(repo) else "",
            # Part of another tracked clone (its install script updates this one): shown, not updated on its own.
            "partOf": part_of.name if part_of else "",
            # Install, for an AppImage or program you have but couriercollie doesn't know where (added by hand).
            "newCopy": bool(repo) and _new_copy(repo),
            # Install clones the project into clonesFolder.
            "installClones": bool(repo) and _can_clone(repo),
            # Installed by the package manager or Flatpak: shown only, never updated here.
            "managedBy": repo.managed_by if repo else "",
            # Built only for other systems: its versions are noted, never installed here.
            "otherSystems": _other_systems_note(d) if repo and repo.other_systems else "",
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
            # couriercollie itself, updated while running: the new version is used once it's restarted.
            "restartNeeded": self._restart_needed(repo),
            "othersUpdating": bool(self._updating - {repo_id}),
            **self._applying(repo, d),
            "managedElsewhere": d.managed_elsewhere + self._own_copy_left(repo) if d.managed_elsewhere else "",
            "branches": [
                {"name": b.name, "sha": b.sha[:7], "isDefault": b.name == d.default_branch,
                 "selected": b.name == current_branch}
                for b in d.branches
            ],
        }

    def _applying(self, repo: TrackedRepo | None, d: Details) -> dict:
        """A clone's step (applying.py): what can run after Update downloads, whether Update asks first (the first
        time, unless Only Download was chosen), and how the step last ran."""
        if not repo or repo.managed_by or not _is_clone(repo) or self._part_of(repo):
            return {"stepChoices": [], "step": "", "updateAsks": False}
        choices = self._step_choices(repo, d)
        run = self._steps.get(repo.id)
        mine = next((c for c in choices if c["command"] == repo.apply_command), None)
        return {
            "stepChoices": choices,
            "step": repo.apply_command,
            "stepWhat": mine["what"] if mine else "",
            "stepSkip": repo.apply_skip,
            "stepChanged": bool(repo.apply_command) and not self._step_still_approved(repo, fresh=False),
            # Update asks first what to run (or Only Download): there's something to choose, and it hasn't been.
            "updateAsks": bool(choices) and not repo.apply_command and not repo.apply_skip,
            "stepRunning": bool(run and run.running),
            "stepResult": run.result if run else "",
            "stepCode": run.code if run else 0,
            "stepOutput": "\n".join(run.output) if run else "",
            # For a step that asks for a password the window couldn't take: to run in a terminal instead.
            "stepTerminalLine": (applying.terminal_line(repo.local_path, repo.apply_command)
                                 if repo.apply_command else ""),
        }

    def _step_choices(self, repo: TrackedRepo, d: Details | None = None) -> list[dict]:
        """What can run after Update downloads, to choose from: the suggestions (applying.suggestions), and the step
        approved before if it's none of them. Read from the clone if its page hasn't loaded."""
        if d is None or d.state != "ready":
            path = repo.local_path
            scripts, built = updater.install_scripts(path), applying.builds(path)
        else:
            scripts, built = d.install_scripts, d.builds
        choices = [{"label": s.label, "command": s.command, "what": s.what}
                   for s in applying.suggestions(repo.local_path, scripts, built)]
        if repo.apply_command and all(c["command"] != repo.apply_command for c in choices):
            choices.append({"label": repo.apply_command, "command": repo.apply_command, "what": "the step"})
        return choices

    @staticmethod
    def _own_copy_left(repo: TrackedRepo | None) -> str:
        """For something your package manager now installed too: couriercollie's own copy (an AppImage, or a program
        in ~/.local/bin), still there but no longer updated, and often found first when you run it."""
        if repo and (_is_program(repo) or _is_appimage(repo)) and repo.local_path and Path(repo.local_path).exists():
            return (f" couriercollie\u2019s own copy, {updater.shown(repo.local_path)}, isn\u2019t updated any more: "
                    "delete it to use your package manager\u2019s.")
        return ""

    def _part_of(self, repo: TrackedRepo) -> TrackedRepo | None:
        """The tracked clone this one is part of: it's inside that one's folder, and that one's install script names
        it (AeroThemePlasma's install.sh clones SMOD into its repos/ folder, then builds and installs it). Updating
        that one takes care of this one, so this one is only shown. Only when the script says so: never guessed."""
        if not _is_clone(repo) or not repo.local_path:
            return None
        here = Path(repo.local_path).resolve()
        for other in self._config.repos:
            if other is repo or not _is_clone(other) or not other.local_path:
                continue
            there = Path(other.local_path).resolve()
            if there in here.parents and applying.scripts_name(str(there), [repo.id, *repo.aliases]):
                return other
        return None

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
            if installed and installed not in (NOT_INSTALLED, newest) and not repo.managed_by:
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
        if repo.managed_by:
            text, status, kind, headline = d.managed_version or "Installed", \
                f"{'Flatpak' if repo.managed_by == 'Flatpak' else 'Your package manager'} installed it, and keeps " \
                f"it up to date. The newest here is {newest_text}.", STATUS_MANAGED, \
                checker.installed_with(repo.managed_by)
        elif installed == NOT_INSTALLED and repo.other_systems:
            # Built for other systems: never installed here, so there's only your version to note, not "installed".
            text, status, kind, headline = "Not set", f"The newest is {newest_text}. Mark it as up to date once " \
                "you have it.", STATUS_NOT_INSTALLED, "Version not set"
        elif installed == NOT_INSTALLED:
            text, status, kind, headline = "Not installed", f"The newest is {newest_text}.", STATUS_NOT_INSTALLED, \
                "Not installed"
        elif not installed and repo.source == config.SOURCE_SCANNED and repo.follow != FOLLOW_BRANCH:
            # Found on this computer, so Update replaces it (rather than Install putting a second copy beside it).
            text, status, kind, headline = "Unknown", f"Its version isn\u2019t in its file name. Update replaces it " \
                f"with the newest, {newest_text}.", STATUS_UPDATE, "Version unknown"
        elif installed == newest or (repo.follow != FOLLOW_BRANCH and assets.same_version(installed, newest)):
            text, status, kind, headline = yours_text, "Up to date", STATUS_CURRENT, "Up to date"
        elif repo.follow != FOLLOW_BRANCH and assets.is_newer(installed, newest):
            # Never offered the older one: the newest release may have been taken down, or yours came from elsewhere.
            text, status, kind, headline = yours_text, f"Yours is newer than the newest release ({newest_text}).", \
                STATUS_CURRENT, "Up to date"
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
        where = f"your clone is on {disk}" if disk else f"your version ({yours_text}) isn\u2019t part of it"
        return {"status": f"Not comparable with {branch}: {where}.", "updateAvailable": False,
                "statusKind": STATUS_PROBLEM, "headline": "Not comparable"}

    def _restart_needed(self, repo: TrackedRepo | None) -> bool:
        """couriercollie itself, updated while it runs: your version isn't the one running. Followed as a clone (run
        from one), that's the commit it started at; else its release."""
        from . import __version__

        if not repo or repo.id != self.MYSELF or repo.installed in ("", NOT_INSTALLED) or repo.id in self._updating:
            return False
        if _is_clone(repo):
            return bool(self._started_at) and repo.installed != self._started_at
        return not assets.same_version(repo.installed, __version__)

    @Slot()
    def restartApp(self):
        """Restart couriercollie (after it updated itself): this copy quits, and the new one starts once it's gone. (Not
        before: a second start hands over to the one already open.) Not while something is updating: quitting would
        cut it short."""
        if self._updating:
            return
        wait_then_start = 'while kill -0 "$0" 2>/dev/null; do sleep 0.2; done; exec "$@"'
        QProcess.startDetached("/bin/sh", ["-c", wait_then_start, str(os.getpid()), str(integration.LAUNCHER)])
        QApplication.quit()

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
        version = version.strip()
        repo = self._config.find(repo_id)
        if repo and repo.other_systems and version == NOT_INSTALLED:
            return  # built for other systems: never installed here, so never "not installed" either
        if repo and version and version != repo.installed:
            repo.installed = version
            self._version_changed(repo)
            self._check_from_page(repo)  # never checked yet: the list says it from the page, as the page does
            self._changed(repo_id)
            if repo.follow == FOLLOW_BRANCH:
                self._refresh_whats_new(repo_id)  # compare the new version with the branch

    @Slot(str, str)
    def setFollow(self, repo_id, follow):
        """Follow releases or a branch instead. Your version means something else in each (a release tag, or a
        commit), so it's set again: from disk for a scanned repo, else "Not installed" until you say."""
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
        """Compare your commit with the followed branch's newest again (the branch was changed, or the clone moved),
        for the page's "N new commits" and its list of them."""
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
            return on_disk, branch_on_disk, yours, _compare(ref, host, yours, head, local_path if scanned else "")

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
            self._check_from_page(repo)

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
        """Follow this file (Your Build File). Kept as a pattern with the version as "*", so the same file is found in
        every later release. Only a file that runs on this computer can be picked."""
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
