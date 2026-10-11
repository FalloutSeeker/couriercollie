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
# Names an install script goes by, in the clone's top folder. "uninstall.sh" and the like are left out on purpose.
INSTALL_SCRIPTS = ("install.sh", "install", "setup.sh")
# Scripts bigger than this aren't shown (or offered): something that large isn't a script to read before running.
SCRIPT_MAX_BYTES = 256 * 1024


class UpdateError(Exception):
    """Why an update couldn't be done, for the user."""


def _git(path: str, *args: str, timeout: int = 30) -> subprocess.CompletedProcess:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"}
    try:
        return subprocess.run(["git", "-C", path, *args], capture_output=True, text=True, timeout=timeout, env=env)
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


def pull(path: str, branch: str, repo_ids: list[str]) -> tuple[str, str, int]:
    """Brings the clone at `path` up to the newest commit on `branch`. Returns (commit before, commit after, how many
    new commits). Refuses, with the reason, anything that isn't a plain fast-forward of the branch you're on."""
    if not (Path(path) / ".git").exists():
        raise UpdateError(f"There’s no git clone at {path} any more.")
    if not os.access(Path(path) / ".git", os.W_OK):
        raise UpdateError(f"{path} belongs to another user (often the system), so it can’t be updated from here. "
                          f"In a terminal: cd {shlex.quote(path)} && sudo git pull --ff-only")
    on = _out(path, "symbolic-ref", "--short", "-q", "HEAD")
    if on != branch:
        where = f"on {on}" if on else "not on any branch"
        raise UpdateError(f"Your clone is {where}, not {branch}, so it wasn’t changed. Switch it to {branch} "
                          f"(git switch {shlex.quote(branch)}), or follow {on or 'another branch'} instead.")
    before = _out(path, "rev-parse", "HEAD")
    remote = _remote_for(path, repo_ids)
    fetched = _git(path, "fetch", "--quiet", "--no-tags", remote, branch, timeout=FETCH_TIMEOUT)
    if fetched.returncode != 0:
        raise UpdateError(f"Couldn’t download the new commits: {_last_line(fetched)}")
    merged = _git(path, "merge", "--ff-only", "--quiet", "FETCH_HEAD")
    if merged.returncode != 0:
        said = (merged.stderr + merged.stdout).lower()  # the reason may come before git's last line ("Aborting")
        if "fast-forward" in said:
            raise UpdateError("Your clone has commits of its own that aren’t on the project’s branch, so it "
                              "wasn’t changed. Pull it yourself in a terminal to choose how to combine them.")
        if "overwritten" in said or "local changes" in said:
            raise UpdateError("Files you changed in the clone are also changed by the new commits, so it wasn’t "
                              "changed. Commit or stash your changes, then update again.")
        raise UpdateError(f"Couldn’t update the clone: {_last_line(merged)}")
    after = _out(path, "rev-parse", "HEAD")
    count = int(_out(path, "rev-list", "--count", f"{before}..{after}") or 0) if before and after else 0
    return before, after, count


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
