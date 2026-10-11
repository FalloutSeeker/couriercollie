"""Updating what's tracked (stage 5). Only ever runs because you clicked Update (DECISIONS.md, D4, D6).

Git clones: the new commits on the followed branch are pulled, fast-forward only, so nothing of yours is merged,
rebased or thrown away. A project's install script is never run here; it's shown to you first, and runs in a terminal
window you can watch (and type your password into, if it asks).
"""

import os
import shlex
import shutil
import subprocess
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
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"}
    try:
        return subprocess.run(["git", "-c", f"safe.directory={path}", "-C", path, *args], capture_output=True,
                              text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired as e:
        raise UpdateError("Git took too long to answer; check your connection and try again.") from e
    except OSError as e:
        raise UpdateError(f"Couldn’t run git: {e}") from e


def _out(path: str, *args: str) -> str:
    result = _git(path, *args)
    return result.stdout.strip() if result.returncode == 0 else ""


def _last_line(result: subprocess.CompletedProcess) -> str:
    lines = [line for line in (result.stderr or result.stdout).splitlines() if line.strip()]
    return lines[-1].strip() if lines else f"git exited with {result.returncode}"


def _remote_for(path: str, repo_ids: list[str]) -> str:
    """The clone's remote that points at the tracked project (a scan matched it by address), else "origin"."""
    wanted = {i.lower() for i in repo_ids}
    for name in _out(path, "remote").splitlines():
        try:
            if sources.parse_url(_out(path, "remote", "get-url", name)).id.lower() in wanted:
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
    on = _out(path, "symbolic-ref", "--short", "-q", "HEAD")
    if on != branch:
        where = f"on {on}" if on else "not on any branch"
        raise UpdateError(f"Your clone is {where}, not {branch}, so it wasn\u2019t changed. Switch it to {branch} "
                          f"(git switch {shlex.quote(branch)}), or follow {on or 'another branch'} instead.")
    before = _out(path, "rev-parse", "HEAD")
    remote = _remote_for(path, repo_ids)
    result = _run_steps(path, [["fetch", "--quiet", "--no-tags", remote, branch],
                               ["merge", "--ff-only", "--quiet", "FETCH_HEAD"]], as_root)
    if result.returncode != 0:
        raise _explain(result)
    after = _out(path, "rev-parse", "HEAD")
    count = int(_out(path, "rev-list", "--count", f"{before}..{after}") or 0) if before and after else 0
    return before, after, count


def checkout_release(path: str, tag: str, repo_ids: list[str]) -> tuple[str, str]:
    """Moves the clone at `path` to the release `tag`, fetched from the project. Returns (commit before, the branch it
    was on, or ""). The branch itself isn't changed, so `git switch <branch>` goes back. Refuses if that would leave
    commits behind that aren't on any branch or tag."""
    as_root = _as_root(path)
    on = _out(path, "symbolic-ref", "--short", "-q", "HEAD")
    before = _out(path, "rev-parse", "HEAD")
    if not on and before and not _out(path, "for-each-ref", "--count=1", "--contains", before):
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
