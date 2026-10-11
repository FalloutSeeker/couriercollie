"""Single-file Flatpak bundles from a project's releases ("App.flatpak"). Installed from a file, a bundle's origin has
no address to update from, so Flatpak never updates it; the app does. Installed for you only (flatpak --user), so no
password is needed. (Flatpaks installed from a repository, like Flathub, stay Flatpak's to update.)
"""

import re
import subprocess
from pathlib import Path

# "Flatpak “org.example.Tool”", or "… (all users)" when it's installed system-wide: the app doesn't update those, as
# flatpak would read the file as root from a folder you can write to, with no way to check it again there.
_PLACE = re.compile(r"Flatpak “(.+)”( \(all users\))?")
# A bundle names the app it holds, e.g. "app/org.example.Tool/x86_64/stable", near its start.
_REF = re.compile(rb"app/([A-Za-z][\w-]*(?:\.[\w-]+)+)/(\w+)/([\w.-]+)")
_HOMEPAGE = re.compile(r"<url\s+type=[\"']homepage[\"']\s*>\s*([^<\s]+)\s*</url>")
_RELEASE = re.compile(r"<release\b[^>]*\bversion=[\"']([^\"']+)[\"']")
INSTALL_TIMEOUT = 1800


def place(app_id: str, where: str = "user") -> str:
    return f"Flatpak “{app_id}”" + (" (all users)" if where == "system" else "")


def from_place(local_path: str) -> tuple[str, str]:
    """(app ID, "user" or "system") of a repo whose place is a Flatpak, else ("", "")."""
    m = _PLACE.fullmatch(local_path)
    return (m.group(1), "system" if m.group(2) else "user") if m else ("", "")


def _flatpak(*args: str, timeout: int = 60) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(["flatpak", *args], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None


def bundle_app(path: Path) -> tuple[str, str]:
    """(app ID, processor) a bundle holds, read from the file without installing it. ("", "") if it isn't one."""
    with path.open("rb") as f:
        m = _REF.search(f.read(64 * 1024))
    return (m.group(1).decode(), m.group(2).decode()) if m else ("", "")


def installation(app_id: str) -> str:
    """Where the app is installed: "user", "system", or "" if it isn't."""
    for where in ("user", "system"):
        result = _flatpak("info", f"--{where}", app_id)
        if result and result.returncode == 0:
            return where
    return ""


def _metainfo(app_id: str, where: str = "") -> str:
    """The app's AppStream file (its homepage, its versions), from where it's installed."""
    where = where or installation(app_id)
    result = _flatpak("info", f"--{where}", "--show-location", app_id) if where else None
    if not result or result.returncode != 0:
        return ""
    folder = Path(result.stdout.strip()) / "files" / "share"
    for path in (folder / "metainfo" / f"{app_id}.metainfo.xml", folder / "appdata" / f"{app_id}.appdata.xml"):
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
    return ""


def installed_version(app_id: str) -> tuple[str, bool]:
    """(the installed version, from the app's own release list; whether it's installed)."""
    if not installation(app_id):
        return "", False
    m = _RELEASE.search(_metainfo(app_id))
    return (m.group(1) if m else ""), True


# Installed apps' homepages, read once per run (each takes two flatpak calls).
_homepages: dict[tuple[str, str], str] = {}


def homepage(app_id: str, where: str = "") -> str:
    key = (app_id, where)
    if key not in _homepages:
        m = _HOMEPAGE.search(_metainfo(app_id, where))
        _homepages[key] = m.group(1) if m else ""
    return _homepages[key]


def _installed_apps() -> list[tuple[str, str, bool]]:
    """(app ID, installation, whether its origin has an address to update from) for every installed app. An app
    installed from a bundle file has an origin without one."""
    apps = _flatpak("list", "--app", "--columns=application,origin,installation")
    if not apps or apps.returncode != 0:
        return []
    addresses = {}
    for where in ("user", "system"):
        remotes = _flatpak("remotes", f"--{where}", "--show-disabled", "--columns=name,url")
        for line in (remotes.stdout.splitlines() if remotes and remotes.returncode == 0 else []):
            name, _, url = line.partition("\t")
            if name.strip():
                addresses[(name.strip(), where)] = bool(url.strip())
    found = []
    for line in apps.stdout.splitlines():
        parts = [p.strip() for p in line.split("\t")]
        if len(parts) == 3 and (parts[1], parts[2]) in addresses:
            found.append((parts[0], parts[2], addresses[(parts[1], parts[2])]))
    return found


def from_bundles() -> list[tuple[str, str]]:
    """(app ID, installation) of apps installed from a bundle file: their origin has no address to update from."""
    return [(app_id, where) for app_id, where, updatable in _installed_apps() if not updatable]


def managed_by_flatpak(repo_ids: list[str]) -> tuple[str, str] | None:
    """(app ID, its version) if the project behind these addresses is installed as a Flatpak from a repository
    (Flathub, etc.), which Flatpak keeps up to date. Matched by the app's homepage (sources.same_project), never by a
    similar name."""
    from . import sources

    for app_id, where, updatable in _installed_apps():
        if updatable and sources.same_project(homepage(app_id, where), repo_ids):
            return app_id, installed_version(app_id)[0]
    return None


def install(path: Path) -> subprocess.CompletedProcess | None:
    """Install (or update to) the bundle at `path`, for you only."""
    return _flatpak("install", "--user", "--noninteractive", "--reinstall", "--bundle", str(path),
                    timeout=INSTALL_TIMEOUT)
