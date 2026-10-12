"""After a clone is updated: a running program only uses the new files once it's restarted, rebuilt or reinstalled,
and how is up to each project. So a clone's page shows:

- the project's own update steps, quoted from its README (never followed by the app: a README is written for people,
  and a command guessed from it could do anything);
- what the app can do for certain: rebuild and restart the containers running from the clone's compose files, as they
  were started. Like an install script, it's shown first and runs in a terminal you can watch (DECISIONS.md, D6).
"""

import json
import os
import re
import shutil
import subprocess
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
    """Rebuild the running services from the updated files and restart them, with the same project and files."""
    project = ["-p", c.project] if c.project else []
    files = [arg for f in c.files for arg in ("-f", f)]
    return [*c.tool, *project, *files, "up", "-d", "--build", *c.services]
