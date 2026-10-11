"""Updating what's tracked (stage 5). Only ever runs because you clicked Update (DECISIONS.md, D4, D6).

RPMs: the new .rpm is downloaded, checked, and installed by dnf, which asks for your password.

Programs (an archive with a ready-made program inside): each version is unpacked into its own folder, and a link in
~/.local/bin starts it; updating switches the link, then removes the old version.

AppImages: the new file is downloaded next to yours, checked against the project's published checksum (and that it
really is an AppImage), then swapped in; the old one is removed once the new one is in place.

Git clones: the new commits on the followed branch are pulled, fast-forward only, so nothing of yours is merged,
rebased or thrown away. A project's install script is never run here; it's shown to you first, and runs in a terminal
window you can watch (and type your password into, if it asks).
"""

import hashlib
import os
import platform
import shlex
import shutil
import subprocess
import tarfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from . import sources

# Fetching can take a while for a big project on a slow connection.
FETCH_TIMEOUT = 300
# As root, the time also covers typing the password.
ROOT_TIMEOUT = 600
# How a clone that belongs to the system is updated: through polkit, which asks for your password (DECISIONS.md, D6).
ROOT = ["pkexec"]
# Names an install script goes by, in the clone's top folder. "uninstall.sh" and the like are left out on purpose.
INSTALL_SCRIPTS = ("install.sh", "install", "setup.sh")
# Scripts bigger than this aren't shown (or offered): something that large isn't a script to read before running.
SCRIPT_MAX_BYTES = 256 * 1024


class UpdateError(Exception):
    """Why an update couldn't be done, for the user."""


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


def git_out(path: str, *args: str, timeout: int = 30) -> str:
    """A git command's output in the clone at `path`, or "" if it fails. Never asks for anything."""
    try:
        result = _git(path, *args, timeout=timeout)
    except UpdateError:
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _last_line(result: subprocess.CompletedProcess) -> str:
    lines = [line for line in (result.stderr or result.stdout).splitlines() if line.strip()]
    return lines[-1].strip() if lines else f"git exited with {result.returncode}"


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


def _as_root(path: str) -> bool:
    """Whether the clone has to be changed as root: it belongs to the system. One that belongs to another person is
    left alone: changing it as root would leave files in it that they can't change."""
    if not (Path(path) / ".git").exists():
        raise UpdateError(f"There\u2019s no git clone at {path} any more.")
    if _writable(path):
        return False
    if _owner(path) == 0 and (not ROOT or shutil.which(ROOT[0])):
        return True
    if _owner(path) == os.geteuid():
        raise UpdateError(f"{path} is yours, but its permissions don\u2019t let it be changed, so it wasn\u2019t.")
    raise UpdateError(f"{path} belongs to another user, so it can\u2019t be updated from here. As that user, in a "
                      f"terminal: cd {shlex.quote(path)} && git pull --ff-only")


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
        for step in steps:
            result = _git(path, *step, timeout=FETCH_TIMEOUT)
            if result.returncode != 0:
                break
        return result
    git = shutil.which("git") or "git"
    script = "export LC_ALL=C GIT_TERMINAL_PROMPT=0; " + " && ".join(
        shlex.join([git, "-C", path, *step]) for step in steps)
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
    """Install scripts in the clone's top folder, by name."""
    folder = Path(path)
    return [n for n in INSTALL_SCRIPTS
            if (folder / n).is_file() and (folder / n).stat().st_size <= SCRIPT_MAX_BYTES]


def script_text(path: str, name: str) -> str:
    """The script, to read before running it."""
    if name not in install_scripts(path):
        raise UpdateError(f"There’s no {name} in {path}.")
    return (Path(path) / name).read_text(encoding="utf-8", errors="replace")


def _interpreter(script: Path) -> list[str]:
    """How to run the script: itself if it may be run, else what its first line names, else sh."""
    if os.access(script, os.X_OK):
        return [f"./{script.name}"]
    with script.open("rb") as f:
        first = f.readline().decode("utf-8", "replace").strip()
    if first.startswith("#!") and (words := shlex.split(first[2:])):
        return [*words, f"./{script.name}"]
    return ["sh", f"./{script.name}"]


def terminal_command(path: str, name: str) -> tuple[str, list[str]]:
    """(program, arguments) that run the script in a terminal window, from the clone's folder, kept open after it
    finishes so its output can be read."""
    if name not in install_scripts(path):
        raise UpdateError(f"There’s no {name} in {path}.")
    run = _interpreter(Path(path) / name)
    if konsole := shutil.which("konsole"):
        return konsole, ["--workdir", path, "--hold", "-e", *run]
    if xdg := shutil.which("xdg-terminal-exec"):
        # No "keep open" option here, so the script's window waits for Enter when it's done.
        line = shlex.join(run) + "; echo; read -r -p 'Finished. Press Enter to close.' _"
        return xdg, [f"--dir={path}", "sh", "-c", line]
    raise UpdateError("No terminal app was found to run it in (Konsole, or one that xdg-terminal-exec knows).")


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
    return Path(os.environ.get("REPOPROJECT_APPS") or Path.home() / "Applications")


