"""After a clone is updated: a running program only uses the new files once it's rebuilt, reinstalled or restarted,
and how is up to each project. So each clone can have one step to run after an update (TrackedRepo.apply_command): a
command you approve once, run in the clone's folder, inside the app, after each Update.

- Suggested from what's certain: rebuilding the containers running from the clone's compose files, or running one of
  its install, setup or update scripts. The README's update steps are quoted, to help choose; never followed.
- Approval covers the command and the files it names (a script, a compose file): if an update changes them, the step
  isn't run until you've looked again (fingerprint). So a pulled change can't slip new commands past you (D6).
- A step that asks for a password can't be answered here (there's no terminal), so it stops, and can be run in a
  terminal instead.
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

README_NAMES = ("README.md", "README.markdown", "Readme.md", "readme.md", "README", "README.txt")
README_MAX_BYTES = 512 * 1024
# What's quoted: enough for a few steps, not the whole README.
STEPS_MAX_CHARS = 1500

# A heading about updating ("## Updating", "### Upgrade to 2.0"), or a paragraph that starts like one ("To update: …").
_UPDATE_WORD = re.compile(r"\b(updat(e|es|ing)|upgrad(e|es|ing))\b", re.I)
_UPDATE_START = re.compile(r"^\W*(to (update|upgrade)|updating|upgrading)\b", re.I)
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")


def _readme(path: str) -> str:
    for name in README_NAMES:
        file = Path(path) / name
        try:
            if file.is_file() and file.stat().st_size <= README_MAX_BYTES:
                return file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
    return ""


def readme_path(path: str) -> Path | None:
    return next((Path(path) / n for n in README_NAMES if (Path(path) / n).is_file()), None)


def _outside_code(lines: list[str]):
    """(index, line, whether it's inside a ``` block) for each line, so a "# comment" in code isn't a heading."""
    in_code = False
    for i, line in enumerate(lines):
        if _FENCE.match(line):
            in_code = not in_code
            yield i, line, True
        else:
            yield i, line, in_code


def _shortened(text: str) -> str:
    text = text.strip("\n")
    if len(text) <= STEPS_MAX_CHARS:
        return text
    cut = text[:STEPS_MAX_CHARS].rsplit("\n", 1)[0]
    if cut.count("```") % 2:  # don't leave a code block open
        cut += "\n```"
    return cut + "\n\n…"


def readme_steps(path: str) -> str:
    """The README's update steps, as Markdown: the section under a heading about updating, or else a paragraph that
    starts "To update". "" if it has none."""
    lines = _readme(path).splitlines()
    for i, line, in_code in _outside_code(lines):
        m = None if in_code else _HEADING.match(line)
        if m and _UPDATE_WORD.search(m.group(2)):
            level, body = len(m.group(1)), []
            for _j, rest, rest_in_code in _outside_code(lines[i + 1:]):
                if not rest_in_code and (h := _HEADING.match(rest)) and len(h.group(1)) <= level:
                    break
                body.append(rest)
            if "".join(body).strip():
                return _shortened("\n".join(body))
    paragraph: list[str] = []
    for _i, line, in_code in _outside_code([*lines, ""]):
        if line.strip() or in_code:
            paragraph.append(line)
            continue
        if paragraph and not _HEADING.match(paragraph[0]) and _UPDATE_START.match(paragraph[0]):
            return _shortened("\n".join(paragraph))
        paragraph = []
    return ""


@dataclass
class Compose:
    """Containers running from a clone's compose files (Docker Compose or podman-compose)."""
    tool: list[str]  # ["podman-compose"], ["podman", "compose"] or ["docker", "compose"]
    project: str
    files: list[str]  # the compose files they were started with, e.g. with deploy/compose.gpu.yml
    services: list[str]  # the ones running: only these are rebuilt, so a profile that's off stays off


def _containers(engine: str) -> list[dict[str, str]]:
    """The running containers' labels, from podman or docker."""
    exe = shutil.which(engine)
    if not exe:
        return []
    try:
        out = subprocess.run([exe, "ps", "--format", "json"], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return []
    if out.returncode != 0 or not out.stdout.strip():
        return []
    try:
        # podman: one JSON array; docker: one JSON object per line, its labels as "a=1,b=2".
        rows = json.loads(out.stdout) if out.stdout.lstrip().startswith("[") else \
            [json.loads(line) for line in out.stdout.splitlines() if line.strip()]
    except ValueError:
        return []
    labels = []
    for row in rows if isinstance(rows, list) else []:
        found = row.get("Labels") if isinstance(row, dict) else None
        if isinstance(found, str):
            found = dict(pair.split("=", 1) for pair in found.split(",") if "=" in pair)
        if isinstance(found, dict):
            labels.append({str(k): str(v) for k, v in found.items()})
    return labels


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
            tool = ["docker", "compose"]
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
    label: str
    command: str


def suggestions(path: str, scripts: list[str], compose: Compose | None) -> list[Suggestion]:
    """Steps to choose from: rebuilding the running containers, and each install, setup or update script."""
    from .updater import _interpreter

    found = [Suggestion("Rebuild and restart its containers", shlex.join(compose_command(compose)))] if compose else []
    for name in scripts:
        found.append(Suggestion(f"Run {name}", shlex.join(_interpreter(Path(path) / name, name))))
    return found


# A file bigger than this isn't read into the approval: nothing to read before running.
FILE_MAX_BYTES = 1024 * 1024


def named_files(path: str, command: str) -> list[Path]:
    """The clone's files the command names (a script, a compose file): what approving it covers."""
    try:
        words = shlex.split(command)
    except ValueError:
        return []
    root, files = Path(path).resolve(), []
    for word in words:
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


# What sudo and friends say when there's no terminal to type a password in.
_PASSWORD = re.compile(r"terminal is required|password is required|no tty present|askpass", re.I)


def asked_for_password(output: list[str]) -> bool:
    return any(_PASSWORD.search(line) for line in output[-20:])


def run(path: str, command: str, line: Callable[[str], None], started: Callable[[subprocess.Popen], None]) -> int:
    """Run the step in the clone's folder, passing each line of its output on as it comes. Nothing can be typed in
    (no terminal): a password prompt fails instead of waiting. Returns its exit code."""
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    env.pop("SUDO_ASKPASS", None)
    process = subprocess.Popen(["/bin/sh", "-c", command], cwd=path, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace",
                               start_new_session=True, env=env)
    started(process)
    for text in process.stdout:
        line(text.rstrip("\n"))
    return process.wait()


def stop(process: subprocess.Popen) -> None:
    """Stop the step and anything it started."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass
