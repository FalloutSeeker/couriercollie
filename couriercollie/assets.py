"""Release build files: what kind each one is, whether it suits this computer, and remembering which one you use.

The chosen file is stored as a pattern with the version replaced by "*", so "App-1.2-x86_64.AppImage" picked today
still matches "App-1.3-x86_64.AppImage" in the next release.
"""

import platform
import re
import shutil
from dataclasses import dataclass

KIND_RPM = "RPM"
KIND_DEB = "Debian package"
KIND_ARCH = "Arch package"
KIND_FLATPAK = "Flatpak bundle"
KIND_APPIMAGE = "AppImage"
KIND_PROGRAM = "Program"
KIND_GIT = "git"
# A download whose type can't be told from its name or link (GitLab links are often just labelled "Linux (x86_64)").
KIND_FILE = "File"
KIND_OTHER = "Other"
# Not a file: the project has nothing that runs on this computer, so only its versions are tracked.
KIND_VERSIONS = "versions"

_ARCHIVES = (".tar.gz", ".tgz", ".tar.xz", ".txz", ".tar.bz2", ".tbz2", ".tar.zst", ".zip")
# Files for other systems, or that aren't software at all.
_FOREIGN_EXT = {
    ".deb": "Debian/Ubuntu", ".exe": "Windows", ".msi": "Windows", ".msix": "Windows", ".dmg": "macOS",
    ".pkg": "macOS", ".apk": "Android", ".aab": "Android", ".ipa": "iOS",
}
_NOT_SOFTWARE = (".sha256", ".sha512", ".sha256sum", ".sha512sum", ".sig", ".asc", ".minisig", ".pem", ".sbom",
                 ".json", ".txt", ".md5", ".spdx", ".intoto.jsonl", ".idsig", ".cert", ".crt", ".pub")
# Whole words only, so "studios" isn't read as "iOS".
_FOREIGN_OS = re.compile(
    r"(?<![a-z])(windows|win32|win64|darwin|macos|osx|mac|android|ios|freebsd|openbsd|netbsd)(?![a-z])", re.I
)
# Windows-only even without saying so: installers ("App.Setup.1.2.zip", "app-setup-x64.zip") and screensavers (".scr").
_WINDOWS_HINT = re.compile(r"(?<![a-z])setup(?![a-z])|\.scr(?![a-z])", re.I)

_ARCH_WORDS = {
    "x86_64": ("x86_64", "x86-64", "amd64", "x64", "linux64"),
    "aarch64": ("aarch64", "arm64", "arm-64", "armv8"),
}
_ANY_ARCH = re.compile(r"(x86_64|x86-64|amd64|x64|aarch64|arm64|arm-64|armv7|armhf|armel|armv6|arm32|i386|i586|i686|"
                       r"386|riscv64|riscv32|powerpc64le|powerpc64|powerpc|ppc64le|ppc64|ppc|s390x|loongarch64|"
                       r"loong64|mips64el|mips64|mipsel|mips|sparc64)", re.I)


# Package managers on this computer: which package files can be installed here (packages.py). Looked up once, as
# every file of every release on a page is classified.
PACKAGE_TOOLS: set[str] | None = None


def has(tool: str) -> bool:
    global PACKAGE_TOOLS
    if PACKAGE_TOOLS is None:
        PACKAGE_TOOLS = {t for t in ("dnf", "apt", "pacman", "zypper", "flatpak") if shutil.which(t)}
    return tool in PACKAGE_TOOLS


@dataclass
class AssetInfo:
    kind: str
    suits: bool  # likely to run on this computer
    note: str  # short reason when it doesn't suit, e.g. "for Windows"


def classify(name: str, url: str = "", machine: str | None = None) -> AssetInfo:
    """What kind of file this is and whether it suits this computer. The link's file name is used when the name is
    only a label."""
    machine = machine or platform.machine()
    info = _classify_name(name.lower(), machine)
    if info.kind == KIND_FILE and url:
        from_url = _classify_name(url.lower().split("?", 1)[0].rsplit("/", 1)[-1], machine)
        if from_url.kind != KIND_FILE:
            return from_url
    return info


def _foreign_package(name: str) -> AssetInfo:
    """A package for another distro's package manager."""
    return AssetInfo(KIND_OTHER, False, f"{name}: not supported on your distro")


def _kind_of(lower: str) -> "str | AssetInfo":
    """What kind of file a name is, other than a package: or why it doesn't suit, as an AssetInfo."""
    if lower.endswith(".flatpakref"):
        return AssetInfo(KIND_OTHER, False, "Flatpak: install it with your software center instead")
    if lower.endswith(".flatpak"):
        return KIND_FLATPAK if has("flatpak") else AssetInfo(KIND_OTHER, False, "Flatpak: flatpak isn\u2019t installed")
    if lower.endswith(".snap"):
        return AssetInfo(KIND_OTHER, False, "Snap: not supported")
    # A file belonging to another system's package, e.g. "app-x86_64.apk.idsig": check before the processor type,
    # or "x86_64" would make it look like it fits this PC.
    for ext, system in _FOREIGN_EXT.items():
        if ext + "." in lower:
            return AssetInfo(KIND_OTHER, False, f"for {system}")
    if _WINDOWS_HINT.search(lower) and not lower.endswith((".rpm", ".appimage")):
        return AssetInfo(KIND_OTHER, False, "for Windows")
    if lower.endswith(_NOT_SOFTWARE):
        return AssetInfo(KIND_OTHER, False, "checksum or signature")
    if lower.endswith(".src.rpm"):
        return AssetInfo(KIND_OTHER, False, "source package")
    if lower.endswith(".appimage"):
        return KIND_APPIMAGE
    if lower.endswith(_ARCHIVES):
        return KIND_PROGRAM
    if lower.endswith(tuple(_FOREIGN_EXT)):
        return AssetInfo(KIND_OTHER, False, f"for {_FOREIGN_EXT['.' + lower.rsplit('.', 1)[-1]]}")
    return KIND_FILE


def _classify_name(lower: str, machine: str) -> AssetInfo:
    # Packages: for this distro's package manager (installed with it, packages.py), or for another's. Arch's before
    # macOS's ".pkg" below.
    package = None
    if lower.endswith((".pkg.tar.zst", ".pkg.tar.xz")):
        package = KIND_ARCH if has("pacman") else _foreign_package("Arch package")
    elif lower.endswith(".deb"):
        package = KIND_DEB if has("apt") else _foreign_package("Debian package")
    elif lower.endswith(".rpm") and not lower.endswith(".src.rpm"):
        package = KIND_RPM if has("dnf") or has("zypper") else _foreign_package("RPM")
    if isinstance(package, AssetInfo):
        return package
    kind = package or _kind_of(lower)
    if isinstance(kind, AssetInfo):
        return kind

    if m := _FOREIGN_OS.search(lower):
        return AssetInfo(kind, False, f"for {_os_label(m.group(1))}")
    own = _ARCH_WORDS.get(machine, (machine,))
    if any(w in lower for w in own):
        return AssetInfo(kind, True, "")
    if m := _ANY_ARCH.search(lower):
        return AssetInfo(kind, False, f"for {m.group(1)} processors")
    # No processor mentioned: usually fine for RPMs ("noarch") and AppImages with a single build. A file of unknown
    # type only counts if it says it's for Linux.
    return AssetInfo(kind, kind != KIND_FILE or "linux" in lower, "")


def _os_label(word: str) -> str:
    word = word.lower()
    if word.startswith("win"):
        return "Windows"
    if word in ("darwin", "macos", "osx", "mac"):
        return "macOS"
    return {"android": "Android", "ios": "iOS"}.get(word, word.capitalize())


def version_of(tag: str) -> str:
    """The changing part of a tag, from its first digit: "v1.2.3" -> "1.2.3", "nightly-2026" -> "2026"."""
    m = re.search(r"\d", tag)
    return tag[m.start():] if m else ""


# What "*" in a pattern matches: a version number. Starts with a digit; may contain dashes only before another
# number or a pre-release word, so "1.2.0", "2024-01-05" and "2.0-rc1" match, but "CLI-1.2" or "1.2-debuginfo" don't.
_VERSION = r"\d[0-9A-Za-z.+~_]*(?:-(?:\d|rc|beta|alpha|pre)[0-9A-Za-z.+~_]*)*"


def pattern_for(asset_name: str, tag: str) -> str:
    """The pattern that finds this same file in later releases: the name with its version replaced by "*"."""
    version = version_of(tag)
    if version and version in asset_name:
        return asset_name.replace(version, "*")
    return asset_name


def matches(pattern: str, asset_name: str) -> bool:
    if not pattern:
        return False
    regex = _VERSION.join(re.escape(part) for part in pattern.split("*"))
    return re.fullmatch(regex, asset_name) is not None