def menu_dir() -> Path:
    return _data_home() / "applications"


def _checksum_files(asset_name: str, others: list) -> list:
    """Checksum files in the same release that may list `asset_name`: "<file>.sha256" first, then shared ones."""
    own = [a for a in others if a.name.lower() in (asset_name.lower() + ".sha256", asset_name.lower() + ".sha256sum")]
    shared = [a for a in others if a not in own and a.name != asset_name and len(a.name) < 80
              and any(n in a.name.lower() for n in _CHECKSUM_NAMES) and (a.size or 0) < 1024 * 1024]
    return own + shared


def _find_sha256(text: str, asset_name: str) -> str:
    """The SHA-256 for `asset_name` in a checksum file: "<hex>  <name>" lines, or a file holding just the hex."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in lines:
        parts = line.replace("*", " ").split()
        if len(parts) >= 2 and parts[-1].lstrip("./") == asset_name and _is_sha256(parts[0]):
            return parts[0].lower()
    if len(lines) == 1 and _is_sha256(lines[0].split()[0]):
        return lines[0].split()[0].lower()
    return ""


def _is_sha256(text: str) -> bool:
    return len(text) == 64 and all(c in "0123456789abcdefABCDEF" for c in text)


def expected_sha256(asset, others: list, get_text) -> str:
    """The checksum the project published for `asset`: the site's own (GitHub gives one for each file, no request),
    else from a checksum file in the release (one small download). "" if there's none."""
    if asset.digest.startswith("sha256:") and _is_sha256(asset.digest[7:]):
        return asset.digest[7:].lower()
    for f in _checksum_files(asset.name, others):
        try:
            if found := _find_sha256(get_text(f.url), asset.name):
                return found
        except (OSError, ValueError, sources.SourceError):
            continue
    return ""


def fetch_text(url: str, limit: int = 1024 * 1024) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": sources.USER_AGENT})
    with urllib.request.urlopen(req, timeout=sources.TIMEOUT) as resp:
        return resp.read(limit).decode("utf-8", "replace")


def download(url: str, dest: Path, size: int | None, progress=None) -> str:
    """Downloads `url` to `dest`, returning its SHA-256. `progress(done, total)` is called now and then."""
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
    except (OSError, urllib.error.URLError) as e:
        dest.unlink(missing_ok=True)
        raise UpdateError(f"The download didn’t finish: {getattr(e, 'reason', None) or e}") from e
    except UpdateError:
        dest.unlink(missing_ok=True)
        raise
    return digest.hexdigest()


def is_appimage(path: Path) -> bool:
    """An AppImage is a program (ELF) with "AI" and its type (1 or 2) at byte 8."""
    with path.open("rb") as f:
        head = f.read(11)
    return head[:4] == b"\x7fELF" and head[8:10] == b"AI" and head[10:11] in (b"\x01", b"\x02")


def _download_checked(asset, part: Path, others: list, progress, get_text) -> bool:
    """Downloads `asset` to `part` and checks it against the checksum the project published. Returns whether there
    was one to check against. A download that doesn't match is deleted, and that's the end of it."""
    got = download(asset.url, part, asset.size, progress)
    expected = expected_sha256(asset, others, get_text)
    if expected and got != expected:
        part.unlink(missing_ok=True)
        raise UpdateError("The download doesn\u2019t match the checksum the project published, so it was thrown away. "
                          "Try again later; if it keeps happening, the file on the site may have been tampered with.")
    return bool(expected)


def install_appimage(asset, others: list, folder: Path, old: Path | None,
                     progress=None, get_text=fetch_text) -> tuple[Path, bool]:
    """Downloads `asset` (a release's AppImage) into `folder`, checks it, and puts it in place of `old` (if any),
    which is then removed. Returns (the new file, whether it was checked against a published checksum)."""
    folder.mkdir(parents=True, exist_ok=True)
    if not os.access(folder, os.W_OK):
        raise UpdateError(f"{folder} belongs to another user (often the system), so the new version can’t be put "
                          "there from here.")
    name = Path(asset.name).name  # never a path from the site
    part = folder / f".{name}.part"
    try:
        verified = _download_checked(asset, part, others, progress, get_text)
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
    " ` $ and \\), then the file's own (each backslash doubled)."""
    escaped = str(path).replace("\\", "\\\\\\\\")
    for ch in '"`$':
        escaped = escaped.replace(ch, "\\\\" + ch)
    return f'"{escaped}"'


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


def write_menu_entry(repo_id: str, name: str, app: Path, icon: str) -> Path:
    """A menu entry (KDE launcher) for an AppImage the app installed. Marked as the app's, so it's kept up to date."""
    entry = menu_dir() / f"repoproject-{repo_id.replace('/', '-').lower()}.desktop"
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text("\n".join([
        "[Desktop Entry]",
        "Type=Application",
        f"Name={name}",
        f"Exec={_desktop_quote(app)} %U",
        f"TryExec={app}",
        f"Icon={icon or 'application-vnd.appimage'}",
        "Terminal=false",
        "Categories=Utility;",
        "Comment=Installed by RepoProject",
        f"X-RepoProject-Repo={repo_id}",
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
    return _data_home() / "repoproject" / "programs"


def bin_dir() -> Path:
    """Where the link to each program goes: on Fedora, already where the terminal looks for commands."""
    return Path(os.environ.get("REPOPROJECT_BIN") or Path.home() / ".local" / "bin")


def _folder_name(text: str) -> str:
    """A repo or version as one folder name."""
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in text).strip(".") or "_"


def _unpack(archive: Path, into: Path) -> None:
    """Unpacks an archive into `into`, refusing anything that would land outside it, links that point outside it,
    device files, and archives that unpack to more than UNPACKED_MAX_BYTES."""
    into.mkdir(parents=True)
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
        verified = _download_checked(asset, part, others, progress, get_text)
        _unpack(part, unpacking)
        program = choose_program(unpacking, wanted, list(hints))
        link = bin_dir() / program.name
        before = link.resolve() if link.is_symlink() else None
        if (link.exists() or link.is_symlink()) and not (before and before.is_relative_to(home.resolve())):
            raise UpdateError(f"{link} already exists and wasn’t put there by RepoProject, so it wasn’t "
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
        new_link = bin_dir() / f".{program.name}.repoproject"
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
# RPMs: the release's .rpm is downloaded, checked, and installed by dnf, as root, which asks for your password
# (DECISIONS.md, D4, D6). Only RPMs installed from a downloaded file are tracked: dnf doesn't update those itself.

DNF = ["dnf"]
RPM_MAGIC = b"\xed\xab\xee\xdb"
# Installing can take a while (dnf may download what the package needs), plus typing the password.
DNF_TIMEOUT = 1800


def downloads_dir() -> Path:
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "repoproject" / "downloads"


def rpm_info(path: Path) -> tuple[str, str, str]:
    """(name, version, architecture) from an .rpm file's header, read without installing it."""
    try:
        result = subprocess.run(["rpm", "-qp", "--qf", "%{NAME}|%{VERSION}|%{ARCH}", str(path)], capture_output=True,
                                text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise UpdateError(f"Couldn’t read the RPM: {e}") from e
    parts = result.stdout.strip().split("|")
    if result.returncode != 0 or len(parts) != 3:
        raise UpdateError("The download isn’t a readable RPM, so it wasn’t installed.")
    return parts[0], parts[1], parts[2]


def install_rpm(asset, others: list, package: str = "", progress=None, installing=None,
                get_text=fetch_text) -> tuple[str, str, bool]:
    """Downloads a release's .rpm, checks it, and installs it with dnf (asking for the password). `package`: the name
    of the package you have, which the file must be. `installing()` is called when dnf starts. Returns (package name,
    version, whether the download was checked against a published checksum). The download is deleted afterwards."""
    folder = downloads_dir()
    folder.mkdir(parents=True, exist_ok=True)
    name = Path(asset.name).name
    part, file = folder / f".{name}.part", folder / name
    try:
        verified = _download_checked(asset, part, others, progress, get_text)
        with part.open("rb") as f:
            if f.read(4) != RPM_MAGIC:
                raise UpdateError(f"{name} isn’t an RPM, so it wasn’t installed.")
        os.replace(part, file)  # dnf needs the .rpm name
        rpm_name, version, arch = rpm_info(file)
        if package and rpm_name != package:
            raise UpdateError(f"The new file is the package “{rpm_name}”, not “{package}” that you "
                              "have, so it wasn’t installed. The project may have renamed it.")
        if arch not in (platform.machine(), "noarch"):
            raise UpdateError(f"The new file is for {arch} computers, not this one, so it wasn’t installed.")
        if installing:
            installing()
        try:
            result = subprocess.run([*ROOT, *DNF, "install", "-y", str(file)], capture_output=True, text=True,
                                    timeout=DNF_TIMEOUT)
        except subprocess.TimeoutExpired as e:
            raise UpdateError("dnf took too long; check Discover or a terminal to see if it’s still busy.") from e
        except OSError as e:
            raise UpdateError(f"Couldn’t run dnf: {e}") from e
        if ROOT and result.returncode in (126, 127):
            raise UpdateError("The password wasn’t given, so nothing was installed.")
        if result.returncode != 0:
            raise UpdateError(f"dnf couldn’t install it: {_last_line(result)}")
        return rpm_name, version, verified
    finally:
        part.unlink(missing_ok=True)
        file.unlink(missing_ok=True)
