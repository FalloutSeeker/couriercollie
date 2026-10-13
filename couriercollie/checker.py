"""Checking every tracked repo for updates.

Requests per check (DECISIONS.md, D7): one for a repo that follows releases; none for a branch (git ls-remote), plus
one or two to compare when your commit isn't the branch's newest. Scanned repos read their version from disk.
Once GitHub says its hourly limit is reached, the remaining GitHub repos aren't asked; they keep "not checked".

Results are kept in their own file (`state_path()`), not the settings file: the background checker writes them
while the window may be open, and the window owns the settings file. Nothing here installs anything.
"""

import dataclasses
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import assets, flatpaks, packages, scan, sources, updater
from .config import FOLLOW_BRANCH, NOT_INSTALLED, SOURCE_SCANNED, Settings, TrackedRepo
from .sources import RepoRef, SourceError

# What a check found.
UP_TO_DATE = "up-to-date"
UPDATE = "update"
NOT_INSTALLED_YET = "not-installed"
OTHER = "other"  # your version is ahead of, or not on, the followed branch: not an update
NO_RELEASES = "no-releases"
FAILED = "failed"
RATE_LIMITED = "rate-limited"
UNREACHABLE = "unreachable"  # the site didn't answer (no connection): says nothing about the repo

# A few repos are asked about at once: much quicker than one by one, without hammering a site.
CHECKS_AT_ONCE = 4


@dataclass
class Result:
    status: str
    text: str  # one line for the list, e.g. "Update available: v1.19.0"
    newest: str = ""  # the newest version seen (a tag, or a branch's newest commit)
    checked_at: str = ""
    retry_after: str = ""  # when a rate limit ends (ISO time), if that's why it wasn't checked
    # This is the previous check's result, kept because this time the site couldn't be asked (its hourly limit, or no
    # answer): an update found before is still an update.
    not_rechecked: bool = False


@dataclass
class State:
    last_run: str = ""  # when the last check of everything finished (ISO time)
    results: dict[str, Result] = field(default_factory=dict)
    # The newest version already announced for each repo, so a notification is only sent for something new.
    notified: dict[str, str] = field(default_factory=dict)


def state_path() -> Path:
    if env := os.environ.get("COURIERCOLLIE_STATE"):
        return Path(env)
    base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    return base / "couriercollie" / "checks.json"


def load_state(path: Path | None = None) -> State:
    """The saved results; empty if there are none yet, or the file can't be read (it's only a record of checks)."""
    path = path or state_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return State(
            last_run=str(data.get("last_run", "")),
            results={k: Result(**v) for k, v in data.get("results", {}).items()},
            notified={str(k): str(v) for k, v in data.get("notified", {}).items()},
        )
    except (OSError, ValueError, TypeError, AttributeError):
        return State()


def save_state(state: State, path: Path | None = None) -> None:
    path = path or state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(asdict(state), indent=1), encoding="utf-8")
    os.replace(tmp, path)


def now() -> datetime:
    return datetime.now(timezone.utc)


def stamp() -> str:
    return now().isoformat(timespec="seconds")


def due(settings: Settings, state: State, at: datetime | None = None) -> bool:
    """Whether an automatic check is due: automatic checks are on, and the interval has passed since the last one."""
    if not settings.auto_check:
        return False
    if not state.last_run:
        return True
    try:
        last = datetime.fromisoformat(state.last_run)
    except ValueError:
        return True
    return (at or now()) - last >= timedelta(hours=settings.check_interval_hours)


# ---------------------------------------------------------------------------------------------------------------------
# One repo


def _yours(repo: TrackedRepo) -> tuple[str, bool]:
    """Your version, and whether it's still there: read from disk for one on this computer (it may have been updated,
    or removed, outside the app)."""
    if repo.source == SOURCE_SCANNED and repo.local_path:
        version, present = scan.version_on_disk(repo.local_path, releases=repo.follow != FOLLOW_BRANCH)
        return version or repo.installed, present
    return repo.installed, True


# What the list says when what was on this computer was removed outside the app.
GONE = "Not found on this computer"


# A check only needs the newest release, so it asks for a few (sources.newest_releases).
CHECK_RELEASES = 5


def installed_with(managed_by: str) -> str:
    """How the list and the page name what installed it: "Installed with Package Manager", or "… with Flatpak". Not
    which package manager: that's the same on every repo of this computer, so it says nothing."""
    return f"Installed with {'Flatpak' if managed_by == 'Flatpak' else 'Package Manager'}"


