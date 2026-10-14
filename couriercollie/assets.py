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
# One file compressed on its own (not an archive): a program, when its name says it's for Linux or a processor.
_COMPRESSED = (".gz", ".xz", ".bz2", ".zst")
# Files for other systems, or that aren't software at all.
_FOREIGN_EXT = {
    ".deb": "Debian/Ubuntu", ".exe": "Windows", ".msi": "Windows", ".msix": "Windows", ".dmg": "macOS",
    ".pkg": "macOS", ".apk": "Android", ".aab": "Android", ".ipa": "iOS",
}
# Archives beside a release's programs that hold none: eza's "completions-0.23.5.tar.gz" and "man-0.23.5.tar.gz", and
# source code or manual pages anywhere in the name (glab's "glab_1.122.0_source.tar.gz", WezTerm's "…-src.tar.gz",
# yq's "yq_man_page_only.tar.gz").
_NOT_A_PROGRAM = re.compile(r"(?:shell-)?(?:completions?|man|manpages?|docs?|vendor)(?![a-z])|"
                            r".*(?<![a-z])(?:source|src|sources|man[_-]?pages?|completions?)(?![a-z])", re.I)
_NOT_SOFTWARE = (".zsync", ".sha256", ".sha512", ".sha256sum", ".sha512sum", ".sig", ".asc", ".minisig", ".pem",
                 ".sbom", ".json", ".txt", ".md5", ".spdx", ".intoto.jsonl", ".idsig", ".cert", ".crt", ".pub")
# Whole words only, so "studios" isn't read as "iOS".
_FOREIGN_OS = re.compile(
    r"(?<![a-z])(windows|win32|win64|darwin|macos|osx|mac|android|ios|freebsd|openbsd|netbsd)(?![a-z])", re.I
)
# Windows-only even without saying so: installers ("App.Setup.1.2.zip", "app-setup-x64.zip") and screensavers (".scr").
_WINDOWS_HINT = re.compile(r"(?<![a-z])setup(?![a-z])|\.scr(?![a-z])", re.I)

_ARCH_WORDS = {
    "x86_64": ("x86_64", "x86-64", "amd64", "x64", "linux64", "64bit", "64-bit"),
    "aarch64": ("aarch64", "arm64", "arm-64", "armv8"),
}
# A bare "x86", "32-bit" or "linux32" is the 32-bit PC build (lazygit's "linux_32-bit").
_ANY_ARCH = re.compile(r"(x86_64|x86-64|amd64|x64|aarch64|arm64|arm-64|armv7|armhf|armel|armv6|arm32|i386|i586|i686|"
                       r"386|riscv64|riscv32|powerpc64le|powerpc64|powerpc|ppc64le|ppc64|ppc|s390x|loongarch64|"
                       r"loong64|mips64el|mips64|mipsel|mips|sparc64|32-bit|32bit|linux32|x86(?![_-]?64)|64-bit|64bit|"
                       r"(?<![a-z])arm(?![a-z0-9]))", re.I)
# How a processor is said in the "for … processors" note.
_ARCH_SAID = {"32-bit": "32-bit", "32bit": "32-bit", "linux32": "32-bit", "x86": "32-bit", "64bit": "64-bit PC",
              "64-bit": "64-bit PC"}


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
    build: bool = True  # a build of the software, for some system; not a checksum, signature or source package


def classify(name: str, url: str = "", machine: str | None = None) -> AssetInfo:
    """What kind of file this is and whether it suits this computer. The link's file name is used when the name is
    only a label."""
    machine = machine or platform.machine()
    info = _classify_name(name.lower(), machine)
    if info.kind == KIND_FILE and url:
        last = url.lower().split("?", 1)[0].rsplit("/", 1)[-1]
        from_url = _classify_name(last, machine)
        if from_url.kind != KIND_FILE and not _bare(last):  # a link's ".../download" is no file's name
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
        return AssetInfo(KIND_OTHER, False, "checksum or signature", build=False)
    if _NOT_A_PROGRAM.match(lower):
        return AssetInfo(KIND_OTHER, False, "documentation, completions or source", build=False)
    if lower.endswith(".src.rpm"):
        return AssetInfo(KIND_OTHER, False, "source package", build=False)
    if lower.endswith(".appimage"):
        return KIND_APPIMAGE
    if lower.endswith(_ARCHIVES):
        return KIND_PROGRAM
    if lower.endswith(_COMPRESSED) and ("linux" in lower or _ANY_ARCH.search(lower)):
        return KIND_PROGRAM  # the program itself, compressed on its own (rust-analyzer's "…-linux-gnu.gz")
    if lower.endswith(tuple(_FOREIGN_EXT)):
        return AssetInfo(KIND_OTHER, False, f"for {_FOREIGN_EXT['.' + lower.rsplit('.', 1)[-1]]}")
    if _bare(lower) and ("linux" in lower or _ANY_ARCH.search(lower)):
        return KIND_PROGRAM  # the program itself, not in an archive (installed as one: updater.install_program)
    return KIND_FILE


