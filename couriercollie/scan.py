"""Scanning this computer for software that came from GitHub or GitLab (DESIGN.md §1).

Three steps:
1. Find things on disk: git clones, AppImages, packages installed from a downloaded file (RPM, Debian), and
   Flatpak bundles. No network.
2. Check each find with its site (`identify`): which project it is now (sites redirect renamed and moved projects),
   or why it can't be tracked. Finds already on the list are matched without asking the site.
3. Merge into the list (`merge`): a repo already on the list (added by hand, installed from the app, or found before)
   is updated in place and marked as scanned. Only genuinely new ones are added.
"""

import os
import re
import subprocess
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import assets, flatpaks, packages, sources, updater
from .config import FOLLOW_BRANCH, SOURCE_SCANNED, Config, TrackedRepo
from .sources import RepoRef, SourceError

# How deep into a scan folder to look: enough for ~/code/someone/project/subproject, without crawling a whole home
# folder's worth of nested files.
MAX_DEPTH = 6
# Folders not worth looking in: dependencies, build output, caches. Hidden folders (".cache", ".local", …) are skipped
# too.
SKIP_DIRS = {"node_modules", "__pycache__", "venv", "site-packages", "vendor", "target", "build", "dist"}
# Where hand-installed software usually lives (DECISIONS.md, D12): the home folder, and the standard places for
# software installed outside the package manager. Changeable in Settings.
DEFAULT_SCAN_FOLDERS = ("~", "/opt", "/usr/local", "/srv")
# Hidden folders that often hold AppImages. Hidden folders aren't walked, so these are looked in directly, when
# they're inside a scan folder.
HIDDEN_APPIMAGE_DIRS = ("~/.local/bin",)
# RPMs that came from a downloaded file rather than a package repository.
RPM_FROM_FILE = {"@commandline", "<unknown>", "@System"}


@dataclass
class Found:
    """Something a scan found on this computer."""

    id: str  # "<domain>/<path>". Before `identify`, as on disk (may be an old name); after, the project's current one.
    name: str
    url: str
    host: str  # "github"/"gitlab"; empty until identified
    path: str  # where on this computer
    kind: str  # assets.KIND_*: "git" for a clone
    version: str  # what's on disk: a commit for a clone, a version number for an app or RPM; "" if unknown
    branch: str = ""  # for clones: the branch that's checked out
    description: str = ""
    other_paths: list[str] = field(default_factory=list)  # the same project found in more places
    aliases: list[str] = field(default_factory=list)  # old addresses it was found under
    needs_password: bool = False  # in a folder this user can't change (e.g. owned by the system in /opt)
    homepage: str = ""  # the project's own website, once identified ("-" if it gives none)
    release_file: str = ""  # for AppImages: the release file it updates from, e.g. "App-*-x86_64.AppImage"


# ---------------------------------------------------------------------------------------------------------------------
# 1. Finding things on disk


def _clone_info(path: str) -> Found | None:
    remote = updater.git_out(path, "config", "--get", "remote.origin.url")
    if not remote:
        # No "origin": use whichever remote there is.
        first = updater.git_out(path, "remote").splitlines()
        remote = updater.git_out(path, "config", "--get", f"remote.{first[0]}.url") if first else ""
    try:
        ref = sources.parse_url(remote)
    except ValueError:
        return None  # a local folder or an address that isn't a project page
    return Found(
        id=ref.id, name=ref.name, url=ref.web_url, host="", path=path, kind=assets.KIND_GIT,
        version=updater.git_out(path, "rev-parse", "HEAD"),
        branch=updater.git_out(path, "symbolic-ref", "--short", "-q", "HEAD"),
    )


def _inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def scan_roots(folders: Iterable[str]) -> list[Path]:
    """The folders to walk: existing ones only, and none inside another (so nothing is scanned twice)."""
    paths = []
    for folder in folders:
        path = Path(folder).expanduser()
        if path.is_dir():
            paths.append(path.resolve())
    paths = sorted(set(paths), key=lambda p: len(p.parts))
    roots: list[Path] = []
    for path in paths:
        if not any(_inside(path, r) for r in roots):
            roots.append(path)
    return roots


