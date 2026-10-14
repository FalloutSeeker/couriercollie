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
# (Each within a line, and of a bounded length: a README written to make them slow can't.)
_TARGET = r"(\([^)\n]{0,2048}\)|\[[^\]\n]{0,256}\])"  # a link's address: "(https://…)", or "[name]" defined elsewhere
_PICTURE = re.compile(rf"\[?!\[[^\]\n]{{0,256}}\]{_TARGET}(\]{_TARGET})?|<img\b[^>\n]{{0,2048}}>", re.I)
_TAG = re.compile(r"</?[a-z][^>\n]{0,2048}>", re.I)
_LINK = re.compile(rf"\[([^\]\n]{{0,256}})\]{_TARGET}")
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


def _without_comments(text: str) -> str:
    """Text without HTML comments ("<!-- … -->"); one never closed hides the rest, as it would on the site."""
    parts, at = [], 0
    while (start := text.find("<!--", at)) != -1:
        parts.append(text[at:start])
        end = text.find("-->", start + 4)
        if end == -1:
            return "".join(parts)
        at = end + 3
    return "".join(parts) + text[at:]


def no_pictures(text: str) -> str:
    """Markdown that can't show a picture: shown, one would be downloaded from wherever it's hosted, whoever wrote
    it. Outside code blocks, every HTML tag goes (<img>, and "background=" on anything), and every "![" is a plain
    "[" (whatever follows: "![a [b] c](…)", "![logo]" defined elsewhere). Code blocks are left as written."""
    lines, in_code = [], False
    for line in _without_comments(text).splitlines():
        if _FENCE.match(line):
            in_code = not in_code
        elif not in_code:
            line = _TAG.sub("", line).replace("![", "[")
        lines.append(line)
    return "\n".join(lines)


def _cleaned(text: str) -> str:
    """A section without its badges, pictures and HTML (clutter, and pictures from anywhere)."""
    text = no_pictures(_PICTURE.sub("", _without_comments(text)))
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
    # Each heading's parent (the nearest bigger one before it), and where its section ends (the next as big after
    # it): in one pass each, as a README may have thousands of headings.
    parents, ends, stack = [], [len(lines)] * len(headings), []
    for n, (i, level, title) in enumerate(headings):
        while stack and headings[stack[-1]][1] >= level:
            ends[stack.pop()] = i
        parents.append(headings[stack[-1]][2] if stack else "")
        stack.append(n)
    found = []
    for n, (i, level, title) in enumerate(headings):
        parent = parents[n]
        if (rank := _rank(title, parent)) is None:
            continue
        # In the README, an update heading under a bigger install heading is about updating something else ("Updating
        # plugins"): unless it's just "Upgrading", names the project, or is part of an update section.
        if rank == 0 and project and level > biggest and len(title.split()) > 1 and not _UPDATE.search(parent) \
                and not names & set(_NAME_WORD.findall(title.lower())):
            continue
        end = ends[n]
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
        if (Path(path) / name).is_file():  # (not one gone since the clone was last read)
            found.append(Suggestion(f"Run {name}", shlex.join(_interpreter(Path(path) / name, name)), name))
    if built and not scripts:  # (a project's own install script is its way: it may build more than this folder)
        found.append(Suggestion("Rebuild and install it", " && ".join(build_command(b) for b in built), "the rebuild"))
    return found


# A file bigger than this isn't read into the approval: nothing to read before running.
FILE_MAX_BYTES = 1024 * 1024


# Files a tool reads without being told their names: "make install" runs what the Makefile says, so a change to the
# Makefile is a change to the step.
_MAKEFILES = ("GNUmakefile", "makefile", "Makefile")
_IMPLIED = {
    "make": ("GNUmakefile", "makefile", "Makefile"), "gmake": ("GNUmakefile", "makefile", "Makefile"),
    "npm": ("package.json",), "pnpm": ("package.json",), "yarn": ("package.json",), "cargo": ("Cargo.toml",),
    "just": ("justfile", "Justfile"), "cmake": ("CMakeLists.txt",), "meson": ("meson.build",),
}
_IMPLIED_NAMES = {name for names in _IMPLIED.values() for name in names}  # (CMakeLists.txt: not a document)