def releases_result(shown: list[sources.Release], yours: str, managed_by: str = "", found: bool = False,
                    pattern: str = "") -> Result:
    """The result for a repo following releases, from the releases it shows (newest first) and your version.
    `managed_by`: what installed it and keeps it updated ("dnf"), if that's the package manager or Flatpak: then
    it's never an update here. `found`: a scan found it on this computer, so without a version it's there, unknown.
    `pattern`: the file you follow, which the newest release must have for it to be an update you can install."""
    if not shown:
        return Result(NO_RELEASES, "No releases yet")
    newest = shown[0].tag
    if managed_by:
        return Result(OTHER, installed_with(managed_by), newest)
    if not yours and found:  # e.g. an AppImage renamed without its version
        return Result(NOT_INSTALLED_YET, f"Version unknown · newest {newest}", newest)
    if not yours or yours == NOT_INSTALLED:
        return Result(NOT_INSTALLED_YET, f"Not installed · newest {newest}", newest)
    if assets.same_version(yours, newest):
        return Result(UP_TO_DATE, "Up to date", newest)
    if assets.is_newer(yours, newest):  # (the newest release was taken down, or yours came from elsewhere): not older
        return Result(UP_TO_DATE, f"Up to date (newer than {newest})", newest)
    if pattern and not assets.pick(pattern, [a.name for a in shown[0].assets]):
        # The project dropped or renamed your file: nothing to install, so not an update; the page says what to do.
        return Result(OTHER, f"Your file isn\u2019t in {newest}", newest)
    return Result(UPDATE, f"Update available: {newest}", newest)


def branch_result(branch: str, head: str, yours: str, c: sources.Comparison | None, disk: str = "",
                  managed_by: str = "") -> Result:
    """The result for a repo following a branch, from its newest commit, your version, how they compare (None: they
    couldn't be compared), for a clone the branch it's on, and what else installed it (as for releases_result)."""
    if managed_by:
        return Result(OTHER, installed_with(managed_by), head)
    if not yours or yours == NOT_INSTALLED:
        return Result(NOT_INSTALLED_YET, f"Not installed · following {branch}", head)
    if yours == head or (c and c.relation == sources.SAME):
        return Result(UP_TO_DATE, "Up to date", head)
    if c is None:
        return Result(OTHER, f"Couldn’t compare your version with {branch}", head)
    if c.relation == sources.BEHIND:
        count = "1 new commit" if c.total == 1 else f"{c.total} new commits"
        return Result(UPDATE, f"{count} on {branch}", head)
    if c.relation == sources.AHEAD:
        if disk and disk != branch:
            return Result(OTHER, f"Nothing new on {branch} (your clone is on {disk})", head)
        return Result(OTHER, f"Ahead of {branch}", head)
    return Result(OTHER, f"Not comparable with {branch}", head)


def _check_releases(repo: TrackedRepo, ref: RepoRef, yours: str) -> Result:
    rels = sources.newest_releases(ref, repo.host, CHECK_RELEASES, repo.prereleases)
    return releases_result([r for r in rels if repo.prereleases or not r.prerelease], yours, repo.managed_by,
                           repo.source == SOURCE_SCANNED, repo.asset_pattern)


def _check_branch(repo: TrackedRepo, ref: RepoRef, yours: str) -> Result:
    default, branches = sources.branches(ref)  # git, not the API
    branch = repo.branch or default
    head = next((b.sha for b in branches if b.name == branch), "")
    if not head:
        return Result(FAILED, f"Couldn’t check: there’s no branch “{branch}” anymore")
    c = None
    if yours and yours not in (NOT_INSTALLED, head):
        clone = repo.local_path if repo.source == SOURCE_SCANNED else ""
        try:
            c = updater.compare_here(clone, yours, head) or sources.compare(ref, repo.host, yours, head)
        except sources.RateLimited:
            raise  # not "couldn't compare": check_repo marks it, so the rest of GitHub's repos aren't asked
        except SourceError:
            pass  # "couldn't compare"
    disk = scan.branch_on_disk(repo.local_path) if repo.source == SOURCE_SCANNED and repo.local_path else ""
    return branch_result(branch, head, yours, c, disk, repo.managed_by)


def check_repo(repo: TrackedRepo, github_limited: threading.Event | None = None) -> Result:
    """Check one repo. `github_limited` is shared by a check of everything: once GitHub says its hourly limit is
    reached, the other GitHub repos aren't asked."""
    ref = RepoRef.from_id(repo.id)
    if github_limited is not None and github_limited.is_set() and repo.host == "github":
        return Result(RATE_LIMITED, "Not checked: GitHub’s hourly limit was reached")
    try:
        yours, present = _yours(repo)
        if repo.follow == FOLLOW_BRANCH:
            result = _check_branch(repo, ref, yours)
        else:
            result = _check_releases(repo, ref, yours)
        if not present and not repo.managed_by:
            result = Result(NOT_INSTALLED_YET, GONE, result.newest)  # removed outside the app: not up to date
    except sources.RateLimited as e:
        if repo.host == "github" and github_limited is not None:
            github_limited.set()
        until = f" (until {e.reset_at.astimezone():%H:%M})" if e.reset_at else ""
        return Result(RATE_LIMITED, f"Not checked: {ref.domain}’s hourly limit was reached{until}",
                      retry_after=e.reset_at.isoformat() if e.reset_at else "", checked_at=stamp())
    except sources.Unreachable as e:
        return Result(UNREACHABLE, f"Couldn’t check: {e}", checked_at=stamp())
    except SourceError as e:
        return Result(FAILED, f"Couldn’t check: {e}", checked_at=stamp())
    except Exception as e:  # noqa: BLE001 - one repo's surprise mustn't stop the check of all the others
        return Result(FAILED, f"Couldn’t check: something unexpected went wrong ({type(e).__name__}).",
                      checked_at=stamp())
    result.checked_at = stamp()
    return result


