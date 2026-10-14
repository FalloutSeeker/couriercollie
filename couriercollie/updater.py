"""Updating what's tracked. Only ever runs because you clicked Update (DECISIONS.md, D4, D6).

Packages (an .rpm, .deb or Arch package): the new one is downloaded, checked, and installed by the package manager
(dnf, zypper, apt or pacman), which asks for your password.

Programs (an archive with a ready-made program inside): each version is unpacked into its own folder, and a link in
~/.local/bin starts it; updating switches the link, then removes the old version.

AppImages: the new file is downloaded next to yours, checked against the project's published checksum (and that it
really is an AppImage), then swapped in; the old one is removed once the new one is in place.

Flatpak bundles: installed for you with flatpak (flatpaks.py), which never updates a bundle by itself.

Git clones: a project you don't have yet is cloned into ~/src. The new commits on the followed branch are pulled,
fast-forward only, so nothing of yours is merged, rebased or thrown away. What runs after an update (a step you
approved: applying.py) is never run unseen; one that asks for a password is copied to a terminal to run there.

Whatever is downloaded is checked against the checksum the project published, when there is one, before it's used.
"""

import contextlib
import errno
import hashlib
import http.client
import os
import re
import platform
import pwd
import shlex
import secrets
import shutil
import subprocess
import tarfile
import threading
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

from . import flatpaks, packages, sources

# Fetching can take a while for a big project on a slow connection.
FETCH_TIMEOUT = 300
# As root, the time also covers typing the password.
ROOT_TIMEOUT = 600
# How a clone that belongs to the system is updated: through polkit, which asks for your password (DECISIONS.md, D6).
ROOT = ["/usr/bin/pkexec"]
# What runs as root is named by its full path, and finds anything else only in the system's folders: a program of the
# same name in a folder you can write to (~/.local/bin, say) must never be the one run.
SYSTEM_PATH = "/usr/sbin:/usr/bin:/sbin:/bin"
GIT_AS_ROOT = "/usr/bin/git"
# Names an install, setup or update script goes by, in the clone's top folder or scripts/. "uninstall.sh" and the like
# are left out on purpose.
INSTALL_SCRIPTS = ("install.sh", "install", "setup.sh", "update.sh",
                   "scripts/install.sh", "scripts/install", "scripts/setup.sh", "scripts/update.sh")
# Scripts bigger than this aren't shown (or offered): something that large isn't a script to read before running.
SCRIPT_MAX_BYTES = 256 * 1024


class UpdateError(Exception):
    """Why an update couldn't be done, for the user."""


def shown(path) -> str:
    """A path as shown to you: inside your home folder, it starts with ~ (easier to read than /home/<you>/…)."""
    home, text = str(Path.home()), str(path)
    return "~" + text[len(home):] if text == home or text.startswith(home + "/") else text


def _git(path: str, *args: str, timeout: int = 30) -> subprocess.CompletedProcess:
    # safe.directory: git won't otherwise read a clone that belongs to another user (e.g. the system, in /opt).
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0", "LC_ALL": "C"}
    try:
        return subprocess.run(["git", "-c", f"safe.directory={path}", "-C", path, *args], capture_output=True,
                              text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired as e:
        raise UpdateError("Git took too long to answer; check your connection and try again.") from e
    except OSError as e:
        raise UpdateError(f"Couldn’t run git: {e}") from e


def _inside_tree(path: str, hooks: str) -> bool:
    """Whether a hooks folder is among the clone's own files (not in .git, which a pull leaves alone)."""
    root = Path(path).resolve()
    where = (root / Path(hooks).expanduser()).resolve()
    return where.is_relative_to(root) and not where.is_relative_to(root / ".git")


def git_out(path: str, *args: str, timeout: int = 30) -> str:
    """A git command's output in the clone at `path`, or "" if it fails. Never asks for anything."""
    try:
        result = _git(path, *args, timeout=timeout)
    except UpdateError:
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


# Closing lines that say nothing themselves (zypper's "Please see the above error message for a hint."), and what a
# line that says why looks like.
_SAYS_NOTHING = re.compile(r"see the above|problem occurred during or after|has been aborted|abort, retry, ignore",
                           re.I)
_SAYS_WHY = re.compile(r"error|fail|cannot|can't|couldn't|unable|conflict|nothing provides|not found|no such|"
                       r"denied|signature|requires|broken|refus", re.I)


def _last_line(result: subprocess.CompletedProcess, program: str = "git") -> str:
    """Why a command failed, in one line: the last that says why (an error, a conflict, a missing dependency), from
    its errors before its output; else its last line that says anything."""
    streams = [[s.strip() for s in text.splitlines() if s.strip() and not _SAYS_NOTHING.search(s)]
               for text in (result.stderr or "", result.stdout or "")]
    for lines in streams:
        if why := [line for line in lines if _SAYS_WHY.search(line)]:
            return why[-1]
    return next((lines[-1] for lines in streams if lines), f"{program} exited with {result.returncode}")


def compare_here(path: str, yours: str, head: str) -> "sources.Comparison | None":
    """How your commit relates to the branch's newest, worked out by git in the clone itself, when it has both (once
    fetched, or after you pulled by hand): free (no request to the site), and it knows commits of yours that were
    never pushed, which the site can't. None if the clone doesn't have both, or isn't there."""
    if not path or not (Path(path) / ".git").exists():
        return None
    for sha in (yours, head):
        if _git(path, "cat-file", "-e", f"{sha}^{{commit}}").returncode != 0:
            return None
    counts = git_out(path, "rev-list", "--left-right", "--count", f"{yours}...{head}").split()
    if len(counts) != 2:
        return None
    ahead, behind = int(counts[0]), int(counts[1])  # yours only; the branch's only
    if not ahead and not behind:
        return sources.Comparison(sources.SAME)
    if not ahead:
        log = git_out(path, "log", "--format=%H%x09%s", "-n", "50", f"{yours}..{head}")
        commits = [sources.Commit(*line.split("\t", 1)) for line in log.splitlines() if "\t" in line]
        return sources.Comparison(sources.BEHIND, behind, commits)
    return sources.Comparison(sources.AHEAD if not behind else sources.DIVERGED, behind)


def _remote_for(path: str, repo_ids: list[str]) -> str:
    """The clone's remote that points at the tracked project (a scan matched it by address), else "origin"."""
    wanted = {i.lower() for i in repo_ids}
    for name in git_out(path, "remote").splitlines():
        try:
            if sources.parse_url(git_out(path, "remote", "get-url", name)).id.lower() in wanted:
                return name
        except ValueError:
            continue
    return "origin"


def _writable(path: str) -> bool:
    return os.access(Path(path) / ".git", os.W_OK)


def _owner(path: str) -> int:
    return (Path(path) / ".git").stat().st_uid


def someone_elses(path: str) -> str:
    """The person a clone belongs to, if it's another's (not yours, nor the system's): its updates are theirs, so it's
    only shown here. "" otherwise, or if it can't be told."""
    try:
        owner = _owner(path)
    except OSError:
        return ""
    if owner in (0, os.geteuid()):
        return ""
    try:
        return pwd.getpwuid(owner).pw_name
    except KeyError:
        return str(owner)


def _as_root(path: str) -> bool:
    """Whether the clone has to be changed as root: it belongs to the system. One that belongs to another person is
    left alone: changing it as root would leave files in it that they can't change."""
    if not (Path(path) / ".git").exists():
        raise UpdateError(f"There\u2019s no git clone at {shown(path)} any more.")
    if _writable(path):
        return False
    if _owner(path) == 0 and (not ROOT or shutil.which(ROOT[0])):
        return True
    if _owner(path) == os.geteuid():
        raise UpdateError(f"{shown(path)} is yours, but its permissions don\u2019t let it be changed, so it "
                          "wasn\u2019t.")
    raise UpdateError(f"{shown(path)} belongs to another user, so it can\u2019t be updated from here. As that user, "
                      f"in a terminal: cd {shlex.quote(path)} && git pull --ff-only")


def needs_password(path: str) -> bool:
    """Whether updating the clone will ask for your password (it belongs to the system)."""
    try:
        return _as_root(path)
    except (UpdateError, OSError):
        return False


def _run_steps(path: str, steps: list[list[str]], as_root: bool) -> subprocess.CompletedProcess:
    """Runs git commands in order, stopping at the first that fails. As root, all in one go, so the password is asked
    for once."""
    if not as_root:
        result = None
        # Your own hooks (in .git/hooks, which a pull can't change) run as usual. Hooks the clone keeps in its own
        # files (core.hooksPath into them: husky, .githooks) don't: the pull would change them, then run them, unseen.
        hooks = git_out(path, "config", "core.hooksPath")
        unsafe = bool(hooks) and _inside_tree(path, hooks)
        for step in steps:
            result = _git(path, *(["-c", "core.hooksPath=/dev/null"] if unsafe else []), *step, timeout=FETCH_TIMEOUT)
            if result.returncode != 0:
                break
        return result
    # As root: git from the system's folder, and none of the clone's hooks (scripts git would otherwise run).
    script = f"export PATH={SYSTEM_PATH} LC_ALL=C GIT_TERMINAL_PROMPT=0; " + " && ".join(
        shlex.join([GIT_AS_ROOT, "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false",
                    "-c", f"safe.directory={path}", "-C", path, *step]) for step in steps)
    try:
        result = subprocess.run([*ROOT, "/bin/sh", "-c", script], capture_output=True, text=True,
                                timeout=ROOT_TIMEOUT)
    except subprocess.TimeoutExpired as e:
        raise UpdateError("The update took too long; nothing more was done.") from e
    except OSError as e:
        raise UpdateError(f"Couldn\u2019t ask for the password: {e}") from e
    if ROOT and result.returncode in (126, 127):  # polkit: the password wasn't given, or isn't allowed
        raise UpdateError("The password wasn\u2019t given, so nothing was changed.")
    return result


def _explain(result: subprocess.CompletedProcess) -> UpdateError:
    """Why git refused, for the user. Its reason may come before its last line ("Aborting")."""
    said = (result.stderr + result.stdout).lower()
    if "not possible to fast-forward" in said or "diverging" in said:
        return UpdateError("Your clone has commits of its own that aren\u2019t on the project\u2019s branch, so it "
                           "wasn\u2019t changed. Pull it yourself in a terminal to choose how to combine them.")
    if "overwritten" in said or "local changes" in said:
        return UpdateError("Files you changed in the clone are also changed by the update, so it wasn\u2019t "
                           "changed. Commit or stash your changes, then update again.")
    if "couldn't find remote ref" in said or "unable to access" in said or "could not resolve" in said:
        return UpdateError(f"Couldn\u2019t download the update: {_last_line(result)}")
    return UpdateError(f"Couldn\u2019t update the clone: {_last_line(result)}")


def pull(path: str, branch: str, repo_ids: list[str]) -> tuple[str, str, int]:
    """Brings the clone at `path` up to the newest commit on `branch`. Returns (commit before, commit after, how many
    new commits). Refuses, with the reason, anything that isn't a plain fast-forward of the branch you're on."""
    as_root = _as_root(path)
    on = git_out(path, "symbolic-ref", "--short", "-q", "HEAD")
    if on != branch:
        where = f"on {on}" if on else "not on any branch"
        raise UpdateError(f"Your clone is {where}, not {branch}, so it wasn\u2019t changed. Switch it to {branch} "
                          f"(git switch {shlex.quote(branch)}), or follow {on or 'another branch'} instead.")
    before = git_out(path, "rev-parse", "HEAD")
    remote = _remote_for(path, repo_ids)
    result = _run_steps(path, [["fetch", "--quiet", "--no-tags", remote, branch],
                               ["merge", "--ff-only", "--quiet", "FETCH_HEAD"]], as_root)
    if result.returncode != 0:
        raise _explain(result)
    after = git_out(path, "rev-parse", "HEAD")
    count = int(git_out(path, "rev-list", "--count", f"{before}..{after}") or 0) if before and after else 0
    return before, after, count


# A whole project's history can be big.
CLONE_TIMEOUT = 1800


def clones_dir() -> Path:
    """Where Install puts a clone of a project you don't have yet (D8)."""
    return Path(os.environ.get("COURIERCOLLIE_CLONES") or Path.home() / "src")


def clone(url: str, ref: str, name: str) -> Path:
    """Clones the project at `url` into its own folder in clones_dir(), on branch `ref` (or at the release tag `ref`).
    Cloned under a hidden name first, so a failed clone leaves no half-made folder behind. Returns the folder."""
    parent = clones_dir()
    parent.mkdir(parents=True, exist_ok=True)
    base = _folder_name(name)
    # Its own hidden name (two projects of the same name may be cloned at once), then the first free name.
    part = parent / f".{base}.{secrets.token_hex(4)}.part"
    try:
        result = _git(str(parent), "-c", "advice.detachedHead=false", "clone", "--quiet", "--branch", ref, "--",
                      url, part.name, timeout=CLONE_TIMEOUT)
        if result.returncode != 0:
            raise UpdateError(f"Couldn\u2019t clone the project: {_last_line(result)}")
        for dest in (parent / n for n in (base, *(f"{base}-{i}" for i in range(2, 100)))):
            try:
                dest.mkdir()  # taken, or ours: a rename onto an empty folder replaces it
            except FileExistsError:
                continue
            try:
                part.rename(dest)
            except OSError:
                dest.rmdir()
                raise
            break
        else:
            raise UpdateError(f"Couldn\u2019t find a free folder name for {base} in {shown(parent)}.")
    finally:
        shutil.rmtree(part, ignore_errors=True)
    return dest


def checkout_release(path: str, tag: str, repo_ids: list[str]) -> tuple[str, str]:
    """Moves the clone at `path` to the release `tag`, fetched from the project. Returns (commit before, the branch it
    was on, or ""). The branch itself isn't changed, so `git switch <branch>` goes back. Refuses if that would leave
    commits behind that aren't on any branch or tag."""
    as_root = _as_root(path)
    on = git_out(path, "symbolic-ref", "--short", "-q", "HEAD")
    before = git_out(path, "rev-parse", "HEAD")
    if not on and before and not git_out(path, "for-each-ref", "--count=1", "--contains", before):
        raise UpdateError("Your clone has commits that aren\u2019t on any branch, and moving it to the new release "
                          "would leave them behind, so it wasn\u2019t changed. Put them on a branch first "
                          "(git switch -c <name>), then update again.")
    remote = _remote_for(path, repo_ids)
    ref = f"refs/tags/{tag}"
    result = _run_steps(path, [["fetch", "--quiet", "--no-tags", remote, f"{ref}:{ref}"],
                               ["-c", "advice.detachedHead=false", "checkout", "--quiet", "--detach", ref]], as_root)
    if result.returncode != 0:
        raise _explain(result)
    return before, on


# ---------------------------------------------------------------------------------------------------------------------
# Install scripts


def install_scripts(path: str) -> list[str]:
    """Install, setup and update scripts in the clone's top folder or its scripts/ folder, by name ("setup.sh",
    "scripts/setup.sh"). Not one that's a link to a file outside the clone: a change there would go unseen."""
    folder = Path(path).resolve()
    found = []
    for n in INSTALL_SCRIPTS:
        try:
            file = (folder / n).resolve()
            if file.is_relative_to(folder) and file.is_file() and file.stat().st_size <= SCRIPT_MAX_BYTES:
                found.append(n)
        except OSError:
            continue
    return found


def _interpreter(script: Path, name: str = "") -> list[str]:
    """How to run the script (`name`: its path from the clone's folder, where it's run from): itself if it may be
    run, else what its first line names, else sh."""
    relative = f"./{name or script.name}"
    if os.access(script, os.X_OK):
        return [relative]
    try:
        with script.open("rb") as f:
            first = f.readline().decode("utf-8", "replace").strip()
    except OSError:  # (gone since it was found)
        return ["sh", relative]
    if first.startswith("#!") and (words := shlex.split(first[2:])):
        return [*words, relative]
    return ["sh", relative]


# ---------------------------------------------------------------------------------------------------------------------
# AppImages: downloaded next to the one you have (or into ~/Applications, DECISIONS.md D8), checked, then swapped in.
# The old file is removed only once the new one is in place (D6).

# Nothing this big is downloaded: a mistake, or not an app.
DOWNLOAD_MAX_BYTES = 4 * 1024 ** 3
CHUNK = 1024 * 1024
# Checksum files in a release, by name (lower case).
_CHECKSUM_NAMES = ("sha256sums", "sha256sum", "checksums", "checksum", "sha256")


def _data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def apps_dir() -> Path:
    """Where AppImages the app installs go (D8)."""
    return Path(os.environ.get("COURIERCOLLIE_APPS") or Path.home() / "Applications")


def menu_dir() -> Path:
    return _data_home() / "applications"


def _checksum_files(asset_name: str, others: list) -> list:
    """Checksum files in the same release that may list `asset_name`: "<file>.sha256" first, then shared ones."""
    own = [a for a in others if a.name.lower() in (asset_name.lower() + ".sha256", asset_name.lower() + ".sha256sum")]
    shared = [a for a in others if a not in own and a.name != asset_name and len(a.name) < 80
              and any(n in a.name.lower() for n in _CHECKSUM_NAMES) and (a.size or 0) < 1024 * 1024]
    return own + shared


# "<hex>  <name>" (sha256sum; "*" before the name in binary mode), or BSD's "SHA256 (<name>) = <hex>".
_SUM_LINE = re.compile(r"^([0-9a-fA-F]{64})\s+\*?(.+)$")
_BSD_LINE = re.compile(r"^SHA256 \((.+)\) = ([0-9a-fA-F]{64})$")


def _find_sha256(text: str, asset_name: str, own: bool = False) -> str:
    """The SHA-256 for `asset_name` in a checksum file: the line naming it exactly (a folder before the name is
    allowed, as in "dist/app.AppImage"). In its own "<file>.sha256", a file holding just the hex counts too; in a
    file shared by the release, never: it would be another file's."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in lines:
        if m := _SUM_LINE.match(line):
            digest, name = m.group(1), m.group(2).strip()
        elif m := _BSD_LINE.match(line):
            name, digest = m.group(1), m.group(2)
        else:
            continue
        if name.removeprefix("./") == asset_name or name.rsplit("/", 1)[-1] == asset_name:
            return digest.lower()
    if own and len(lines) == 1 and _is_sha256(lines[0].split()[0]):
        return lines[0].split()[0].lower()
    return ""


def _is_sha256(text: str) -> bool:
    return len(text) == 64 and all(c in "0123456789abcdefABCDEF" for c in text)


def expected_sha256(asset, others: list, get_text) -> str:
    """The checksum the project published for `asset`: the site's own (GitHub gives one for each file, no request),
    else from a checksum file in the release (one small download). "" if there's none."""
    if asset.digest.startswith("sha256:") and _is_sha256(asset.digest[7:]):
        return asset.digest[7:].lower()
    own = (asset.name.lower() + ".sha256", asset.name.lower() + ".sha256sum")
    for f in _checksum_files(asset.name, others):
        try:
            if found := _find_sha256(get_text(f.url), asset.name, f.name.lower() in own):
                return found
        except (OSError, ValueError, sources.SourceError):
            continue
    return ""


def _secure(url: str) -> bool:
    """Over https: over plain http, anyone between here and the site could swap what's sent (a GitLab release's
    files are links, which can point anywhere). Except from this computer itself, where nothing is in between."""
    parsed = urllib.parse.urlparse(url)
    return parsed.scheme == "https" or (parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost"))


def fetch_text(url: str, limit: int = 1024 * 1024) -> str:
    if not _secure(url):
        raise ValueError("not over https")  # a checksum anyone could swap would check nothing: not used
    req = urllib.request.Request(url, headers={"User-Agent": sources.USER_AGENT})
    with urllib.request.urlopen(req, timeout=sources.TIMEOUT) as resp:
        return resp.read(limit).decode("utf-8", "replace")


def download(url: str, dest: Path, size: int | None, progress=None) -> str:
    """Downloads `url` to `dest`, returning its SHA-256. `progress(done, total)` is called now and then."""
    if not _secure(url):
        raise UpdateError("The file\u2019s address isn\u2019t secure (http, not https), so it wasn\u2019t "
                          "downloaded.")
    if size and size > DOWNLOAD_MAX_BYTES:
        raise UpdateError("The file is too big to be an app; it wasn’t downloaded.")
    if size and shutil.disk_usage(dest.parent).free < size + 64 * 1024 ** 2:
        raise UpdateError(f"There isn’t enough free space in {dest.parent} for the download.")
    digest, done = hashlib.sha256(), 0
    req = urllib.request.Request(url, headers={"User-Agent": sources.USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=sources.TIMEOUT) as resp, dest.open("wb") as out:
            total = int(resp.headers.get("Content-Length") or size or 0)
            while chunk := resp.read(CHUNK):
                done += len(chunk)
                if done > DOWNLOAD_MAX_BYTES:
                    raise UpdateError("The download is too big to be an app; it was stopped.")
                digest.update(chunk)
                out.write(chunk)
                if progress:
                    progress(done, total)
            # A connection that dropped partway can look like the end of the file: only the whole of it counts. (A
            # cut-off AppImage from a project with no checksum would otherwise be installed, broken.)
            if total and done != total:
                raise UpdateError(f"The download didn\u2019t finish: {done:,} of {total:,} bytes arrived. Try again.")
    except (OSError, urllib.error.URLError, http.client.HTTPException) as e:
        dest.unlink(missing_ok=True)
        if isinstance(e, urllib.error.HTTPError):
            e.close()  # (the error answer's connection)
        raise UpdateError(f"The download didn’t finish: {_download_problem(e)}") from e
    except UpdateError:
        dest.unlink(missing_ok=True)
        raise
    return digest.hexdigest()


def _download_problem(e: Exception) -> str:
    """Why a download stopped, in words (not "[Errno -3] Temporary failure in name resolution")."""
    reason = getattr(e, "reason", None)
    if isinstance(e, urllib.error.HTTPError):
        return f"the site answered with an error ({e.code}). Try again later."
    if isinstance(e, TimeoutError) or isinstance(reason, TimeoutError) or "timed out" in str(reason or e):
        return "the connection stopped answering. Check your internet connection, then try again."
    if isinstance(e, urllib.error.URLError):
        return "couldn\u2019t connect. Check your internet connection, then try again."
    if isinstance(e, (http.client.HTTPException, ConnectionError)):
        return "the connection dropped. Try again."
    if getattr(e, "errno", None) == errno.ENOSPC:
        return "the disk is full."
    return str(e)


def is_appimage(path: Path) -> bool:
    """An AppImage is a program (ELF) with "AI" and its type (1 or 2) at byte 8."""
    with path.open("rb") as f:
        head = f.read(11)
    return head[:4] == b"\x7fELF" and head[8:10] == b"AI" and head[10:11] in (b"\x01", b"\x02")


def _download_checked(asset, part: Path, others: list, progress, get_text) -> tuple[bool, str]:
    """Downloads `asset` to `part` and checks it against the checksum the project published. Returns whether there
    was one to check against, and the SHA-256 of what was downloaded. A download that doesn't match is deleted, and
    that's the end of it."""
    got = download(asset.url, part, asset.size, progress)
    expected = expected_sha256(asset, others, get_text)
    if expected and got != expected:
        part.unlink(missing_ok=True)
        raise UpdateError("The download doesn\u2019t match the checksum the project published, so it was thrown away. "
                          "Try again later; if it keeps happening, the file on the site may have been tampered with.")
    return bool(expected), got


def install_appimage(asset, others: list, folder: Path, old: Path | None,
                     progress=None, get_text=fetch_text) -> tuple[Path, bool]:
    """Downloads `asset` (a release's AppImage) into `folder`, checks it, and puts it in place of `old` (if any),
    which is then removed. Returns (the new file, whether it was checked against a published checksum)."""
    folder.mkdir(parents=True, exist_ok=True)
    if not os.access(folder, os.W_OK):
        raise UpdateError(f"{shown(folder)} belongs to another user (often the system), so the new version "
                          "can\u2019t be put there from here.")
    name = Path(asset.name).name  # never a path from the site
    part = folder / f".{name}.{secrets.token_hex(4)}.part"
    try:
        verified, _ = _download_checked(asset, part, others, progress, get_text)
        if not is_appimage(part):
            raise UpdateError(f"{name} isn\u2019t an AppImage, so it wasn\u2019t installed.")
        part.chmod(0o755)
        new = folder / name
        os.replace(part, new)
        if old and old != new:
            old.unlink(missing_ok=True)  # only now: until here, the old one still works
        return new, verified
    finally:
        part.unlink(missing_ok=True)


def _desktop_quote(path: Path) -> str:
    """A path as a desktop entry's Exec= argument. Two layers of escaping: the command line's (a backslash before
    " ` $ and \\), then the file's own (each backslash doubled); and a % is written %% (a lone % is a field code)."""
    escaped = str(path).replace("\\", "\\\\\\\\")
    for ch in '"`$':
        escaped = escaped.replace(ch, "\\\\" + ch)
    return f'"{escaped}"'.replace("%", "%%")


def repoint_menu_entries(old: Path, new: Path) -> int:
    """Menu entries of yours that start the old file (e.g. made by AppImageLauncher or Gear Lever) start the new one
    instead. Returns how many were changed."""
    changed = 0
    for entry in menu_dir().glob("*.desktop") if menu_dir().is_dir() else []:
        try:
            text = entry.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if str(old) not in text:
            continue
        lines = [line.replace(str(old), str(new)) if line.startswith(("Exec=", "TryExec=")) else line
                 for line in text.splitlines()]
        entry.write_text("\n".join(lines) + "\n", encoding="utf-8")
        changed += 1
    return changed


def _one_line(text: str) -> str:
    """A value for one line of a desktop entry: line breaks and other control characters would start new lines (new
    keys), so they become spaces."""
    return "".join(" " if ord(c) < 32 or ord(c) == 127 else c for c in text)


def write_menu_entry(repo_id: str, name: str, app: Path, icon: str) -> Path:
    """A menu entry (KDE launcher) for an AppImage the app installed. Marked as the app's, so it's kept up to date."""
    entry = menu_dir() / f"couriercollie-{_folder_name(repo_id.replace('/', '-').lower())}.desktop"
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text("\n".join([
        "[Desktop Entry]",
        "Type=Application",
        f"Name={_one_line(name)}",
        f"Exec={_one_line(_desktop_quote(app))} %U",
        f"TryExec={_one_line(str(app))}",
        f"Icon={_one_line(icon) or 'application-vnd.appimage'}",
        "Terminal=false",
        "Categories=Utility;",
        "Comment=Installed by couriercollie",
        f"X-couriercollie-Repo={_one_line(repo_id)}",
    ]) + "\n", encoding="utf-8")
    return entry


def menu_entry_for(app: Path) -> bool:
    """Whether any menu entry of yours starts this file."""
    return menu_dir().is_dir() and any(str(app) in e.read_text(encoding="utf-8", errors="replace")
                                       for e in menu_dir().glob("*.desktop"))


# ---------------------------------------------------------------------------------------------------------------------
# Programs: a release's archive (.tar.gz, .zip, …) with a ready-made program inside. Each version is unpacked whole
# (some programs need the files next to them) into its own folder, and a link in ~/.local/bin starts the program
# (D8). Updating unpacks the new version beside the old, switches the link, then removes the old folder.

# Unpacked, an archive may not be bigger than this (an archive can unpack to far more than it downloads).
UNPACKED_MAX_BYTES = 4 * 1024 ** 3


class SeveralPrograms(UpdateError):
    """The archive has more than one program and nothing says which is the one to run. `choices` are their names."""

    def __init__(self, choices: list[str]):
        super().__init__(f"The archive has {len(choices)} programs ({', '.join(choices)}). Choose the one to run, "
                         "then try again.")
        self.choices = choices


def programs_dir() -> Path:
    return _data_home() / "couriercollie" / "programs"


def bin_dir() -> Path:
    """Where the link to each program goes: on Fedora, already where the terminal looks for commands."""
    return Path(os.environ.get("COURIERCOLLIE_BIN") or Path.home() / ".local" / "bin")


def _folder_name(text: str) -> str:
    """A repo or version as one folder name."""
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in text).strip(".") or "_"


def _compressed(path: Path):
    """How to open a file compressed on its own (gzip, xz, bzip2 or zstd, by its first bytes), or None."""
    import bz2
    import gzip
    import lzma

    with path.open("rb") as f:
        head = f.read(6)
    if head.startswith(b"\x1f\x8b"):
        return gzip.open
    if head.startswith(b"\xfd7zXZ\x00"):
        return lzma.open
    if head.startswith(b"BZh"):
        return bz2.open
    if head.startswith(b"\x28\xb5\x2f\xfd"):
        try:
            from compression import zstd  # (Python 3.14)
        except ImportError:
            return None
        return zstd.open
    return None


def _unpack(archive: Path, into: Path, name: str = "program") -> None:
    """Unpacks an archive into `into`, refusing anything that would land outside it, links that point outside it,
    device files, and archives that unpack to more than UNPACKED_MAX_BYTES. A Linux program on its own, not in an
    archive (yq's "yq_linux_amd64"), goes in as `name`, runnable."""
    into.mkdir(parents=True)
    with archive.open("rb") as f:
        if f.read(4) == b"\x7fELF":
            shutil.copyfile(archive, into / name)
            (into / name).chmod(0o755)
            return
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as z:
            members = z.infolist()
            if sum(m.file_size for m in members) > UNPACKED_MAX_BYTES:
                raise UpdateError("The archive unpacks to more than 4 GB, so it wasn’t unpacked.")
            for m in members:
                target = (into / m.filename).resolve()
                if not target.is_relative_to(into.resolve()):
                    raise UpdateError(f"The archive tries to put {m.filename} outside its folder, so it wasn’t "
                                      "unpacked.")
                z.extract(m, into)
                mode = (m.external_attr >> 16) & 0o777
                if mode and not m.is_dir():
                    target.chmod(mode & 0o755)
        return
    if not tarfile.is_tarfile(archive) and (opener := _compressed(archive)):
        # One file compressed on its own (rust-analyzer's "…-linux-gnu.gz"): a program, if that's what it holds.
        program = into / name
        try:
            with opener(archive) as source, program.open("wb") as out:
                while chunk := source.read(CHUNK):
                    if out.tell() + len(chunk) > UNPACKED_MAX_BYTES:
                        raise UpdateError("The file unpacks to more than 4 GB, so it wasn’t unpacked.")
                    out.write(chunk)
        except UpdateError:
            raise
        except Exception as e:  # noqa: BLE001 - cut short or damaged: each format says it its own way (xz, zstd)
            raise UpdateError(f"{archive.name} is damaged and couldn’t be unpacked. Try again later.") from e
        with program.open("rb") as f:
            if f.read(4) != b"\x7fELF":
                raise UpdateError(f"{archive.name} doesn’t hold a Linux program, so it wasn’t installed.")
        program.chmod(0o755)
        return
    try:
        with tarfile.open(archive, "r:*") as t:
            if sum(m.size for m in t.getmembers()) > UNPACKED_MAX_BYTES:
                raise UpdateError("The archive unpacks to more than 4 GB, so it wasn’t unpacked.")
            t.extractall(into, filter="data")  # Python's safe mode: nothing outside, no devices, no setuid
    except tarfile.FilterError as e:
        raise UpdateError(f"The archive has something unsafe in it ({e}), so it wasn’t unpacked.") from e
    except (tarfile.TarError, EOFError, OSError) as e:
        raise UpdateError(f"The archive couldn’t be unpacked: {e}") from e


def _is_program(path: Path) -> bool:
    if path.is_symlink() or not path.is_file() or not os.access(path, os.X_OK) or ".so" in path.name:
        return False
    with path.open("rb") as f:
        return f.read(4) == b"\x7fELF"


def programs_in(folder: Path) -> list[Path]:
    """The programs (Linux executables) in an unpacked archive, shallowest first."""
    found = [p for p in folder.rglob("*") if _is_program(p)]
    return sorted(found, key=lambda p: (len(p.relative_to(folder).parts), str(p)))


def choose_program(folder: Path, wanted: str, hints: list[str]) -> Path:
    """The program to run: the one called `wanted` (chosen before, or the command already installed); the only one;
    or the one named like the project. Otherwise SeveralPrograms."""
    found = programs_in(folder)
    if not found:
        raise UpdateError("There’s no program for Linux in the archive, so there’s nothing to run.")
    if wanted:
        if named := [p for p in found if p.name == wanted]:
            return named[0]
        raise UpdateError(f"The new version has no program called {wanted} any more.")
    if len(found) == 1:
        return found[0]
    for hint in (h.lower().replace("-", "").replace("_", "") for h in hints if h):
        named = [p for p in found if p.name.lower().replace("-", "").replace("_", "").startswith(hint)]
        if len({p.name for p in named}) == 1:
            return named[0]
    raise SeveralPrograms(sorted({p.name for p in found}))


def install_program(repo_id: str, tag: str, asset, others: list, wanted: str = "", hints: list[str] = (),
                    progress=None, get_text=fetch_text) -> tuple[Path, bool, bool]:
    """Downloads a release's archive, checks it, unpacks it into its own folder, points the program's link in
    bin_dir() at it, and removes the version it pointed at before. Returns (the link, whether the download was checked
    against a published checksum, whether it replaced a version). Never replaces a command in bin_dir() that it
    didn't put there."""
    home = programs_dir() / _folder_name(repo_id)
    home.mkdir(parents=True, exist_ok=True)
    part = home / f".{_folder_name(Path(asset.name).name)}.part"
    unpacking = home / f".{_folder_name(tag)}.unpacking"
    shutil.rmtree(unpacking, ignore_errors=True)
    try:
        verified, _ = _download_checked(asset, part, others, progress, get_text)
        # A program on its own is named for the project ("yq", not "yq_linux_amd64").
        _unpack(part, unpacking, _folder_name(next((h for h in hints if h), "")) or _folder_name(asset.name))
        program = choose_program(unpacking, wanted, list(hints))
        link = bin_dir() / program.name
        # ~/.local/bin comes before the system's commands: a program called "sudo" or "ls" would run instead of the
        # real one, every time (and one called "sudo" could read your password).
        if system := next((Path(d) / program.name for d in SYSTEM_PATH.split(":")
                           if (Path(d) / program.name).exists()), None):
            raise UpdateError(f"The program is called \u201c{program.name}\u201d, like a command your system already "
                              f"has ({system}), so it wasn\u2019t installed: it would run instead of that one.")
        before = link.resolve() if link.is_symlink() else None
        if (link.exists() or link.is_symlink()) and not (before and before.is_relative_to(home.resolve())):
            raise UpdateError(f"{link} already exists and wasn’t put there by couriercollie, so it wasn’t "
                              "replaced. Move it away (or uninstall what it belongs to), then try again.")
        version = home / _folder_name(tag)
        # The folder the link uses now. If it's this same version (a reinstall), it's moved aside first.
        old = home / before.relative_to(home.resolve()).parts[0] if before else None
        if version.exists():
            aside = home / f".{_folder_name(tag)}.old"
            shutil.rmtree(aside, ignore_errors=True)
            os.replace(version, aside)
            if old == version:
                old = aside
        os.replace(unpacking, version)
        bin_dir().mkdir(parents=True, exist_ok=True)
        new_link = bin_dir() / f".{program.name}.couriercollie"
        new_link.unlink(missing_ok=True)
        new_link.symlink_to(version / program.relative_to(unpacking))
        os.replace(new_link, link)  # in one step: the command always works, old or new
        for gone in {old, home / f".{_folder_name(tag)}.old"} - {None, version}:
            shutil.rmtree(gone, ignore_errors=True)  # only now: until here, the old version still ran
        return link, verified, before is not None
    finally:
        part.unlink(missing_ok=True)
        shutil.rmtree(unpacking, ignore_errors=True)


def program_version(link: Path) -> str:
    """The version a program's link points at (its folder's name under programs_dir()), or ""."""
    try:
        target = link.resolve(strict=True).relative_to(programs_dir().resolve())
    except (OSError, ValueError):
        return ""
    return target.parts[1] if len(target.parts) > 2 else ""


# ---------------------------------------------------------------------------------------------------------------------
# Packages: the release's .rpm, .deb or Arch package is downloaded, checked, and installed by the package manager
# (packages.py), as root, which asks for your password (DECISIONS.md, D4, D6). Only packages installed from a
# downloaded file are tracked: the package manager doesn't update those itself.

# Installing can take a while (the package manager may download what the package needs), plus typing the password.
INSTALL_TIMEOUT = 1800


# Leftovers of an update that was cut short (the app killed, the computer turned off) are only removed once they're
# this old, so nothing still being made is touched.
LEFTOVER_AGE = 3600


def clean_leftovers(now: float | None = None) -> list[Path]:
    """Removes what an update cut short left behind, in the app's own folders: a half-downloaded ".x.part", a
    half-unpacked ".v2.0.unpacking", a half-made clone, a link not yet put in place. A program's version set aside
    (".v2.0.old") is put back if the version it stood for is missing (cut short just after setting it aside), else
    removed. Nothing that isn't hidden is touched. Returns what was removed or put back."""
    now = time.time() if now is None else now
    done: list[Path] = []

    def stale(path: Path) -> bool:
        try:
            return now - path.lstat().st_mtime > LEFTOVER_AGE
        except OSError:
            return False

    def remove(path: Path):
        try:
            shutil.rmtree(path) if path.is_dir() and not path.is_symlink() else path.unlink()
            done.append(path)
        except OSError:
            pass

    for folder in (apps_dir(), downloads_dir(), clones_dir()):
        for path in folder.glob(".*.part") if folder.is_dir() else []:
            if stale(path):
                remove(path)
    for path in downloads_dir().iterdir() if downloads_dir().is_dir() else []:
        if stale(path):
            remove(path)  # nothing stays here: each download is deleted once installed
    for path in bin_dir().glob(".*.couriercollie") if bin_dir().is_dir() else []:
        if stale(path):
            remove(path)
    for home in programs_dir().iterdir() if programs_dir().is_dir() else []:
        for path in list(home.glob(".*")):
            if not stale(path):
                continue
            if path.name.endswith(".old") and not (home / path.name[1:-len(".old")]).exists():
                try:
                    os.replace(path, home / path.name[1:-len(".old")])
                    done.append(path)
                except OSError:
                    pass
            elif path.name.endswith((".part", ".unpacking", ".old")):
                remove(path)
    return done


def downloads_dir() -> Path:
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "couriercollie" / "downloads"


@contextlib.contextmanager
def _downloaded(asset, others: list, progress, get_text):
    """The release's file, downloaded into a folder of its own in downloads_dir() and checked: (its path, whether it
    was checked against a published checksum, the SHA-256 of what was downloaded). Deleted afterwards, whatever
    happens."""
    downloads_dir().mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix=".", suffix=".part", dir=downloads_dir()))  # (two at once don't meet)
    name = Path(asset.name).name  # never a path from the site
    part, file = folder / f".{name}.part", folder / name
    try:
        verified, digest = _download_checked(asset, part, others, progress, get_text)
        os.replace(part, file)  # installers go by the file's name
        yield file, verified, digest
    finally:
        shutil.rmtree(folder, ignore_errors=True)


