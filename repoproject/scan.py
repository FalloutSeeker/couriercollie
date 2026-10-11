"""Turning what a scan finds into tracked repos, without duplicates.

Finding things on disk is stage 3 (PLAN.md). This part decides what happens with each find: a repo already on the
list (added by hand, installed from the app, or found before) is updated in place and marked as scanned; only
genuinely new ones are added.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from .config import FOLLOW_BRANCH, SOURCE_SCANNED, Config, TrackedRepo


@dataclass
class Found:
    """Something a scan found on this computer."""

    id: str  # address as found on disk, e.g. from a clone's remote: may be an old name of the project
    name: str
    url: str
    host: str
    path: str  # where on this computer
    kind: str  # assets.KIND_*: "git" for a clone
    version: str  # what's on disk: a commit for a clone, a release tag for a downloaded app; "" if unknown
    branch: str = ""  # for clones: the branch that's checked out


@dataclass
class MergeResult:
    added: list[TrackedRepo]
    updated: list[TrackedRepo]  # already on the list; now marked as scanned


def merge(config: Config, found: list[Found], resolve: Callable[[str], str | None] = lambda _id: None) -> MergeResult:
    """Add or update tracked repos from scan finds.

    `resolve` gives a project's current address for an old one (the sites redirect renamed and moved projects), or
    None if unknown. It's only asked when an address doesn't match anything on the list directly.
    """
    result = MergeResult(added=[], updated=[])
    for item in found:
        repo = config.find_any(item.id)
        if repo is None and (current := resolve(item.id)):
            repo = config.find_any(current)
            if repo is not None:
                # Remember the old address, so the next scan matches without asking the site.
                repo.aliases.append(item.id)
        if repo is None:
            repo = TrackedRepo(
                id=item.id, name=item.name, url=item.url, host=item.host,
                added_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            )
            config.repos.append(repo)
            result.added.append(repo)
        elif repo not in result.updated:
            result.updated.append(repo)
        _apply(repo, item)
    return result


def _apply(repo: TrackedRepo, item: Found) -> None:
    """What's on disk wins over what was set by hand: it's the version you actually have."""
    repo.source = SOURCE_SCANNED
    repo.local_path = item.path
    if item.kind == "git":
        # A clone's version is a commit, so it's followed by branch.
        repo.follow, repo.kind = FOLLOW_BRANCH, "git"
        if item.branch:
            repo.branch = item.branch
    if item.version:
        repo.installed = item.version