def walk(roots: Iterable[Path], max_depth: int = MAX_DEPTH) -> tuple[list[Found], list[Path]]:
    """Git clones, and AppImage files, in these folders and their subfolders (except hidden and dependency
    folders). Folders that can't be read are skipped."""
    clones, appimages = [], []
    for root in roots:
        base_depth = len(root.parts)
        for dirpath, dirnames, filenames in os.walk(root):
            if ".git" in dirnames or ".git" in filenames:
                if item := _clone_info(dirpath):
                    clones.append(item)
            appimages += [Path(dirpath, f) for f in sorted(filenames) if f.lower().endswith(".appimage")]
            # Keep looking inside clones: some projects keep other clones in subfolders.
            dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and d not in SKIP_DIRS)
            if len(Path(dirpath).parts) - base_depth >= max_depth:
                dirnames[:] = []
    return clones, appimages



def parse_rpm_list(text: str) -> list[Found]:
    """Parse `dnf repoquery --installed --qf '%{name}|%{version}|%{from_repo}|%{url}\\n'`: keep RPMs installed from
    a downloaded file whose homepage is a project page."""
    kept = []
    for line in text.splitlines():
        parts = line.split("|")
        if len(parts) == 4 and parts[2] in RPM_FROM_FILE:
            name, version, _repo, url = parts
            kept.append(f"{name}|{version}|{url}")
    return _from_homepages(assets.KIND_RPM, "\n".join(kept))


