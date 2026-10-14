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


# ---- The README's install or update steps, shown beside the step (only to read: never run) -------------------------

README_NAMES = ("README.md", "README.markdown", "Readme.md", "readme.md", "README.MD", "README", "README.txt",
                "README.rst", "docs/README.md")
README_MAX_BYTES = 512 * 1024
SECTION_MAX_CHARS = 2500  # enough for a few steps, not the whole README
# What a heading is about (see _rank): whole words, not in a hyphenated one ("Post-update hooks", "RetroPie-Setup").
_UPDATE = re.compile(r"(?<![\w-])(updat(e|es|ing)|upgrad(e|es|ing))(?![\w-])", re.I)
_INSTALL = re.compile(r"(?<![\w-])(install(ation|ing|s)?|set ?up|setting up|build(ing)?|compil(e|ing|ation))(?![\w-])",
                      re.I)
_STARTED = re.compile(r"(?<![\w-])(getting started|quick ?start)(?![\w-])", re.I)
_USAGE = re.compile(r"(?<![\w-])(usage|how to use|download(ing)?)(?![\w-])", re.I)
_USAGE_STEPS = re.compile(r"\b(clone|copy|cp|install|download|extract|unzip|symlink|move|mv)\b", re.I)  # in its text
# Doing it from the clone ("From source", "Basic Git Checkout", "Install a checkout from git"; "Manual installation").
_FROM_SOURCE = re.compile(r"\b(from (the )?(source|git)|git (clone|checkout)|(using|with|via) \W?git)\b", re.I)
_BY_HAND = re.compile(rf"{_FROM_SOURCE.pattern}|\bmanual(ly)?\b", re.I)
# What it needs ("Install Dependencies", or "Building" under "Requirements"): a list of packages, not the steps.
_NEEDS = re.compile(r"^\W*(\w+\W+){0,3}(dependenc(y|ies)|deps|requirements?|prerequisites?)\W*$", re.I)
# An "update" heading that isn't the steps: news, notes, a changelog, a migration from an old version.
_NOT_STEPS = re.compile(r"\b(notes?|news|changelog|log|history|schedule[ds]?|management|hooks?|requests?|policy|"
                        r"what'?s new|migrat\w*|from v?\d|credits?)\b", re.I)
_NAME_WORD = re.compile(r"[a-z0-9]{3,}")  # a word of the project's name ("powerlevel10k")
# What isn't the README's words: pictures and badges ("![…](…)", "<img …>"), HTML tags and comments; a link keeps its
# words ("[Manual Install](#manual-install)" is "Manual Install").
_TARGET = r"(\([^)]*\)|\[[^\]]*\])"  # a link's address: "(https://…)", or "[name]" defined elsewhere
_PICTURE = re.compile(rf"\[?!\[[^\]]*\]{_TARGET}(\]{_TARGET})?|<img\b[^>]*>", re.I)
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_TAG = re.compile(r"</?[a-z][^>]*>", re.I)
_LINK = re.compile(rf"\[([^\]]*)\]{_TARGET}")
# A paragraph that starts like one ("To update: …", "To install it, …").
_STARTS = re.compile(r"^\W*(to (update|upgrade|install)|updating|upgrading|installing)\b", re.I)
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_UNDERLINE = re.compile(r"^\s*(=+|-+)\s*$")  # a heading written as a line underlined with === or ---
_RST_UNDERLINE = re.compile(r"^([=\-~^*#\"'`+:._])\1{2,}\s*$")  # in reStructuredText, any of these
_FENCE = re.compile(r"^\s*(```|~~~)")


def _readme(path: str) -> tuple[str, str]:
    """(its name, its text). Only the clone's own: a README that's a link to a file outside it isn't read."""
    root = Path(path).resolve()
    for name in README_NAMES:
        file = (root / name).resolve()
        try:
            if file.is_relative_to(root) and file.is_file() and file.stat().st_size <= README_MAX_BYTES:
                return name, file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
    return "", ""