# What a step covers (named_files): the clone's files its command names, and those the files it runs name in turn,
# read word by word ("lib/common", "./install-services.sh", "$SCRIPT_DIR/install-services.sh": each ending of a
# path is tried). Any kind of file: a sourced "build.conf" or "scripts/common" is as much the step as a script is.
# When it can't be told which file is meant ("install/*.sh", "dist-${ID}/deps.sh", or a name that ends like several
# of the clone's files, run or sourced), every one that could be is covered: better asked once too often.
# (Spaces as the shell sees them: a non-breaking space is part of a name, as it is when the script runs.)
_SPLIT = re.compile(r"[ \t\r\n\f\v'\"`;|&(),{}\[\]]+")
_VARIABLE = re.compile(r"\$\{[^}]*\}|\$\w+|\$\(|\)")  # "${TARGET_ID}", "$DIR": any part of a name
WORD_MAX = 512  # longer words are data (a payload, a key), never a file's name: not looked at
_SCRIPT_SUFFIXES = (".sh", ".bash", ".zsh", ".py", ".pl", ".rb", ".mk")
# Words after which a file is read as commands, whatever it looks like: sourced, run by an interpreter, included;
# or as the list of what to install ("pip install -r requirements.txt", "xargs -a pkglist.txt", "< packages.txt").
_RUNS_NEXT = {".", "source", "sh", "bash", "zsh", "dash", "ksh", "python", "python3", "perl", "ruby", "node", "exec",
              "include", "-include", "-f", "-r", "--requirement", "-a", "--arg-file", "<"}
# Files never run or read as settings, which change often (documentation, pictures, fonts): not covered unless run or
# read as above, so a step isn't asked about again for them.
# The program's own source, too: every update runs its new code anyway (accepted); a script that only mentions it
# ("see src/lib/api.ts") doesn't make it part of the step.
_NOT_COMMANDS = re.compile(r"\.(md|markdown|rst|txt|adoc|org|html?|pdf|png|jpe?g|gif|svg|webp|ico|xcf|ttf|otf|woff2?|"
                           r"tsx?|jsx?|mjs|cjs|vue|svelte|css|s[ac]ss|go|rs|c|cc|cpp|cxx|h|hh|hpp|java|kt|swift|cs|"
                           r"qml|ui)$|^(license|licence|copying|authors|changelog|readme)(\.\w+)?$", re.I)
NAMED_MAX = 300  # files covered by one step, at most
ENDING_MAX = 3  # a name merely mentioned that ends like more of the clone's files than this names none of them


def _is_script(file: Path) -> bool:
    if file.suffix in _SCRIPT_SUFFIXES or file.name in ("Makefile", "makefile", "GNUmakefile"):
        return True
    try:
        with file.open("rb") as f:
            return f.read(2) == b"#!"
    except OSError:
        return False


def _usable(file: Path, root: Path) -> bool:
    try:
        return file.is_relative_to(root) and file.is_file()
    except OSError:
        return False


def _tracked(root: Path) -> list[str] | None:
    """The clone's files, as git tracks them (relative paths, sorted); None if git can't say. (Through updater's git,
    which also reads a clone that belongs to the system, as one in /opt does.)"""
    from .updater import UpdateError, _git

    try:
        out = _git(str(root), "ls-files", "-z")
    except UpdateError:
        return None
    return sorted(p for p in out.stdout.split("\0") if p) if out.returncode == 0 else None


def _file_words(file: Path) -> list[tuple[str, bool]]:
    """Each word of a text file that may name a file, and whether it's read as commands (after "source", "bash", or
    as a list of what to install); "python3 -m tools.inst" names tools/inst.py, and "npm ci" names package.json (as
    a step's own command does, _IMPLIED). Words too long to be a name are left out."""
    try:
        if file.stat().st_size > FILE_MAX_BYTES:
            return []  # (covered, but not read for more)
        text = file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    found = []
    for line in text.splitlines():
        words = [w for w in _SPLIT.split(line) if w]
        if "find" in words and "-name" in words and words.index("find") + 1 < len(words):
            # "find hooks -name '*.sh' -exec sh {} \;": what it finds, as a pattern ("hooks/*.sh").
            where, name = words[words.index("find") + 1], words[words.index("-name") + 1 : words.index("-name") + 2]
            if name and not where.startswith("-"):
                found.append((f"{where.rstrip('/')}/*{name[0].lstrip('*')}", "-exec" in words or "-execdir" in words))
        for k, word in enumerate(words):
            if len(word) > WORD_MAX or "://" in word or not any(c.isalnum() for c in word):
                continue
            before = words[k - 1] if k else ""
            if before == "-m" and k > 1 and words[k - 2].startswith("python") and "/" not in word:
                found += [(word.replace(".", "/") + ".py", True), (word.replace(".", "/") + "/__main__.py", True)]
                continue
            # (Covered, not followed further: a Makefile's recipes are commands; package.json's, Cargo.toml's or
            # CMakeLists.txt's words lead into the project's own source, which every update changes.)
            found += [(name, name in _MAKEFILES) for name in _IMPLIED.get(word, ())]
            found.append((word, before in _RUNS_NEXT))
    return found


class _Clone:
    """The clone's tracked files, looked up by name (once per step: a clone may have tens of thousands)."""

    def __init__(self, root: Path):
        self.root = root
        self.tracked = _tracked(root)
        self.known = set(self.tracked or ())
        self.by_name: dict[str, list[str]] = {}
        for t in self.tracked or ():
            self.by_name.setdefault(t.rsplit("/", 1)[-1], []).append(t)

    def ok(self, file: Path) -> bool:
        """The clone's own, git-tracked file (not what a build left), when git can say."""
        return _usable(file, self.root) and (self.tracked is None or file.relative_to(self.root).as_posix() in self.known)

    def ending(self, tail: str) -> list[str]:
        """The tracked files whose path ends with `tail`."""
        return [t for t in self.by_name.get(tail.rsplit("/", 1)[-1], ()) if t == tail or t.endswith("/" + tail)]

    def matching(self, pattern: str) -> list[str]:
        """The tracked files a pattern ("install/*.sh", from "$DIR/install/*.sh") could mean, by how they end. (By
        the file's name first, when the pattern says it: a clone may have tens of thousands of files.)"""
        import fnmatch

        last = pattern.rsplit("/", 1)[-1]
        candidates = self.tracked or () if any(c in last for c in "*?[") else self.by_name.get(last, ())
        return [t for t in candidates if fnmatch.fnmatchcase(t, pattern) or fnmatch.fnmatchcase(t, "*/" + pattern)]


def _named_by(file: Path, clone: _Clone) -> tuple[list[tuple[Path, bool]], list[tuple[Path, bool]]]:
    """The clone's files this one names: (file, whether to read it for more). Those named outright (by path, from this
    file's folder or the clone's: each that's there), then those found by how a name ends ("$DIR/lib/common.sh") or
    by a pattern ("install/*.sh", "dist-${ID}/deps.sh"). A name merely mentioned that ends like many files (vendored
    copies) names none; one run or sourced names them all."""
    root = clone.root
    named, ending = [], []
    near = str(file.parent.relative_to(root)) if file.parent != root else ""
    for word, runs in dict.fromkeys(_file_words(file)):
        pattern = _VARIABLE.sub("*", word)
        if pattern != word or any(c in word for c in "*?"):
            if not pattern.strip("*/."):
                continue  # ("$installer"): nothing to tell which file
            # Its longest ending (with a folder in it) that matches any of the clone's files: "install/terminal/*.sh"
            # from "~/.local/share/omakub/install/terminal/*.sh", as the clone is somewhere else once installed.
            pieces = pattern.split("/")
            # (Just the file's name only when it's in a folder named by a variable: "$LIBDIR/install-deps.sh".)
            matches = next((m for i in range(len(pieces) - 1) if (tail := "/".join(pieces[i:]).lstrip("*/"))
                            and ("/" in tail or pattern.startswith("*/"))
                            and (m := clone.matching(tail.removeprefix("./")))), [])
            # A glob ("install/*.sh", in a loop that runs them) means all it matches; a name made of a variable only
            # does when it's run or sourced, or matches only a few (as a name's ending).
            if any(c in word for c in "*?") or runs or len(matches) <= ENDING_MAX:
                for t in matches:
                    if not _NOT_COMMANDS.search(t) or runs:
                        found = (root / t).resolve()
                        ending.append((found, runs or _is_script(found)))
            continue
        parts = word.split("/")
        tails = [t for i in range(len(parts)) if (t := "/".join(parts[i:]))]
        here = []
        for tail in tails:
            here = [c for b in dict.fromkeys((file.parent, root)) if clone.ok(c := (b / tail).resolve())
                    and (runs or c.name in _IMPLIED_NAMES or not _NOT_COMMANDS.search(c.name))]
            if here:
                break
        if here:
            named += [(c, runs or _is_script(c)) for c in dict.fromkeys(here)]
            continue
        if "/" not in word and not word.endswith(_SCRIPT_SUFFIXES) and not runs:
            continue  # (a plain word: not a name behind a variable)
        for tail in tails:  # the longest ending that names any of the clone's files
            ends = clone.ending(tail)
            if not ends:
                continue
            inside = [t for t in ends if near and t.startswith(near + "/")]
            chosen = ends if runs else inside if inside and len(inside) <= ENDING_MAX else ends \
                if len(ends) <= ENDING_MAX else []
            for t in chosen:
                found = (root / t).resolve()
                if _usable(found, root) and (runs or _is_script(found)):
                    ending.append((found, True))
            break
    return named, ending


def named_files(path: str, command: str) -> list[Path]:
    """What approving the command covers: the clone's files it names (a script), those the tools it runs read
    without being told (make's Makefile, npm's package.json), and the files those name in turn (a sourced
    "build.conf", a script it runs, a Makefile's include, "install/*.sh"), followed into those that are commands. A
    change to any of them is shown before the step runs again."""
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
    clone, later, read = _Clone(root), [], set(files)
    queue = list(files)
    while queue:  # (what those name, in turn: files named outright first, then those found by how they end)
        file = queue.pop(0)
        named, ending = _named_by(file, clone)
        for found, runs in named:
            if found not in files and len(files) < NAMED_MAX:
                files.append(found)
            if runs and found not in read:
                read.add(found)
                queue.append(found)
        later.extend(ending)
        if not queue:
            for found, runs in dict.fromkeys(later):
                if found not in files and len(files) < NAMED_MAX:
                    files.append(found)
                if runs and found not in read:
                    read.add(found)
                    queue.append(found)
            later = []
    return files


def missing(path: str, command: str) -> list[str]:
    """The clone's files the command runs that aren't there any more ("./install.sh", removed by an update)."""
    try:
        words = shlex.split(command)
    except ValueError:
        return []
    root = Path(path).resolve()
    # (One that's now a link to a file outside the clone is gone too: what's outside isn't the step.)
    return [w for w in words if w.startswith("./") and not ((f := (root / w).resolve()).is_relative_to(root)
                                                           and f.is_file())]


def _mentions(file: Path, word: bytes) -> bool:
    try:
        return file.stat().st_size <= FILE_MAX_BYTES and word in file.read_bytes()
    except OSError:
        return False