def _bare(lower: str) -> bool:
    """A file with no extension, as a program on its own is published: yq's "yq_linux_amd64", hugo's
    "hugo_0.120.0_linux-amd64" (the dots there are the version's)."""
    if any(c in lower for c in " ()"):
        return False  # a label ("Linux (x86_64)", on GitLab), not a file's name
    ext = lower.rsplit(".", 1)[1] if "." in lower else ""
    return not re.fullmatch(r"[a-z][a-z0-9]{0,8}", ext)


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
        return AssetInfo(kind, False, f"for {_ARCH_SAID.get(m.group(1), m.group(1))} processors")
    # No processor mentioned: usually fine for RPMs ("noarch") and AppImages with a single build. A file of unknown
    # type only counts if it says it's for Linux.
    # Unknown, or a bare program: only if it says it's for Linux ("kubectl" alone could be anyone's).
    return AssetInfo(kind, "linux" in lower if kind == KIND_FILE or (kind == KIND_PROGRAM and _bare(lower)) else True,
                     "")


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


def _numbers(version: str) -> tuple[int, ...] | None:
    """A version made of numbers only ("1.2.0", "2024.10.01") as those numbers, without trailing zeros, else None."""
    if not re.fullmatch(r"\d+(?:\.\d+)*", version):
        return None
    numbers = [int(n) for n in version.split(".")]
    while len(numbers) > 1 and numbers[-1] == 0:
        numbers.pop()
    return tuple(numbers)


def same_version(a: str, b: str) -> bool:
    """Whether two versions are the same: "v1.2.3" and "1.2.3" are, and so are "1.2" and "1.2.0" (a package's
    version and the project's tag often differ like that). Tags without a number ("nightly", "stable") are only the
    same as themselves."""
    # A package may say "-" another way: RPM versions can't have it ("20240203_110809" for the tag "20240203-110809").
    va, vb = (re.sub(r"[-_~]", ".", version_of(v)) for v in (a, b))
    if a == b or (va and va == vb):
        return True
    return _numbers(va) is not None and _numbers(va) == _numbers(vb)


def is_newer(a: str, b: str) -> bool:
    """Whether version a is newer than b. Only told for versions made of numbers ("1.2.10" is newer than "1.2.9"),
    or numbers then a test version's word ("2.0.0-rc1" is newer than "1.0.0", and older than "2.0.0"); others (dates
    with words, commits, "nightly") aren't ordered, so this says no."""
    def numbers(v):  # "v1.2", "release-1.2", "1.2": yes; "abc1234" (a commit) isn't a version
        m = re.match(r"(?:[^\d]*[-_. ])?[vV]?(\d[\d.\-_~]*?)(?:[-_.~]?((?:rc|beta|alpha|pre|preview|dev)[-_.]?\d*|[ab]\d+))?$",
                     v, re.I)
        n = _numbers(re.sub(r"[-_~]", ".", m.group(1).rstrip("-_.~"))) if m else None
        return None if n is None else (n, not m.group(2))  # (a test version comes before its release)

    na, nb = numbers(a), numbers(b)
    if na is None or nb is None:
        return False
    if na[0] != nb[0]:
        return na[0] > nb[0]
    return na[1] and not nb[1]  # (two test versions of one release: not ordered)


# What "*" in a pattern matches: a version number. Starts with a digit; may contain dashes only before another
# number or a pre-release word, so "1.2.0", "2024-01-05" and "2.0-rc1" match, but "CLI-1.2" or "1.2-debuginfo" don't.
_VERSION = r"\d[0-9A-Za-z.+~_]*(?:-(?:\d|rc|beta|alpha|pre)[0-9A-Za-z.+~_]*)*"


def pattern_for(asset_name: str, tag: str) -> str:
    """The pattern that finds this same file in later releases: the name with its version replaced by "*"."""
    version = version_of(tag)
    # As the file may write it: a package can't always use "-" (WezTerm's RPM: "20240203_110809" for "20240203-110809").
    forms = (version, version.replace("-", "_"), version.replace("-", "~"), version.replace("-", "."))
    written = next((v for v in forms if v and v in asset_name), "")
    if not written:
        return asset_name
    pattern = asset_name.replace(written, "*")
    # An RPM's name also carries the packager's release and distro ("app-1.2-1.fc44.x86_64.rpm"), which change
    # between releases (2.fc45): that part is matched as freely as the version.
    # Its distro is kept by name, so a release that also has others' builds (WezTerm: fedora37, fedora38, fedora39,
    # centos9) still finds yours; only its number may change (pick, below, takes the newest).
    if pattern.endswith(".rpm"):
        pattern = re.sub(r"^(.*\*-)\d[\d.]*?(?:\.([A-Za-z]+)\d+(?:_\d+)?)?(\.[A-Za-z0-9_]+\.rpm)$",
                         lambda m: f"{m[1]}*" + (f".{m[2]}*" if m[2] else "") + m[3], pattern)
    # A Debian or Arch package's carries the packager's revision ("tool_1.2-1_amd64.deb", "tool-1.2-1-x86_64.pkg
    # .tar.zst"), which can change too ("-2"): the "*" takes it in, as a version may end in "-<number>".
    elif pattern.endswith(".deb") or ".pkg.tar." in pattern:
        pattern = re.sub(r"\*-\d+(?=[_-])", "*", pattern, count=1)
    return pattern


def pick(pattern: str, names: list[str]) -> str | None:
    """The file a pattern finds among a release's: if several match (an RPM for fedora37 and for fedora39), the one
    with the highest numbers: the newest build."""
    found = [n for n in names if matches(pattern, n)]
    numbers = lambda name: [int(part) for part in re.findall(r"\d+", name)]  # noqa: E731
    return max(found, key=numbers) if found else None


def matches(pattern: str, asset_name: str) -> bool:
    if not pattern:
        return False
    regex = _VERSION.join(re.escape(part) for part in pattern.split("*"))
    return re.fullmatch(regex, asset_name) is not None
