"""Packages for the system's package manager, from a project's releases: RPMs (dnf on Fedora, zypper on openSUSE),
Debian packages (apt) and Arch packages (pacman). Which tool installs each kind, reading a package file's name,
version and processor type, and what's installed now. Installing itself is in updater.install_package.
"""

import platform
import re
import subprocess
from pathlib import Path

from . import assets

# How a package is named where a repo's place would be a folder: 'RPM package “bottom”'.
LABELS = {assets.KIND_RPM: "RPM package", assets.KIND_DEB: "Debian package", assets.KIND_ARCH: "Arch package"}
# The same in a sentence: "an RPM package".
A_LABEL = {kind: ("an " if label[0] in "AR" else "a ") + label for kind, label in LABELS.items()}
_PLACE = re.compile(r"(RPM|Debian|Arch) package “(.+)”")

# The command that installs a package file (given after it), run as root, by full path.
INSTALL = {
    "dnf": ["/usr/bin/dnf", "install", "-y"],
    # A file from a project's release isn't signed with a key zypper knows.
    "zypper": ["/usr/bin/zypper", "--non-interactive", "install", "--allow-unsigned-rpm"],
    "apt": ["/usr/bin/apt-get", "install", "-y"],
    "pacman": ["/usr/bin/pacman", "-U", "--noconfirm"],
}
# What each kind of file starts with: an RPM's lead, a Debian package's "ar" archive, an Arch package's zstd or xz.
MAGIC = {assets.KIND_RPM: (b"\xed\xab\xee\xdb",), assets.KIND_DEB: (b"!<arch>\n",),
         assets.KIND_ARCH: (b"\x28\xb5\x2f\xfd", b"\xfd7zXZ\x00")}
# Processor names as each kind writes them, as this computer's (platform.machine()) are.
_ARCH_NAMES = {"amd64": "x86_64", "arm64": "aarch64", "armhf": "armv7l", "i386": "i686", "ppc64el": "ppc64le",
               "all": "noarch", "any": "noarch"}


def place(kind: str, name: str) -> str:
    return f"{LABELS[kind]} “{name}”"


def from_place(local_path: str) -> tuple[str, str] | None:
    """(kind, package name) for a repo whose place is a package, else None."""
    if m := _PLACE.fullmatch(local_path):
        return {"RPM": assets.KIND_RPM, "Debian": assets.KIND_DEB, "Arch": assets.KIND_ARCH}[m.group(1)], m.group(2)
    return None


def tool_for(kind: str) -> str:
    """The package manager here that installs this kind of file ("dnf", …), or "" if there's none."""
    order = {assets.KIND_RPM: ("dnf", "zypper"), assets.KIND_DEB: ("apt",), assets.KIND_ARCH: ("pacman",)}
    return next((t for t in order.get(kind, ()) if assets.has(t)), "")


def upstream_version(version: str) -> str:
    """The project's version in a package's: without an epoch ("1:") or the packager's revision ("-1ubuntu2")."""
    version = version.split(":", 1)[-1]
    return version.rsplit("-", 1)[0] if "-" in version else version


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(list(args), capture_output=True, text=True, timeout=30)


def file_info(kind: str, path: Path) -> tuple[str, str, str]:
    """(name, version, processor) of a package file, read without installing it. The processor as this computer
    calls it ("x86_64"), or "noarch". Raises ValueError if it can't be read."""
    try:
        if kind == assets.KIND_RPM:
            out = _run("rpm", "-qp", "--qf", "%{NAME}|%{VERSION}|%{ARCH}", str(path))
            fields = out.stdout.split("|") if out.returncode == 0 else []
        elif kind == assets.KIND_DEB:
            out = _run("dpkg-deb", "--show", "--showformat=${Package}|${Version}|${Architecture}", str(path))
            fields = out.stdout.split("|") if out.returncode == 0 else []
        else:
            out = _run("pacman", "-Qip", str(path))  # "Name            : bottom", one per line
            info = {k.strip(): v.strip() for k, _, v in (line.partition(":") for line in out.stdout.splitlines())}
            fields = [info.get("Name", ""), info.get("Version", ""), info.get("Architecture", "")] \
                if out.returncode == 0 else []
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ValueError(f"Couldn’t read the package: {e}") from e
    if len(fields) != 3 or not all(f.strip() for f in fields):
        raise ValueError("The download isn’t a package that can be read, so it wasn’t installed.")
    name, version, arch = (f.strip() for f in fields)
    return name, upstream_version(version), _ARCH_NAMES.get(arch, arch)