def fingerprint(path: str, command: str) -> str:
    """What was approved: the command, and the content of the files it names."""
    digest, root = hashlib.sha256(command.encode()), Path(path).resolve()
    files = named_files(path, command)
    if any(_mentions(file, b"submodule") for file in files):
        # Its submodules (which it updates and runs): the commits they're at, and where they come from. A pull that
        # only moves one changes what runs.
        from .updater import UpdateError, _git

        try:
            staged = _git(str(root), "ls-files", "-s", "-z").stdout
        except UpdateError:
            staged = "?"
        digest.update(b"\0submodules\0" + "\0".join(e for e in staged.split("\0") if e.startswith("160000"))
                      .encode())
        if (root / ".gitmodules").is_file():
            digest.update(b"\0.gitmodules\0" + (root / ".gitmodules").read_bytes())
    for file in files:
        digest.update(b"\0" + str(file.relative_to(root)).encode() + b"\0")
        try:
            with file.open("rb") as f:
                digest.update(hashlib.file_digest(f, "sha256").digest())  # (in parts: a big file too)
        except OSError:
            digest.update(b"\0unreadable")  # (so it becoming readable again is a change too)
    return digest.hexdigest()


# Characters that don't show, or show something else than what's there (a space that isn't one, text that runs
# backwards): shown as their codes, so what's read is what runs.
_HIDDEN = re.compile("[^\\S\\n\\t ]|[\\x00-\\x08\\x0b\\x0c\\x0e-\\x1f\\x7f-\\x9f\\u00ad\\u200b-\\u200f\\u202a-\\u202e"
                     "\\u2060-\\u2064\\u2066-\\u2069\\ufeff]")
# What a step downloads and runs as it goes: not in the clone, so never shown in the window.
_FETCHES = re.compile(r"\b(curl|wget|git (?:clone|pull|fetch|submodule)|(?:npm|pnpm) (?:ci|install|i)|yarn|"
                      r"pip3? install|pipx install|cargo install|go (?:install|get)|flatpak install|yay|paru|"
                      r"(?:docker|podman) (?:pull|build)|compose (?:pull|up))\b")


def _shown(text: str) -> str:
    return _HIDDEN.sub(lambda m: f"\u27e8U+{ord(m.group()):04X}\u27e9", text)


def changes(path: str, command: str, since: str) -> tuple[list[str], str]:
    """What changed in the files the command covers since the clone was at commit `since` (when it was approved):
    (their names, the diff). ([], "") if that can't be told (no commit, or one that's gone)."""
    from .updater import UpdateError, _git

    root = Path(path).resolve()
    if not since:
        return [], ""
    names = [f.relative_to(root).as_posix() for f in named_files(path, command)]
    try:
        listed = _git(str(root), "diff", "--name-only", since, "--", *names)
        diff = _git(str(root), "diff", "--no-color", "--no-ext-diff", since, "--", *names) if listed.stdout else None
    except UpdateError:
        return [], ""
    if listed.returncode != 0:
        return [], ""
    return listed.stdout.split(), (diff.stdout[:FILE_MAX_BYTES] if diff else "")


def review_text(path: str, command: str, since: str = "") -> str:
    """The command and the files it covers, to read before approving it: what can't be seen shown by its code; and,
    first, whether it also downloads things as it runs (which can't be shown), and what changed since it was
    approved at commit `since` (as a diff: the change is what there is to read)."""
    root = Path(path).resolve()
    parts, fetches = [_shown(command)], set()
    changed, diff = changes(path, command, since)
    if changed:
        parts = [f"# Changed since you approved it: {', '.join(_shown(n) for n in changed)}\n\n{_shown(diff)}",
                 "\n# ======== All it runs, as it is now ========\n", *parts]
    for file in named_files(path, command):
        try:
            size = file.stat().st_size
            text = (f"# ({size / 1024 ** 2:.1f} MB: too big to show here. It\u2019s covered all the same: a change to "
                    "it is shown before the step runs again.)\n" if size > FILE_MAX_BYTES
                    else file.read_text(encoding="utf-8", errors="replace"))
        except OSError as e:
            text = f"# (couldn\u2019t be read: {e.strerror or e})\n"
        fetches.update(m.group(1) for m in _FETCHES.finditer(text))
        parts.append(f"\n# ---- {_shown(str(file.relative_to(root)))} ----\n" + _shown(text))
    if fetches:
        parts.insert(0, f"# As it runs, it also downloads from the internet ({', '.join(sorted(fetches))}): what it gets "
                        "isn\u2019t in the clone, so it isn\u2019t shown here.\n")
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