def _run_out(*args: str) -> str | None:
    """A command's standard output, or None if it couldn't be run or failed."""
    try:
        result = subprocess.run(list(args), capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout if result.returncode == 0 else None


def _dnf(*args: str) -> str | None:
    return _run_out("dnf", *args)


def offered_by_repos(names: list[str], dnf=_dnf) -> set[str] | None:
    """Which of these packages a repository you have enabled offers (Fedora, RPM Fusion, a COPR, or one an RPM added
    itself when installed): dnf updates those, so they're not for this app. None if dnf couldn't be asked."""
    if not names:
        return set()
    out = dnf("repoquery", "--available", "--qf", "%{name}\n", *names)
    return None if out is None else {line.strip() for line in out.splitlines()} & set(names)


def find_rpms(dnf=_dnf) -> list[Found]:
    """RPMs only you can update: installed from a downloaded file, from a GitHub or GitLab project, and offered by no
    repository you have enabled. If dnf can't say which repositories offer them, none are listed (DECISIONS.md, D12)."""
    out = dnf("repoquery", "--installed", "--qf", "%{name}|%{version}|%{from_repo}|%{url}\n")
    candidates = parse_rpm_list(out) if out is not None else []
    offered = offered_by_repos([f.name for f in candidates], dnf)
    if offered is None:
        return []
    return [f for f in candidates if f.name not in offered]


def _from_homepages(kind: str, lines: str) -> list[Found]:
    """Packages as "name|version|homepage" lines, kept if the homepage is a project's page."""
    found = []
    for line in lines.splitlines():
        parts = line.split("|")
        if len(parts) != 3:
            continue
        name, version, url = parts
        try:
            ref = sources.parse_url(url)
        except ValueError:
            continue
        found.append(Found(id=ref.id, name=name, url=ref.web_url, host="", path=packages.place(kind, name), kind=kind,
                           version=packages.upstream_version(version)))
    return found


def find_debs(run=_run_out) -> list[Found]:
    """Debian packages only you can update: apt marks one no repository you have offers as "local" (installed from
    a downloaded file, and not added by a repository since). Kept if its homepage is a GitHub or GitLab project."""
    listed = run("apt", "list", "--installed")
    names = [line.split("/", 1)[0] for line in (listed or "").splitlines() if line.rstrip().endswith(",local]")]
    if not names:
        return []
    homepages = run("dpkg-query", "--show", "--showformat=${Package}|${Version}|${Homepage}\n", *names)
    return _from_homepages(assets.KIND_DEB, homepages or "")


def find_zypper_rpms(run=_run_out) -> list[Found]:
    """openSUSE's RPMs only you can update: zypper lists one no repository offers under "(System Packages)"."""
    listed = run("zypper", "--quiet", "--xmlout", "search", "--installed-only", "--details", "--type", "package")
    names = sorted(set(re.findall(r'<solvable [^>]*name="([^"]+)"[^>]*repository="\(System Packages\)"', listed or "")))
    if not names:
        return []
    return _from_homepages(assets.KIND_RPM, run("rpm", "-q", "--qf", "%{NAME}|%{VERSION}|%{URL}\n", *names) or "")


def find_flatpak_bundles() -> list[Found]:
    """Flatpaks installed from a bundle file (Flatpak never updates those), kept if their homepage is a project's."""
    found = []
    for app_id, where in flatpaks.from_bundles():
        try:
            ref = sources.parse_url(flatpaks.homepage(app_id))
        except ValueError:
            continue
        found.append(Found(id=ref.id, name=app_id.rsplit(".", 1)[-1], url=ref.web_url, host="",
                           path=flatpaks.place(app_id, where), kind=assets.KIND_FLATPAK,
                           version=flatpaks.installed_version(app_id)[0]))
    return found


def find_packages() -> list[Found]:
    """Packages installed from a downloaded file that the package manager doesn't update: RPMs (dnf, or zypper),
    and Debian packages (apt). Not Arch's: pacman can't tell a downloaded package from one built from the AUR, which
    AUR helpers keep up to date."""
    if assets.has("dnf"):
        return find_rpms()
    if assets.has("zypper"):
        return find_zypper_rpms()
    if assets.has("apt"):
        return find_debs()
    return []


# AppImages made with the standard tools carry where they update from, e.g.
# "gh-releases-zsync|owner|repo|latest|App-*-x86_64.AppImage.zsync": the project, and (usually) its release file.
_UPDATE_INFO = re.compile(rb"gh-releases-zsync\|([A-Za-z0-9_.-]+)\|([A-Za-z0-9_.-]+)\|"
                          rb"(?:[^|\x00]*\|([A-Za-z0-9_.*+~-]+)\.zsync)?")
# "1.18.2", optionally with a pre-release part like "-beta.2" or "-rc1" (but not "-linux").
_VERSION_IN_NAME = re.compile(r"(?<![\d.])v?(\d+(?:\.\d+)+(?:[-~](?:rc|beta|alpha|pre|dev)[0-9.]*)?)(?=[-_.+]|$)",
                              re.I)


def appimage_version(filename: str) -> str:
    """The version in an AppImage's file name, e.g. "LocalSend-1.18.2-linux-x86-64.AppImage" -> "1.18.2"."""
    stem = re.sub(r"\.appimage$", "", filename, flags=re.I)
    m = _VERSION_IN_NAME.search(stem)
    return m.group(1) if m else ""


def appimage_source(path: Path) -> tuple[RepoRef, str] | None:
    """Where an AppImage updates from: the project, and its release file ("" if it doesn't say)."""
    try:
        with open(path, "rb") as f:
            head = f.read(4 * 1024 * 1024)  # the update info sits near the start of the file
    except OSError:
        return None
    if not (m := _UPDATE_INFO.search(head)):
        return None
    return RepoRef("github.com", f"{m.group(1).decode()}/{m.group(2).decode()}"), (m.group(3) or b"").decode()


def _appimage(path: Path) -> Found | None:
    """An AppImage that says where it came from. Others can't be matched to a project, so they're left out; they can
    still be added by hand."""
    if not path.is_file() or not (source := appimage_source(path)):
        return None
    ref, release_file = source
    return Found(id=ref.id, name=ref.name, url=ref.web_url, host="github", path=str(path),
                 kind=assets.KIND_APPIMAGE, version=appimage_version(path.name), release_file=release_file)


def find_appimages(dirs: Iterable[str]) -> list[Found]:
    """AppImages directly in these folders (not their subfolders)."""
    found = []
    for d in dirs:
        folder = Path(d).expanduser()
        if folder.is_dir():
            found += [f for p in sorted(folder.iterdir()) if p.suffix.lower() == ".appimage" and (f := _appimage(p))]
    return found


def find_all(folders: Iterable[str] = DEFAULT_SCAN_FOLDERS, system_packages: Callable[[], list[Found]] = find_packages,
             bundles: Callable[[], list[Found]] = find_flatpak_bundles,
             max_depth: int = MAX_DEPTH) -> list[Found]:
    """Everything on this computer, with each project listed once (extra places go in `other_paths`)."""
    roots = scan_roots(folders)
    clones, appimage_files = walk(roots, max_depth)
    hidden = [d for d in HIDDEN_APPIMAGE_DIRS if any(_inside(Path(d).expanduser().resolve(), r) for r in roots)]
    items = (clones + system_packages() + [f for p in appimage_files if (f := _appimage(p))] + find_appimages(hidden)
             + bundles())
    for item in items:
        if item.kind in packages.LABELS or item.kind == assets.KIND_FLATPAK:
            continue  # packages: through the package manager, which asks for the password itself; Flatpaks: for you
        # Updating a clone changes its folder; updating an AppImage replaces the file in its folder.
        target = item.path if item.kind == assets.KIND_GIT else str(Path(item.path).parent)
        item.needs_password = not os.access(target, os.W_OK)
    by_id: dict[str, Found] = {}
    for item in items:
        key = item.id.lower()
        if key in by_id:
            by_id[key].other_paths.append(item.path)
        else:
            by_id[key] = item
    return list(by_id.values())


def version_on_disk(path: str, releases: bool = False) -> tuple[str, bool]:
    """What's on this computer now for a scanned repo, read from where the scan found it: (version, still there).
    A clone's commit (or, when it follows releases, the release tag it's at), an AppImage's version from its file
    name, or a package's installed version (packages.py)."""
    if package := packages.from_place(path):
        return packages.installed_version(*package)
    if app_id := flatpaks.from_place(path)[0]:
        return flatpaks.installed_version(app_id)
    p = Path(path)
    if p.is_symlink() and (version := updater.program_version(p)):
        return version, True  # a program the app installed: its link points into that version's folder
    if (p / ".git").exists():
        tags = updater.git_out(path, "tag", "--points-at", "HEAD").split() if releases else []
        return (tags[0] if tags else updater.git_out(path, "rev-parse", "HEAD")), True
    if p.is_file() and p.suffix.lower() == ".appimage":
        return appimage_version(p.name), True
    return "", False


def branch_on_disk(path: str) -> str:
    """The branch checked out in a clone, or "" (not a clone, or no branch checked out)."""
    return updater.git_out(path, "symbolic-ref", "--short", "-q", "HEAD") if (Path(path) / ".git").exists() else ""


# ---------------------------------------------------------------------------------------------------------------------
# 2. Checking finds with their site


@dataclass
class Checked:
    found: Found
    problem: str = ""  # why it can't be tracked, for the user; empty if it can


LOOKUPS_AT_ONCE = 4


def _identify_one(item: Found, lookup: Callable[[RepoRef], sources.ProjectInfo]) -> Checked:
    try:
        info = lookup(RepoRef.from_id(item.id))
    except sources.NotFound:
        return Checked(item, "Not found on its site. It may be private, or have been removed.")
    except SourceError as e:
        return Checked(item, str(e))
    if info.ref.id.lower() != item.id.lower():
        item.aliases.append(item.id)
    item.id, item.url, item.host = info.ref.id, info.ref.web_url, info.host
    item.description = info.description
    item.homepage = info.homepage or "-"
    if item.kind == assets.KIND_GIT:
        item.name = info.name or item.name
    return Checked(item)


def identify(items: list[Found], known: Callable[[str], bool],
             lookup: Callable[[RepoRef], sources.ProjectInfo] | None = None) -> list[Checked]:
    """Ask each find's site which project it is now. `known(id)` says if an address is already on the list: those
    aren't looked up, so a scan of things you already track uses no requests. Lookups run a few at a time; results
    keep the order of `items`."""
    lookup = lookup or sources.project_info
    with ThreadPoolExecutor(max_workers=LOOKUPS_AT_ONCE) as pool:
        futures = [None if known(item.id) else pool.submit(_identify_one, item, lookup) for item in items]
        return [Checked(item) if f is None else f.result() for item, f in zip(items, futures)]


def _plain(text: str) -> str:
    return " ".join(text.lower().split())


def looks_like(config: Config, item: Found) -> TrackedRepo | None:
    """A tracked repo that's probably the same project under another address: a mirror on another site (e.g. a GitHub
    copy of a GitLab project). Same project name and same description, ignoring case and spacing. Addresses alone
    can't tell, so the user decides."""
    if not item.description.strip():
        return None
    name = RepoRef.from_id(item.id).name.lower()
    return next((r for r in config.repos
                 if RepoRef.from_id(r.id).name.lower() == name and _plain(r.description) == _plain(item.description)),
                None)


# ---------------------------------------------------------------------------------------------------------------------
# 3. Merging into the list


@dataclass
class MergeResult:
    added: list[TrackedRepo]
    updated: list[TrackedRepo]  # already on the list; now marked as scanned


def link_to(item: Found, repo: TrackedRepo) -> Found:
    """Make a find merge into `repo` (the user confirmed it's the same project): the find's address becomes an alias."""
    if item.id.lower() != repo.id.lower():
        item.aliases.append(item.id)
        item.id = repo.id
    return item


def merge(config: Config, found: list[Found], resolve: Callable[[str], str | None] = lambda _id: None) -> MergeResult:
    """Add or update tracked repos from scan finds.

    A find matches a tracked repo by its address, any address it was found under (`Found.aliases`), or the tracked
    repo's own aliases. `resolve` gives a project's current address for an old one, or None; it's only asked when
    nothing matches directly.
    """
    result = MergeResult(added=[], updated=[])
    for item in found:
        repo = next((r for a in (item.id, *item.aliases) if (r := config.find_any(a))), None)
        if repo is None and (current := resolve(item.id)):
            repo = config.find_any(current)
        if repo is None:
            repo = TrackedRepo(
                id=item.id, name=item.name, url=item.url, host=item.host, description=item.description,
                added_at=datetime.now(timezone.utc).isoformat(timespec="seconds"), homepage=item.homepage,
            )
            config.repos.append(repo)
            result.added.append(repo)
        elif repo not in result.updated:
            result.updated.append(repo)
        # Remember old addresses, so the next scan matches without asking the site.
        for alias in (item.id, *item.aliases):
            if alias.lower() != repo.id.lower() and alias.lower() not in (a.lower() for a in repo.aliases):
                repo.aliases.append(alias)
        _apply(repo, item)
    return result


def _apply(repo: TrackedRepo, item: Found) -> None:
    """What's on disk wins over what was set by hand: it's the version you actually have. A clone already tracked
    there that follows releases (moved to each release's tag) stays that way: found again by a scan, it's the same."""
    by_release = repo.kind == assets.KIND_GIT and repo.local_path == item.path and repo.follow != FOLLOW_BRANCH
    exact = item.release_file if "*" not in item.release_file else ""
    repo.source = SOURCE_SCANNED
    repo.local_path = item.path
    if item.kind == assets.KIND_GIT and not by_release:
        # A clone's version is a commit, so it's followed by branch.
        repo.follow, repo.kind = FOLLOW_BRANCH, assets.KIND_GIT
        if item.branch:
            repo.branch = item.branch
    elif item.kind == assets.KIND_APPIMAGE and not repo.asset_pattern and (item.version or exact):
        # Follow the same file as the one on disk, e.g. "App-*-x86_64.AppImage"; or, renamed without its version,
        # the one it says it updates from, if that's one file (its "*" is any text, not just a version).
        repo.asset_pattern = assets.pattern_for(Path(item.path).name, item.version) if item.version else exact
        repo.kind = assets.KIND_APPIMAGE
    if item.version and not by_release:  # (its version is the release's tag, read from disk when its page loads)
        repo.installed = item.version
