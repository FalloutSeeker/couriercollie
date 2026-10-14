"""After a clone is updated: a running program only uses the new files once it's rebuilt, reinstalled or restarted,
and how is up to each project. So Update does the whole job: it downloads, then runs the clone's step
(TrackedRepo.apply_command), a command you approve the first time (or choose Only Download), run in the clone's
folder, inside the app.

- Chosen from what's certain: running one of the clone's install, setup or update scripts, or building and
  installing again in its build folder. Nothing is typed in.
- Approval covers the command and the files it names (a script): if an update changes them, the step
  isn't run until you've looked again (fingerprint). So a pulled change can't slip new commands past you (D6).
- A step that asks for a password (sudo) gets the desktop's own password window (password_window): couriercollie
  never sees the password. If there's no such window (or the step uses doas, or a sudo named by its full path), it
  stops, and can be run in a terminal instead.
"""

import hashlib
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Suggestion:
    label: str  # on its button: "Run install.sh"
    command: str
    what: str  # in a sentence: "Running install.sh…", "install.sh finished"


@dataclass
class Build:
    """A build folder in the clone, set up by an earlier build (CMake or Meson): it knows how the project was built
    and where it installs to, so rebuilding and installing it again guesses nothing."""
    tool: str  # "cmake" or "meson"
    folder: str  # in the clone, e.g. "build"
    prefix: str  # where it installs to, e.g. "/usr"


def builds(path: str) -> list[Build]:
    """The clone's build folders (directly in it): CMake's (a CMakeCache.txt for this very clone) and Meson's."""
    found = []
    root = Path(path).resolve()
    try:
        folders = sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith("."))
    except OSError:
        return []
    for folder in folders:
        cache, meson = folder / "CMakeCache.txt", folder / "meson-info" / "intro-buildoptions.json"
        if cache.is_file():
            text = cache.read_text(errors="replace")
            home = re.search(r"^CMAKE_HOME_DIRECTORY:INTERNAL=(.*)$", text, re.M)
            prefix = re.search(r"^CMAKE_INSTALL_PREFIX:PATH=(.*)$", text, re.M)
            if home and Path(home.group(1)).resolve() == root:  # (not a build of another project kept here)
                found.append(Build("cmake", folder.name, prefix.group(1) if prefix else "/usr/local"))
        elif meson.is_file():
            try:
                options = json.loads(meson.read_text())
            except ValueError:
                continue
            prefix = next((o.get("value") for o in options if o.get("name") == "prefix"), "/usr/local")
            found.append(Build("meson", folder.name, str(prefix)))
    return found


def build_command(b: Build) -> str:
    """Build again in the same folder, then install as it was set up to: with sudo where only root can write."""
    sudo = "" if os.access(b.prefix, os.W_OK) else "sudo "
    folder = shlex.quote(b.folder)
    if b.tool == "cmake":
        return f"cmake --build {folder} && {sudo}cmake --install {folder}"
    return f"meson compile -C {folder} && {sudo}meson install -C {folder}"


def scripts_name(path: str, addresses: list[str]) -> bool:
    """Whether the clone's install scripts name one of these projects (as "gitgud.io/aeroshell/smod"): it sets that
    project up as part of itself."""
    from .updater import install_scripts

    for name in install_scripts(path):
        try:
            text = (Path(path) / name).read_text(errors="replace").lower()
        except OSError:
            continue
        if any(address.lower() in text for address in addresses):
            return True
    return False


def suggestions(path: str, scripts: list[str], built: list[Build] | None = None) -> list[Suggestion]:
    """Steps to choose from: each install, setup or update script, or else building and installing again (as the
    clone's build folders were set up)."""
    from .updater import _interpreter

    found = []
    for name in scripts:
        found.append(Suggestion(f"Run {name}", shlex.join(_interpreter(Path(path) / name, name)), name))
    if built and not scripts:  # (a project's own install script is its way: it may build more than this folder)
        found.append(Suggestion("Rebuild and install it", " && ".join(build_command(b) for b in built), "the rebuild"))
    return found


# A file bigger than this isn't read into the approval: nothing to read before running.
FILE_MAX_BYTES = 1024 * 1024