# Run as root: copy the package ($1, named $2) into a new folder only root can write to, check it's still the file
# that was checked (sha256 $3), then install that copy with the command that follows ($4…).
_CHANGED = 3
_INSTALL_COPY = (
    f'export PATH={SYSTEM_PATH}; '
    'src=$1; name=$2; sum=$3; shift 3; '
    'dir=$(mktemp -d) || exit 1; trap \'rm -rf "$dir"\' EXIT; '
    'cp -- "$src" "$dir/$name" || exit 1; '
    f'printf "%s  %s\\n" "$sum" "$dir/$name" | sha256sum -c --status - || exit {_CHANGED}; '
    'chmod 644 "$dir/$name"; chmod 755 "$dir"; '  # apt reads it as its own unprivileged user
    '"$@" "$dir/$name"'
)


# One install by a package manager (or Flatpak) at a time: each locks its database while it works, and a second at once
# would fail ("could not get lock"). Updating several things at once, the others wait here for their turn.
_PACKAGE_MANAGER = threading.Lock()
# What the package managers say when another program (Discover, a terminal) is installing at the moment.
_BUSY = re.compile(r"could not get lock|unable to lock database|system management is locked|another app is "
                   r"currently holding|database is locked", re.I)


def install_package(asset, others: list, kind: str, package: str = "", progress=None, installing=None,
                    get_text=fetch_text) -> tuple[str, str, bool, str]:
    """Downloads a release's package (an .rpm, .deb or Arch package, by `kind`), checks it, and installs it with this
    computer's package manager, which asks for the password. `package`: the name of the package you have, which the
    file must be. `installing()` is called when the package manager starts. Returns (package name, version, whether
    the download was checked against a published checksum, the package manager). The download is deleted after."""
    tool = packages.tool_for(kind)
    if not tool:
        raise UpdateError(f"There\u2019s no package manager here for {packages.A_LABEL[kind]}, so it wasn\u2019t "
                          "installed.")
    with _downloaded(asset, others, progress, get_text) as (file, verified, checked):
        with file.open("rb") as f:
            if not f.read(8).startswith(packages.MAGIC[kind]):
                raise UpdateError(f"{file.name} isn\u2019t {packages.A_LABEL[kind]}, so it wasn\u2019t installed.")
        try:
            found, version, arch = packages.file_info(kind, file)
        except ValueError as e:
            raise UpdateError(str(e)) from e
        if package and found != package:
            raise UpdateError(f"The new file is the package \u201c{found}\u201d, not \u201c{package}\u201d that you "
                              "have, so it wasn\u2019t installed. The project may have renamed it.")
        if not packages.suits(arch):
            raise UpdateError(f"The new file is for {arch} computers, not this one, so it wasn\u2019t installed.")
        # The checked file is in a folder you can write to, so as root it's first copied where only root can, and
        # checked there against what was downloaded (and checked): nothing can swap it between the download and the
        # package manager installing it.
        with _PACKAGE_MANAGER:
            if installing:
                installing()
            try:
                result = subprocess.run([*ROOT, "/bin/sh", "-c", _INSTALL_COPY, "sh", str(file), file.name, checked,
                                         *packages.INSTALL[tool]], capture_output=True, text=True,
                                        timeout=INSTALL_TIMEOUT)
            except subprocess.TimeoutExpired as e:
                raise UpdateError(f"{tool} took too long; check a terminal to see if it\u2019s still busy.") from e
            except OSError as e:
                raise UpdateError(f"Couldn\u2019t run {tool}: {e}") from e
    if ROOT and result.returncode in (126, 127):
        raise UpdateError("The password wasn\u2019t given, so nothing was installed.")
    if result.returncode == _CHANGED:
        raise UpdateError("The downloaded file changed after it was checked, so nothing was installed.")
    if result.returncode != 0 and _BUSY.search(result.stderr + result.stdout):
        raise UpdateError(f"Your package manager ({tool}) is busy with something else: another program is "
                          "installing or updating software. Try again once it\u2019s done.")
    if result.returncode != 0 and "remove is disabled" in result.stderr + result.stdout:  # (apt's --no-remove)
        raise UpdateError("Installing it would remove other packages it conflicts with, so it wasn\u2019t installed.")
    if result.returncode != 0:
        raise UpdateError(f"{tool} couldn\u2019t install it: {_last_line(result, tool)}")
    return found, version, verified, tool


def install_flatpak(asset, others: list, app_id: str = "", progress=None, get_text=fetch_text) -> tuple[str, bool]:
    """Downloads a release's Flatpak bundle, checks it, and installs it for you (flatpaks.py). `app_id`: the app you
    have, which the bundle must hold. Returns (the app's ID, whether the download was checked against a published
    checksum). The download is deleted afterwards."""
    with _downloaded(asset, others, progress, get_text) as (file, verified, _):
        found, arch = flatpaks.bundle_app(file)
        if not found:
            raise UpdateError(f"{file.name} isn\u2019t a Flatpak bundle, so it wasn\u2019t installed.")
        if app_id and found != app_id:
            raise UpdateError(f"The new file holds the app \u201c{found}\u201d, not \u201c{app_id}\u201d that you "
                              "have, so it wasn\u2019t installed. The project may have renamed it.")
        if arch != platform.machine():
            raise UpdateError(f"The new file is for {arch} computers, not this one, so it wasn\u2019t installed.")
        with _PACKAGE_MANAGER:
            result = flatpaks.install(file)
    if result is None:
        raise UpdateError("Couldn\u2019t run flatpak.")
    if result.returncode != 0:
        raise UpdateError(f"flatpak couldn\u2019t install it: {_last_line(result, 'flatpak')}")
    return found, verified
