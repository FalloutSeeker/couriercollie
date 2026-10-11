"""An icon for each tracked repo, found once when the repo first appears and then saved (DECISIONS.md, D13).

In order, the first that turns something up:
1. On this computer: an installed package's menu entry, a scanned AppImage's own icon (read with 7z, never run), an icon
   file in a scanned clone, or an installed app whose menu entry matches the repo's name.
2. The project's picture on its site (sources.ProjectInfo.icon_url), downloaded once.
3. Nothing: NONE is saved, and the window shows the default icon for the kind of repo.

The result is "theme:<name>" (an icon from the desktop's icon theme), "file:<path>" (a picture in the cache folder or
on disk), or NONE.
"""

import hashlib
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

from . import packages, sources

NONE = "-"
MAX_BYTES = 1024 * 1024
IMAGE_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/svg+xml": ".svg", "image/gif": ".gif",
               "image/webp": ".webp"}
IMAGE_SUFFIXES = (".png", ".svg", ".jpg", ".jpeg", ".gif", ".webp")
APPLICATION_DIRS = ("~/.local/share/applications", "/usr/local/share/applications", "/usr/share/applications",
                    "~/.local/share/flatpak/exports/share/applications", "/var/lib/flatpak/exports/share/applications")
ICON_DIRS = ("~/.local/share/icons", "/usr/local/share/icons", "/usr/share/icons",
             "~/.local/share/flatpak/exports/share/icons", "/var/lib/flatpak/exports/share/icons")
# Where projects usually keep their icon, relative to the clone ("{name}" is the project's name).
CLONE_ICON_FILES = ("icon.svg", "icon.png", "logo.svg", "logo.png", "{name}.svg", "{name}.png",
                    "assets/icon.svg", "assets/icon.png", "assets/logo.svg", "assets/logo.png",
                    "data/icon.svg", "data/icon.png", "resources/icon.svg", "resources/icon.png",
                    "images/logo.svg", "images/logo.png", "docs/logo.svg", "docs/logo.png")


def cache_dir() -> Path:
    base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return base / "couriercollie" / "icons"


def _cache_name(repo_id: str, suffix: str) -> Path:
    return cache_dir() / (hashlib.sha1(repo_id.lower().encode()).hexdigest()[:16] + suffix)


def _keep(repo_id: str, data: bytes, suffix: str) -> str:
    """Save a picture in the cache folder. Returns "file:<path>", or "" if it's too big or not a picture."""
    if not data or len(data) > MAX_BYTES or suffix not in IMAGE_SUFFIXES:
        return ""
    if suffix != ".svg" and not _looks_like_image(data):
        return ""
    path = _cache_name(repo_id, suffix)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return f"file:{path}"


def _looks_like_image(data: bytes) -> bool:
    return data.startswith((b"\x89PNG", b"\xff\xd8", b"GIF8")) or (data[:4] == b"RIFF" and data[8:12] == b"WEBP")


def _plain(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


# ---------------------------------------------------------------------------------------------------------------------
# 1. On this computer


def theme_icon_exists(name: str) -> bool:
    """Whether an icon theme (or /usr/share/pixmaps) has an icon by this name. Themes keep icons three folders deep
    ("hicolor/48x48/apps/x.png", "breeze/apps/48/x.svg")."""
    for d in ICON_DIRS:
        root = Path(d).expanduser()
        if root.is_dir() and any(root.glob(f"*/*/*/{name}.*")):
            return True
    return any(Path("/usr/share/pixmaps").glob(f"{name}.*"))


def _from_icon_key(value: str) -> str:
    """The Icon= line of a menu entry, as a result (or "" if it points at nothing)."""
    value = value.strip()
    if not value:
        return ""
    if value.startswith("/"):
        return f"file:{value}" if Path(value).is_file() else ""
    return f"theme:{value}" if theme_icon_exists(value) else ""


def _desktop_entry(path: Path) -> dict[str, str]:
    """The [Desktop Entry] section of a menu entry file."""
    entry, inside = {}, False
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {}
    for line in lines:
        if line.startswith("["):
            inside = line.strip() == "[Desktop Entry]"
        elif inside and "=" in line:
            key, _, value = line.partition("=")
            entry.setdefault(key.strip(), value.strip())
    return entry


def from_package(kind: str, package: str) -> str:
    """The icon of an installed package's menu entry."""
    for line in packages.files_of(kind, package):
        if line.endswith(".desktop") and "/applications/" in line:
            if icon := _from_icon_key(_desktop_entry(Path(line)).get("Icon", "")):
                return icon
    return ""


def from_appimage(repo_id: str, path: Path) -> str:
    """The AppImage's own icon (".DirIcon", usually a link to the real picture), read without running it."""
    seven_zip = shutil.which("7z")
    if not seven_zip or not path.is_file():
        return ""

    def read(member: str) -> bytes:
        try:
            result = subprocess.run([seven_zip, "x", "-so", str(path), member], capture_output=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            return b""
        return result.stdout if result.returncode == 0 else b""

    data = read(".DirIcon")
    if data and len(data) < 256 and not _looks_like_image(data) and b"<svg" not in data:
        target = data.decode(errors="replace").strip().lstrip("./")  # a link to the real file inside
        data, suffix = read(target), Path(target).suffix.lower()
    else:
        suffix = ".svg" if b"<svg" in data[:1024] else ".png"
    return _keep(repo_id, data, suffix)


def from_clone(repo_id: str, folder: Path, name: str) -> str:
    for relative in CLONE_ICON_FILES:
        path = folder / relative.format(name=name)
        if path.is_file():
            try:
                if icon := _keep(repo_id, path.read_bytes(), path.suffix.lower()):
                    return icon
            except OSError:
                continue
    return ""


def from_installed_app(names: list[str]) -> str:
    """An installed app whose menu entry matches one of these names (its file name, a part of it like the "localsend"
    in "org.localsend.localsend", or its Name=). Very short names are skipped, to avoid chance matches."""
    wanted = {_plain(n) for n in names if len(_plain(n)) >= 4}
    if not wanted:
        return ""
    for d in APPLICATION_DIRS:
        folder = Path(d).expanduser()
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.desktop")):
            parts = {_plain(path.stem)} | {_plain(p) for p in path.stem.split(".")}
            entry = None
            if not parts & wanted:
                entry = _desktop_entry(path)
                if _plain(entry.get("Name", "")) not in wanted:
                    continue
            entry = entry or _desktop_entry(path)
            if icon := _from_icon_key(entry.get("Icon", "")):
                return icon
    return ""


def on_this_computer(repo_id: str, name: str, project: str, local_path: str) -> str:
    if package := packages.from_place(local_path):
        if icon := from_package(*package):
            return icon
    elif local_path.lower().endswith(".appimage"):
        if icon := from_appimage(repo_id, Path(local_path)):
            return icon
    elif local_path and (Path(local_path) / ".git").exists():
        if icon := from_clone(repo_id, Path(local_path), project):
            return icon
    return from_installed_app([name, project])


# ---------------------------------------------------------------------------------------------------------------------
# 2. The project's picture on its site


class Unreachable(Exception):
    """The site couldn't be asked. The repo is left unresolved, so the next time the window loads it tries again."""


def download(repo_id: str, url: str) -> str:
    """The picture at `url`, saved in the cache folder; "" if there's none or it isn't a usable picture. Raises
    Unreachable if the site couldn't be reached."""
    if not url:
        return ""
    if "avatars.githubusercontent.com" in url:
        url += ("&" if "?" in url else "?") + "s=128"  # a small copy is plenty for a list icon
    req = urllib.request.Request(url, headers={"User-Agent": sources.USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=sources.TIMEOUT) as resp:
            suffix = IMAGE_TYPES.get(resp.headers.get_content_type(), "")
            data = resp.read(MAX_BYTES + 1)
    except urllib.error.HTTPError:
        return ""  # the site answered: there's no picture there
    except (OSError, ValueError) as e:
        raise Unreachable(str(e)) from e
    return _keep(repo_id, data, suffix) if suffix else ""


# ---------------------------------------------------------------------------------------------------------------------


def resolve(repo_id: str, name: str, local_path: str, icon_url: str | None = None) -> str:
    """Find an icon for a repo, in the order at the top of this file. `icon_url` is the site's picture address if
    it's already known (None: ask the site, one request). Raises Unreachable if the site couldn't be asked."""
    project = sources.RepoRef.from_id(repo_id).name
    if icon := on_this_computer(repo_id, name, project, local_path):
        return icon
    if icon_url is None:
        try:
            icon_url = sources.project_info(sources.RepoRef.from_id(repo_id)).icon_url
        except sources.NotFound:
            icon_url = ""
        except sources.SourceError as e:
            raise Unreachable(str(e)) from e
    return download(repo_id, icon_url) or NONE