def _headings(lines: list[str], kind: str = ".md") -> list[tuple[int, int, str]]:
    """(line index, level, text) of each heading, outside code blocks: "## Install", or "Install" underlined. In
    reStructuredText (kind ".rst") a line underlined with any punctuation, the levels in the order the underlines
    first appear."""
    if kind == ".rst":
        found, order = [], []
        for i, line in enumerate(lines):
            if i and _RST_UNDERLINE.match(line) and lines[i - 1].strip() and not _RST_UNDERLINE.match(lines[i - 1]):
                if line[0] not in order:
                    order.append(line[0])
                found.append((i - 1, order.index(line[0]) + 1, lines[i - 1].strip()))
        return found
    found, in_code = [], False
    for i, line in enumerate(lines):
        if _FENCE.match(line):
            in_code = not in_code
        elif in_code:
            continue
        elif m := _HEADING.match(line):
            found.append((i, len(m.group(1)), m.group(2)))
        elif i and _UNDERLINE.match(line) and lines[i - 1].strip() and not _FENCE.match(lines[i - 1]) \
                and not (found and found[-1][0] == i - 1):
            found.append((i - 1, 1 if line.strip()[0] == "=" else 2, lines[i - 1].strip()))
    return found


def _shortened(text: str) -> str:
    text = text.strip("\n")
    if len(text) <= SECTION_MAX_CHARS:
        return text
    cut = text[:SECTION_MAX_CHARS].rsplit("\n", 1)[0]
    if sum(1 for line in cut.splitlines() if _FENCE.match(line)) % 2:  # don't leave a code block open
        cut += "\n```"
    return cut + "\n\n…"


def _words(title: str) -> str:
    """A heading as words: without its badges, pictures, tags, and links' addresses."""
    return " ".join(_LINK.sub(r"\1", _TAG.sub("", _PICTURE.sub("", title))).split())


def _cleaned(text: str) -> str:
    """A section without its badges, pictures and HTML comments (clutter, and pictures from anywhere)."""
    text = _PICTURE.sub("", _COMMENT.sub("", text))
    return "\n".join(line for line in text.splitlines() if line.strip() not in ("[]", "()")) if text else ""


def _rank(title: str, parent: str) -> int | None:
    """What a heading is about, the steps likeliest first: 0 updating (not news of it), 1 installing or building, 2
    "From source" alone, 3 getting started, 4 usage (themes put their steps there), 5 what installing needs; None if
    none of these."""
    if _UPDATE.search(title) and not _NOT_STEPS.search(title):
        return 0
    if _NEEDS.search(title) or _NEEDS.search(parent):
        return 5 if _INSTALL.search(title) or _FROM_SOURCE.search(title) else None
    if _INSTALL.search(title):
        return 1
    if _FROM_SOURCE.search(title):
        return 2
    if _STARTED.search(title):
        return 3
    return 4 if _USAGE.search(title) else None


def _section(text: str, kind: str = ".md", project: str = "") -> tuple[str, str]:
    """In a text (Markdown, else as kind says), the steps for updating (else installing or building): (heading,
    section). The first heading of the likeliest kind (_rank), but rather one about doing it from the clone; else a
    paragraph that starts "To install…". project: the clone's name, when it's the README."""
    lines = text.splitlines()
    headings = [(i, level, _words(title)) for i, level, title in _headings(lines, kind)]
    if project and len(headings) > 1 and headings[0][1] == 1 and all(lv > 1 for _i, lv, _t in headings[1:]):
        headings[0] = (headings[0][0], 1, "")  # the README's title ("Luke's build of dwm"), everything under it
    biggest = min((lv for _i, lv, t in headings if _INSTALL.search(t)), default=9)  # of the install headings
    names = set(_NAME_WORD.findall(project.lower()))
    found = []
    for n, (i, level, title) in enumerate(headings):
        parent = next((t for _j, lv, t in reversed(headings[:n]) if lv < level), "")
        if (rank := _rank(title, parent)) is None:
            continue
        # In the README, an update heading under a bigger install heading is about updating something else ("Updating
        # plugins"): unless it's just "Upgrading", names the project, or is part of an update section.
        if rank == 0 and project and level > biggest and len(title.split()) > 1 and not _UPDATE.search(parent) \
                and not names & set(_NAME_WORD.findall(title.lower())):
            continue
        end = next((j for j, lv, _t in headings[n + 1:] if lv <= level), len(lines))
        body = lines[i + 1:end]
        if body and (_UNDERLINE.match(body[0]) or _RST_UNDERLINE.match(body[0])):  # (an underlined heading's own line)
            body = body[1:]
        if (text := _cleaned("\n".join(body))).strip() and (rank != 4 or _USAGE_STEPS.search(text)):
            found.append((rank, i, end, title, text))
    if found:
        rank, start, end, title, text = min(found)
        # Rather one as likely about doing it from the clone ("Install from source", "Manual upgrade"), unless it's
        # part of this section (shown with it). If this one is too long to show (a wall of distro packages), its part
        # about that, or a "From source" heading.
        fits = len(text) <= SECTION_MAX_CHARS
        title, text = next(((t, x) for r, i, _e, t, x in found if _BY_HAND.search(t)
                            and (r == rank or ((rank, r) == (1, 2) and not fits)) and not (fits and start < i < end)),
                           (title, text))
        return title, _shortened(text)
    paragraphs: list[str] = []
    paragraph: list[str] = []
    in_code = False
    for line in [*lines, ""]:
        if _FENCE.match(line):
            in_code = not in_code
        if line.strip() or in_code:
            paragraph.append(line)
        elif paragraph:
            paragraphs.append("\n".join(paragraph))
            paragraph = []
    for k, paragraph in enumerate(paragraphs):
        if _STARTS.match(paragraph):
            if paragraph.rstrip().endswith(":") and k + 1 < len(paragraphs):  # "To install, run:", and what to run
                paragraph += "\n\n" + paragraphs[k + 1]
            return "", _shortened(_cleaned(paragraph))
    return "", ""