def recheck_against(old: Result, yours: str, by_branch: bool, branch: str = "") -> Result:
    """A check's result redone for a different version of yours, against the same newest version, without asking
    the site. A branch commit that's neither the newest nor known to be behind it can't be judged this way, so that
    keeps the old result until the next check."""
    newest = old.newest
    if not yours or yours == NOT_INSTALLED:
        what = f"following {branch}" if by_branch else f"newest {newest}"
        return dataclasses.replace(old, status=NOT_INSTALLED_YET, text=f"Not installed \u00b7 {what}",
                                   not_rechecked=False)
    same = yours == newest or (not by_branch and assets.same_version(yours, newest))
    if same:
        return dataclasses.replace(old, status=UP_TO_DATE, text="Up to date", not_rechecked=False)
    if not by_branch:
        return dataclasses.replace(old, status=UPDATE, text=f"Update available: {newest}", not_rechecked=False)
    return old


# ---------------------------------------------------------------------------------------------------------------------
# Everything


def find_managed(repos: list[TrackedRepo]) -> dict[str, str]:
    """What installed each repo's project, for those the package manager or Flatpak installed and so keep up to date:
    "dnf", "Flatpak", etc. Those are never updates here. The installed packages and Flatpaks are read once for all."""
    homepages, apps = packages.installed_homepages(), flatpaks.installed_apps()
    found = {}
    for r in repos:
        ids = [r.id, *r.aliases]
        if system := packages.managed_by_system(ids, homepages=homepages, website=r.homepage):
            found[r.id] = system[0]
        elif flatpaks.managed_by_flatpak(ids, apps=apps):
            found[r.id] = "Flatpak"
    return found


def check_all(repos: list[TrackedRepo], previous: State | None = None) -> tuple[State, list[str]]:
    """Check every repo, a few at a time. Returns the new state, and the repos with an update that hasn't been
    announced before (for a notification). Repos that couldn't be checked keep their previous result's version.
    Each repo's managed_by is brought up to date first (find_managed), even for repos whose page was never opened."""
    previous = previous or State()
    managed = find_managed(repos)
    for r in repos:
        r.managed_by = managed.get(r.id, "")
    github_limited = threading.Event()
    with ThreadPoolExecutor(max_workers=CHECKS_AT_ONCE) as pool:
        results = dict(zip((r.id for r in repos), pool.map(lambda r: check_repo(r, github_limited), repos)))
    # GitHub repos checked before the limit was hit kept their answers; ones skipped after it get the reset time
    # from the repo that hit it.
    reset = next((r.retry_after for r in results.values() if r.status == RATE_LIMITED and r.retry_after), "")
    for r in results.values():
        if r.status == RATE_LIMITED and not r.retry_after:
            r.retry_after = reset
    # A repo the limit stopped, or whose site didn't answer, keeps its last result (an update is still an update),
    # marked as not rechecked. (retry_after says which: set for the hourly limit, empty for no answer.)
    for repo_id, r in list(results.items()):
        old = previous.results.get(repo_id)
        if r.status in (RATE_LIMITED, UNREACHABLE) and old and old.status not in (RATE_LIMITED, UNREACHABLE, FAILED):
            results[repo_id] = dataclasses.replace(old, not_rechecked=True, retry_after=r.retry_after)
    # If no site answered (no connection yet after waking up, say), the check doesn't count: the timer tries again
    # within the hour instead of waiting a whole interval.
    answered = not results or any(r.status not in (RATE_LIMITED, UNREACHABLE) and not r.not_rechecked
                                  for r in results.values())
    state = State(last_run=stamp() if answered else previous.last_run, results=results,
                  notified={k: v for k, v in previous.notified.items() if k in results})
    fresh = []
    for repo_id, r in results.items():
        if r.status == UPDATE and not r.not_rechecked and previous.notified.get(repo_id) != r.newest:
            fresh.append(repo_id)
            state.notified[repo_id] = r.newest
    return state, fresh