def suits(arch: str) -> bool:
    return arch in (platform.machine(), "noarch")


def installed_version(kind: str, name: str) -> tuple[str, bool]:
    """(the installed version, whether it's installed). ("", True) if it can't be told."""
    try:
        if kind == assets.KIND_RPM:
            out = _run("rpm", "-q", "--qf", "%{VERSION}", name)
        elif kind == assets.KIND_DEB:
            out = _run("dpkg-query", "--show", "--showformat=${Version}|${db:Status-Status}", name)
            if out.returncode == 0:
                version, _, status = out.stdout.partition("|")
                return (upstream_version(version), True) if status == "installed" else ("", False)
        else:
            out = _run("pacman", "-Q", name)
            if out.returncode == 0:
                return upstream_version(out.stdout.split()[-1]), True
    except (OSError, subprocess.TimeoutExpired):
        return "", True
    return (out.stdout.strip(), True) if out.returncode == 0 else ("", False)


def files_of(kind: str, name: str) -> list[str]:
    """The files an installed package put on this computer (for its menu entry's icon)."""
    command = {assets.KIND_RPM: ["rpm", "-ql"], assets.KIND_DEB: ["dpkg", "-L"],
               assets.KIND_ARCH: ["pacman", "-Qlq"]}[kind]
    try:
        out = _run(*command, name)
    except (OSError, subprocess.TimeoutExpired):
        return []
    return out.stdout.splitlines() if out.returncode == 0 else []


# ---------------------------------------------------------------------------------------------------------------------
# Software the package manager already keeps up to date

# How each package manager is told to update everything, as said to you.
UPGRADE = {"dnf": "dnf upgrade", "zypper": "zypper update", "apt": "apt upgrade", "pacman": "pacman -Syu"}


def _out(*args: str) -> str:
    try:
        result = _run(*args)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout if result.returncode == 0 else ""


def installed_homepages(run=_out) -> list[tuple[str, str]]:
    """(package name, homepage) of every installed package, from this computer's package manager."""
    if has_rpm := assets.has("dnf") or assets.has("zypper"):
        lines = run("rpm", "-qa", "--qf", "%{NAME}|%{URL}\\n")
    elif assets.has("apt"):
        lines = run("dpkg-query", "--show", "--showformat=${Package}|${Homepage}\\n")
    elif assets.has("pacman"):
        # "Name : x" … "URL : y" blocks, one per package.
        pairs, name = [], ""
        for line in run("pacman", "-Qi").splitlines():
            key, _, value = line.partition(":")
            if key.strip() == "Name":
                name = value.strip()
            elif key.strip() == "URL" and name:
                pairs.append(f"{name}|{value.strip()}")
        lines = "\n".join(pairs)
    else:
        return []
    return [tuple(line.split("|", 1)) for line in lines.splitlines() if line.count("|") == 1]


def offered_by_a_repository(name: str, run=_out) -> bool:
    """Whether a repository you have enabled offers this package, so the package manager updates it."""
    if assets.has("dnf"):
        return bool(run("dnf", "repoquery", "--available", "--qf", "%{name}\\n", name).strip())
    if assets.has("zypper"):
        found = run("zypper", "--quiet", "--xmlout", "search", "--match-exact", "--details", "--type", "package", name)
        return bool(re.search(r'repository="(?!\(System Packages\))[^"]+"', found))
    if assets.has("apt"):
        listed = run("apt", "list", "--installed", name)
        return any(line.startswith(f"{name}/") and not line.rstrip().endswith(",local]") for line in listed.splitlines())
    if assets.has("pacman"):
        return bool(run("pacman", "-Si", name))
    return False


def managed_by_system(repo_ids: list[str], run=_out) -> tuple[str, str] | None:
    """(package manager, package) if the project behind these addresses is installed as a package that a repository
    you have enabled offers: the package manager keeps it up to date. Matched by the package's homepage, never by a
    similar name."""
    from . import sources

    wanted = {i.lower() for i in repo_ids}
    for name, homepage in installed_homepages(run):
        try:
            if sources.parse_url(homepage).id.lower() not in wanted:
                continue
        except ValueError:
            continue
        if offered_by_a_repository(name, run):
            tool = next((t for t in ("dnf", "zypper", "apt", "pacman") if assets.has(t)), "")
            return tool, name
    return None