# A link to another text file in the clone ("See [INSTALL.md](./INSTALL.md)"): not to a website.
_LOCAL_DOC = re.compile(r"\]\((?!\w+:)(?:\./)?([^)\s#]+\.(?:md|markdown|txt))(?:#[^)]*)?\)", re.I)
_DOCS = ("UPDATING.md", "UPGRADING.md", "INSTALL.md", "INSTALLING.md", "INSTALLATION.md", "BUILDING.md",
         "docs/INSTALL.md", "docs/install.md", "doc/INSTALL.md", "INSTALL.rst", "INSTALL")
POINTER_MAX_CHARS = 400  # a section this short that links elsewhere only points there
_DOC_NAME = re.compile(r"install|build|setup|updat|upgrad", re.I)  # a file named for the steps ("INSTALL.md")


def readme_section(path: str) -> tuple[str, str]:
    """The README's own steps for updating (else for installing or building): (its heading, the section as Markdown).
    A heading about it, with everything under it up to the next heading as big; else a paragraph that starts "To
    update" or "To install". A README that only points elsewhere ("See INSTALL.md", also before the section's own
    parts) is followed there, and one without any such steps (or only a link to a website) is looked for in
    INSTALL.md and the like: one whose headings don't say shows from its beginning. ("", "") if there are none."""
    root = Path(path).resolve()
    readme, text = _readme(path)
    title, body = _section(text, Path(readme).suffix.lower(), root.name)
    linked = list(dict.fromkeys(_LOCAL_DOC.findall(body)))
    if len(body) > POINTER_MAX_CHARS:  # the steps, unless it starts by pointing to their file, then has its parts
        parts = _headings(body.splitlines())
        lead = "\n".join(body.splitlines()[:parts[0][0]]) if parts else body
        linked = [name for name in _LOCAL_DOC.findall(lead) if _DOC_NAME.search(name)]
        if len(lead) > POINTER_MAX_CHARS or not linked:
            return title, body
    elif not linked and "`" not in body:  # none, or no steps of its own ("See https://…")
        linked = list(_DOCS)
    for name in linked:
        file = (root / name).resolve()
        try:
            if not file.is_relative_to(root) or not file.is_file() or file.stat().st_size > README_MAX_BYTES:
                continue
            text = file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        there, steps = _section(text, file.suffix.lower())
        if steps:
            return " · ".join(t for t in (file.relative_to(root).as_posix(), there) if t), steps
        if text.strip() and not text.startswith("#!"):  # linked from the README or named for it (not a script),
            # though no heading says what it is: its beginning
            return file.relative_to(root).as_posix(), _shortened(_cleaned(text))
    return title, body


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