# Files a tool reads without being told their names: "make install" runs what the Makefile says, so a change to the
# Makefile is a change to the step.
_IMPLIED = {
    "make": ("GNUmakefile", "makefile", "Makefile"), "gmake": ("GNUmakefile", "makefile", "Makefile"),
    "npm": ("package.json",), "pnpm": ("package.json",), "yarn": ("package.json",), "cargo": ("Cargo.toml",),
    "just": ("justfile", "Justfile"), "cmake": ("CMakeLists.txt",), "meson": ("meson.build",),
}


# A word in a script that may name another file it runs: "lib/common.sh", "./install-services.sh", or
# "$SCRIPT_DIR/install-services.sh" (each tail of it is tried: "install-services.sh").
_PATH_WORD = re.compile(r"[\w.+-]*(?:/[\w.+-]+)+|[\w.+-]+\.(?:sh|bash|zsh|py|pl|rb)\b")
_SCRIPT_SUFFIXES = (".sh", ".bash", ".zsh", ".py", ".pl", ".rb")
NAMED_MAX = 200  # files followed from one step, at most
ENDING_MAX = 3  # files found by how a name ends, at most, for one name


def _is_script(file: Path) -> bool:
    if file.suffix in _SCRIPT_SUFFIXES:
        return True
    try:
        with file.open("rb") as f:
            return f.read(2) == b"#!"
    except OSError:
        return False


def _usable(file: Path, root: Path) -> bool:
    try:
        return file.is_relative_to(root) and file.is_file() and file.stat().st_size <= FILE_MAX_BYTES
    except OSError:
        return False


def _tracked(root: Path) -> list[str]:
    """The clone's files, as git tracks them (relative paths)."""
    try:
        out = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [p for p in out.stdout.decode(errors="replace").split("\0") if p] if out.returncode == 0 else []


def _scripts_it_runs(file: Path, root: Path, tracked: list[str]) -> tuple[list[Path], list[Path]]:
    """The clone's other scripts this file names: those it runs or sources (and whatever else it names that's a
    script: following too many costs only a question too many, after an update that changes one). Returns those
    named outright, then those found by how a name behind a variable ends ("$DIR/lib/common.sh"): among the clone's
    files, inside this script's own folder first; never more than a few (a name that ends like many vendored files
    says nothing about which)."""
    try:
        text = file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return [], []
    named, ending = [], []
    near = str(file.parent.relative_to(root)) if file.parent != root else ""
    for word in sorted(set(_PATH_WORD.findall(text))):
        parts = word.split("/")
        tails = [t for i in range(len(parts)) if (t := "/".join(parts[i:]))]
        here = next((c for t in tails for b in (file.parent, root)
                     if _usable(c := (b / t).resolve(), root) and _is_script(c)), None)
        if here:
            named.append(here)
            continue
        for tail in tails:  # the longest ending that names any of the clone's files
            ends = [t for t in tracked if t == tail or t.endswith("/" + tail)]
            if not ends:
                continue
            inside = [t for t in ends if near and t.startswith(near + "/")]
            chosen = inside if inside and len(inside) <= ENDING_MAX else ends if len(ends) <= ENDING_MAX else []
            ending.extend(c for t in chosen if _usable(c := (root / t).resolve(), root) and _is_script(c))
            break
    return named, ending


def named_files(path: str, command: str) -> list[Path]:
    """What approving the command covers: the clone's files it names (a script), those the tools it runs read
    without being told (make's Makefile), and the scripts those run or source in turn. A change to any of them is
    shown before the step runs again."""
    try:
        words = shlex.split(command)
    except ValueError:
        return []
    root, files = Path(path).resolve(), []
    implied = [name for word in words for name in _IMPLIED.get(Path(word).name, ())]
    for word in [*words, *implied]:
        if word.startswith("-"):
            continue
        file = (root / word).resolve()
        if _usable(file, root) and file not in files:
            files.append(file)
    tracked, later = _tracked(root), []
    for file in files:  # (grows as it goes: what those run, in turn)
        named, ending = _scripts_it_runs(file, root, tracked)
        files.extend(f for f in dict.fromkeys(named) if f not in files and len(files) < NAMED_MAX)
        later.extend(ending)
        if file is files[-1]:  # named outright: all followed; now those found by how they end, and what they run
            files.extend(f for f in dict.fromkeys(later) if f not in files and len(files) < NAMED_MAX)
            later = []
    return files


def fingerprint(path: str, command: str) -> str:
    """What was approved: the command, and the content of the files it names."""
    digest, root = hashlib.sha256(command.encode()), Path(path).resolve()
    for file in named_files(path, command):
        try:
            content = file.read_bytes()
        except OSError:
            content = b"\0unreadable"  # (so it becoming readable again is a change too)
        digest.update(b"\0" + str(file.relative_to(root)).encode() + b"\0" + content)
    return digest.hexdigest()


def review_text(path: str, command: str) -> str:
    """The command and the files it names, to read before approving it."""
    root = Path(path).resolve()
    parts = [command]
    for file in named_files(path, command):
        try:
            text = file.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            text = f"# (couldn\u2019t be read: {e.strerror or e})\n"
        parts.append(f"\n# ---- {file.relative_to(root)} ----\n" + text)
    return "\n".join(parts).rstrip() + "\n"


# What sudo (and sudo-rs), doas and pkexec say when there's no terminal (or password window) to type a password in,
# or the password window was closed without one. The step runs with English messages (run), so this matches on any
# system.
_PASSWORD = re.compile(r"terminal is required|tty is required|password is required|no tty present|askpass|"
                       r"authentication required|authentication agent", re.I)


def asked_for_password(output: list[str]) -> bool:
    return any(_PASSWORD.search(line) for line in output[-20:])


# The desktop's own password windows, as sudo can use them (sudo -A): KDE's, GNOME's, and others'. The desktop says
# which is its own ($SSH_ASKPASS: Plasma sets it), else the first of these that's installed.
ASKPASS = ("/usr/bin/ksshaskpass", "/usr/libexec/openssh/gnome-ssh-askpass", "/usr/lib/openssh/gnome-ssh-askpass",
           "/usr/libexec/seahorse/ssh-askpass", "/usr/lib/seahorse/ssh-askpass", "/usr/bin/lxqt-openssh-askpass",
           "/usr/bin/ssh-askpass", "/usr/lib/ssh/ssh-askpass", "/usr/libexec/openssh/ssh-askpass")


def desktop_askpass() -> str:
    """The desktop's own password window for sudo, or "" if there's none."""
    for path in (os.environ.get("SUDO_ASKPASS", ""), os.environ.get("SSH_ASKPASS", ""), *ASKPASS):
        if path and os.path.isabs(path) and os.access(path, os.X_OK):
            return path
    return ""


def password_window(folder: Path) -> dict[str, str]:
    """What a step needs for sudo in it to ask for the password in the desktop's own window: there's no terminal to
    type it in. The password goes from that window straight to sudo; couriercollie never sees it. sudo only uses the
    window when told to (-A), so the step finds a "sudo" first that tells it, written to `folder` (only you can read
    it). Without such a window, nothing: sudo then stops, and the step can be run in a terminal instead."""
    if not (helper := desktop_askpass()) or not (real := shutil.which("sudo")):
        return {}
    folder.mkdir(parents=True, exist_ok=True)
    folder.chmod(0o700)
    (folder / "sudo").write_text(f'#!/bin/sh\nexec {shlex.quote(real)} -A "$@"\n')
    (folder / "sudo").chmod(0o700)
    return {"SUDO_ASKPASS": helper, "PATH": f"{folder}{os.pathsep}{os.environ.get('PATH', '')}"}


def run(path: str, command: str, line: Callable[[str], None], started: Callable[[subprocess.Popen], None],
        asking: dict[str, str] | None = None) -> int:
    """Run the step in the clone's folder, passing each line of its output on as it comes. Nothing can be typed in
    (no terminal): `asking` (password_window) lets sudo ask in a window instead; anything else that asks for a
    password fails rather than waiting. Returns its exit code."""
    # English messages: how a password prompt that failed is told (asked_for_password), on any system.
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C.UTF-8"}
    for name in ("SUDO_ASKPASS", "LANGUAGE"):
        env.pop(name, None)
    env.update(asking or {})
    process = subprocess.Popen(["/bin/sh", "-c", command], cwd=path, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace",
                               start_new_session=True, env=env)
    started(process)
    for text in process.stdout:
        line(text.rstrip("\n"))
    return process.wait()


def terminal_line(path: str, command: str) -> str:
    """The step as one line to paste into a terminal, where a password can be typed."""
    return f"cd {shlex.quote(path)} && {command}"


def stop(process: subprocess.Popen) -> None:
    """Stop the step and anything it started."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass
