"""After a clone is updated: a running program only uses the new files once it's rebuilt, reinstalled or restarted,
and how is up to each project. So Update does the whole job: it downloads, then runs the clone's step
(TrackedRepo.apply_command), a command you approve the first time (or choose Only Download), run in the clone's
folder, inside the app.

- Chosen from what's certain: rebuilding the containers running from the clone's compose files, running one of its
  install, setup or update scripts, or building and installing again in its build folder. Nothing is typed in.
- Approval covers the command and the files it names (a script, a compose file): if an update changes them, the step
  isn't run until you've looked again (fingerprint). So a pulled change can't slip new commands past you (D6).
- A step that asks for a password (sudo) gets a password window: it runs with a sudo that asks through
  couriercollie's own window (sudo -A: run). If none can be shown (doas, or a sudo named by its full path), it
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
class Compose:
    """Containers running from a clone's compose files (Docker Compose or podman-compose)."""
    tool: list[str]  # ["podman-compose"], ["podman", "compose"] or ["docker", "compose"]
    project: str
    files: list[str]  # the compose files they were started with, e.g. with deploy/compose.gpu.yml
    services: list[str]  # the ones running: only these are rebuilt, so a profile that's off stays off


def parse_labels(output: str) -> list[dict[str, str]]:
    """`ps --format '{{json .Labels}}'`, one container a line: podman gives an object, docker "a=1,b=2" (a string).
    That format works on every version of both; `--format json` is only in Docker 23 and later."""
    labels = []
    for line in output.splitlines():
        try:
            found = json.loads(line)
        except ValueError:
            continue
        if isinstance(found, str):
            found = dict(pair.split("=", 1) for pair in found.split(",") if "=" in pair)
        if isinstance(found, dict):
            labels.append({str(k): str(v) for k, v in found.items()})
    return labels


def _containers(engine: str) -> list[dict[str, str]]:
    """The running containers' labels, from podman or docker. None if it can't be asked: not installed, or (docker)
    you aren't allowed to use it without sudo."""
    exe = shutil.which(engine)
    if not exe:
        return []
    try:
        out = subprocess.run([exe, "ps", "--format", "{{json .Labels}}"], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return []
    return parse_labels(out.stdout) if out.returncode == 0 else []


def _docker_compose() -> list[str]:
    """Docker's compose: the plugin (`docker compose`), or the older standalone `docker-compose`."""
    try:
        if subprocess.run(["docker", "compose", "version"], capture_output=True, timeout=15).returncode == 0:
            return ["docker", "compose"]
    except (OSError, subprocess.TimeoutExpired):
        pass
    return ["docker-compose"] if shutil.which("docker-compose") else ["docker", "compose"]


def running_compose(path: str, containers=_containers) -> Compose | None:
    """The compose project running from this folder, if any: told by the labels Compose puts on its containers."""
    folder = os.path.realpath(path)
    for engine in ("podman", "docker"):
        mine = [c for c in containers(engine)
                if os.path.realpath(c.get("com.docker.compose.project.working_dir") or "/nonexistent") == folder]
        if not mine:
            continue
        files = [f for f in mine[0].get("com.docker.compose.project.config_files", "").split(",") if f]
        services = sorted({c["com.docker.compose.service"] for c in mine if c.get("com.docker.compose.service")})
        if engine == "podman":
            tool = ["podman-compose"] if shutil.which("podman-compose") else ["podman", "compose"]
        else:
            tool = _docker_compose()
        return Compose(tool, mine[0].get("com.docker.compose.project", ""), files, services)
    return None


def compose_command(c: Compose) -> list[str]:
    """Rebuild the running services from the updated files and restart them, with the same project and files.
    --force-recreate: podman-compose keeps a container whose compose file is unchanged, even when its image was just
    rebuilt, so it would go on running the old version."""
    project = ["-p", c.project] if c.project else []
    files = [arg for f in c.files for arg in ("-f", f)]
    return [*c.tool, *project, *files, "up", "-d", "--build", "--force-recreate", *c.services]


# ---------------------------------------------------------------------------------------------------------------------
# The step


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


def suggestions(path: str, scripts: list[str], compose: Compose | None,
                built: list[Build] | None = None) -> list[Suggestion]:
    """Steps to choose from: rebuilding the running containers, each install, setup or update script, or else
    building and installing again (as the clone's build folders were set up)."""
    from .updater import _interpreter

    found = [Suggestion("Rebuild and restart its containers", shlex.join(compose_command(compose)),
                        "the container rebuild")] if compose else []
    for name in scripts:
        found.append(Suggestion(f"Run {name}", shlex.join(_interpreter(Path(path) / name, name)), name))
    if built and not scripts:  # (a project's own install script is its way: it may build more than this folder)
        found.append(Suggestion("Rebuild and install it", " && ".join(build_command(b) for b in built), "the rebuild"))
    return found


# A file bigger than this isn't read into the approval: nothing to read before running.
FILE_MAX_BYTES = 1024 * 1024


# Files a tool reads without being told their names: "make install" runs what the Makefile says, so a change to the
# Makefile is a change to the step. (A compose file given with -f is named, so it's covered anyway.)
_IMPLIED = {
    "make": ("GNUmakefile", "makefile", "Makefile"), "gmake": ("GNUmakefile", "makefile", "Makefile"),
    "compose": ("compose.yaml", "compose.yml", "docker-compose.yaml", "docker-compose.yml", "Dockerfile",
                "Containerfile"),
    "npm": ("package.json",), "pnpm": ("package.json",), "yarn": ("package.json",), "cargo": ("Cargo.toml",),
    "just": ("justfile", "Justfile"), "cmake": ("CMakeLists.txt",), "meson": ("meson.build",),
}
_IMPLIED["podman-compose"] = _IMPLIED["docker-compose"] = _IMPLIED["compose"]


def named_files(path: str, command: str) -> list[Path]:
    """The clone's files the command names (a script, a compose file), and those the tools it runs read without
    being told (make's Makefile): what approving it covers."""
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
        try:
            if file.is_relative_to(root) and file.is_file() and file.stat().st_size <= FILE_MAX_BYTES \
                    and file not in files:
                files.append(file)
        except OSError:
            continue
    return files


def fingerprint(path: str, command: str) -> str:
    """What was approved: the command, and the content of the files it names."""
    digest, root = hashlib.sha256(command.encode()), Path(path).resolve()
    for file in named_files(path, command):
        digest.update(b"\0" + str(file.relative_to(root)).encode() + b"\0" + file.read_bytes())
    return digest.hexdigest()


def review_text(path: str, command: str) -> str:
    """The command and the files it names, to read before approving it."""
    root = Path(path).resolve()
    parts = [command]
    for file in named_files(path, command):
        parts.append(f"\n# ---- {file.relative_to(root)} ----\n" + file.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(parts).rstrip() + "\n"


# What sudo (and sudo-rs), doas and pkexec say when there's no terminal (or password window) to type a password in,
# or the password window was closed without one. The step runs with English messages (run), so this matches on any
# system.
_PASSWORD = re.compile(r"terminal is required|tty is required|password is required|no tty present|askpass|"
                       r"authentication required|authentication agent", re.I)


def asked_for_password(output: list[str]) -> bool:
    return any(_PASSWORD.search(line) for line in output[-20:])


def password_window(launcher: str | Path, folder: Path) -> dict[str, str]:
    """What a step needs for sudo to ask for the password in a window: there's no terminal to type it in. sudo does
    that only when told to (-A), so the step finds a "sudo" here first that tells it, and the window is
    couriercollie's own (`couriercollie --askpass`, app.askpass). Written to `folder`, which only you can read."""
    folder.mkdir(parents=True, exist_ok=True)
    folder.chmod(0o700)
    files = {"askpass": f'#!/bin/sh\nexec {shlex.quote(str(launcher))} --askpass "$@"\n'}
    if real := shutil.which("sudo"):
        files["sudo"] = f'#!/bin/sh\nexec {shlex.quote(real)} -A "$@"\n'
    for name, text in files.items():
        (folder / name).write_text(text)
        (folder / name).chmod(0o700)
    return {"SUDO_ASKPASS": str(folder / "askpass"), "PATH": f"{folder}{os.pathsep}{os.environ.get('PATH', '')}"}


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
