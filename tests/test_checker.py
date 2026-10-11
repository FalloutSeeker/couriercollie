import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from couriercollie import checker, sources
from couriercollie.config import Settings, TrackedRepo
from tests.test_scan import make_clone


def release(tag, prerelease=False):
    return sources.Release(tag, tag, None, prerelease, "", "")


class Fakes:
    """Stand-ins for the sites. Counts requests."""

    def __init__(self):
        self.requests = []
        self.releases = {}
        self.branches = {}
        self.relations = {}
        self.limited = set()

    def install(self, case):
        saved = (sources.releases, sources.branches, sources.compare)
        case.addCleanup(lambda: setattr(sources, "releases", saved[0]) or setattr(sources, "branches", saved[1])
                        or setattr(sources, "compare", saved[2]))
        sources.releases, sources.branches, sources.compare = self.get_releases, self.get_branches, self.compare

    def _ask(self, what, ref):
        self.requests.append((what, ref.id))
        if ref.id in self.limited:
            raise sources.RateLimited("github.com says too many requests were made.",
                                      datetime(2026, 10, 11, 2, 24, tzinfo=timezone.utc))

    def get_releases(self, ref, host, count=sources.RELEASES_PER_PAGE):
        self._ask("releases", ref)
        return self.releases[ref.id][:count]

    def get_branches(self, ref):
        return "main", self.branches[ref.id]  # git ls-remote: not a request to the API

    def compare(self, ref, host, yours, head):
        self._ask("compare", ref)
        return sources.Comparison(self.relations.get(ref.id, sources.BEHIND), 2)


def repo(repo_id, **kw):
    return TrackedRepo(id=repo_id, name=repo_id.rsplit("/", 1)[-1], url="", host=kw.pop("host", "github"), **kw)


class CheckRepoTest(unittest.TestCase):
    def setUp(self):
        self.fakes = Fakes()
        self.fakes.install(self)
        self.fakes.releases["github.com/a/app"] = [release("v2.0-rc1", True), release("v1.19.0"), release("v1.18.2")]
        self.fakes.branches["gitgud.io/g/smod"] = [sources.Branch("main", "h" * 40), sources.Branch("dev", "d" * 40)]

    def check(self, r):
        return checker.check_repo(r)

    def test_releases(self):
        self.assertEqual(self.check(repo("github.com/a/app", installed="v1.18.2")).text, "Update available: v1.19.0")
        self.assertEqual(self.check(repo("github.com/a/app", installed="v1.19.0")).status, checker.UP_TO_DATE)
        self.assertEqual(self.check(repo("github.com/a/app", installed="1.19.0")).status, checker.UP_TO_DATE)
        self.assertEqual(self.check(repo("github.com/a/app", installed="-")).text, "Not installed · newest v1.19.0")
        # Pre-releases count only if they're shown.
        self.assertEqual(self.check(repo("github.com/a/app", installed="v1.19.0", prereleases=True)).newest, "v2.0-rc1")

    def test_one_request_per_release_repo(self):
        self.check(repo("github.com/a/app", installed="v1.18.2"))
        self.assertEqual(self.fakes.requests, [("releases", "github.com/a/app")])

    def test_only_a_few_releases_are_asked_for_unless_theyre_all_pre_releases(self):
        self.fakes.releases["github.com/a/betas"] = [release(f"v2.0-beta{i}", True) for i in range(9, 0, -1)] + \
            [release("v1.0")]
        result = self.check(repo("github.com/a/betas", installed="v1.0"))
        self.assertEqual((result.status, result.newest), (checker.UP_TO_DATE, "v1.0"))
        self.assertEqual(len(self.fakes.requests), 2)  # 5 betas, then the full list
        self.fakes.requests.clear()
        self.check(repo("github.com/a/betas", installed="v1.0", prereleases=True))
        self.assertEqual(len(self.fakes.requests), 1)

    def test_no_releases(self):
        self.fakes.releases["github.com/a/empty"] = []
        self.assertEqual(self.check(repo("github.com/a/empty", installed="-")).status, checker.NO_RELEASES)

    def test_branch(self):
        r = repo("gitgud.io/g/smod", host="gitlab", follow="branch", branch="main", installed="h" * 40)
        self.assertEqual(self.check(r).status, checker.UP_TO_DATE)
        self.assertEqual(self.fakes.requests, [])  # same commit: no request at all
        r.installed = "o" * 40
        result = self.check(r)
        self.assertEqual((result.status, result.text), (checker.UPDATE, "2 new commits on main"))
        self.fakes.relations["gitgud.io/g/smod"] = sources.DIVERGED
        r.branch = "dev"
        self.assertEqual(self.check(r).status, checker.OTHER)
        r.branch = "gone"
        self.assertIn("no branch", self.check(r).text)

    def test_scanned_clone_reads_disk(self):
        with tempfile.TemporaryDirectory() as d:
            on_disk = make_clone(Path(d) / "smod", "https://gitgud.io/g/smod.git")
            self.fakes.branches["gitgud.io/g/smod"] = [sources.Branch("main", on_disk)]
            r = repo("gitgud.io/g/smod", host="gitlab", follow="branch", branch="main", installed="stale",
                     source="scanned", local_path=str(Path(d) / "smod"))
            self.assertEqual(self.check(r).status, checker.UP_TO_DATE)

    def test_problems(self):
        def broken(ref, host, **_):
            raise sources.SourceError("Couldn’t reach github.com. Check your internet connection.")

        sources.releases = broken
        result = self.check(repo("github.com/a/app", installed="v1"))
        self.assertEqual(result.status, checker.FAILED)
        self.assertIn("Couldn’t reach", result.text)


class CheckAllTest(unittest.TestCase):
    def setUp(self):
        self.fakes = Fakes()
        self.fakes.install(self)
        for name in ("one", "two", "three"):
            self.fakes.releases[f"github.com/a/{name}"] = [release("v2")]
        self.fakes.releases["gitlab.com/a/four"] = [release("v2")]
        self.repos = [repo(f"github.com/a/{n}", installed="v1") for n in ("one", "two", "three")]
        self.repos.append(repo("gitlab.com/a/four", host="gitlab", installed="v1"))

    def test_rate_limit_stops_further_github_requests(self):
        checker.CHECKS_AT_ONCE, saved = 1, checker.CHECKS_AT_ONCE  # one at a time, so the order is known
        self.addCleanup(setattr, checker, "CHECKS_AT_ONCE", saved)
        self.fakes.limited = {"github.com/a/two"}
        state, _ = checker.check_all(self.repos)
        statuses = {k: v.status for k, v in state.results.items()}
        self.assertEqual(statuses, {"github.com/a/one": checker.UPDATE, "github.com/a/two": checker.RATE_LIMITED,
                                    "github.com/a/three": checker.RATE_LIMITED, "gitlab.com/a/four": checker.UPDATE})
        self.assertNotIn(("releases", "github.com/a/three"), self.fakes.requests)  # not asked
        self.assertEqual(state.results["github.com/a/three"].retry_after, "2026-10-11T02:24:00+00:00")

    def test_without_a_connection_repos_keep_their_last_result(self):
        first, _ = checker.check_all(self.repos)
        saved = checker.sources.releases

        def offline(*args, **kwargs):
            raise checker.sources.Unreachable("Couldn\u2019t reach api.github.com. Check your internet connection.")

        checker.sources.releases = offline
        self.addCleanup(setattr, checker.sources, "releases", saved)
        second, fresh = checker.check_all(self.repos, first)
        kept = second.results["github.com/a/one"]
        self.assertEqual((kept.status, kept.not_rechecked, kept.retry_after), (checker.UPDATE, True, ""))
        self.assertEqual(fresh, [])  # nothing new to announce
        # No site answered, so it doesn't count as a check: the next automatic one isn't put off.
        first.last_run = "2026-10-10T00:00:00+00:00"
        self.assertEqual(checker.check_all(self.repos, first)[0].last_run, first.last_run)
        # Never checked before: says it couldn't be checked (not "failed" for a reason to do with the repo).
        third, _ = checker.check_all(self.repos, checker.State())
        self.assertEqual(third.results["github.com/a/one"].status, checker.UNREACHABLE)

    def test_limited_repos_keep_their_last_result(self):
        checker.CHECKS_AT_ONCE, saved = 1, checker.CHECKS_AT_ONCE
        self.addCleanup(setattr, checker, "CHECKS_AT_ONCE", saved)
        first, _ = checker.check_all(self.repos)
        self.fakes.limited = {"github.com/a/one"}
        first.last_run = "2026-10-10T00:00:00+00:00"
        second, fresh = checker.check_all(self.repos, first)
        kept = second.results["github.com/a/three"]  # skipped once GitHub's limit was hit
        self.assertEqual((kept.status, kept.text, kept.not_rechecked), (checker.UPDATE, "Update available: v2", True))
        self.assertEqual(kept.retry_after, "2026-10-11T02:24:00+00:00")
        self.assertEqual(fresh, [])
        self.assertNotEqual(second.last_run, first.last_run)  # GitLab answered, so it counts
        # Never checked before: nothing to keep.
        third, _ = checker.check_all(self.repos, checker.State())
        self.assertEqual(third.results["github.com/a/three"].status, checker.RATE_LIMITED)

    def test_announce_each_update_once(self):
        state, fresh = checker.check_all(self.repos)
        self.assertEqual(len(fresh), 4)
        state, fresh = checker.check_all(self.repos, state)
        self.assertEqual(fresh, [])  # same versions: nothing new to announce
        self.fakes.releases["gitlab.com/a/four"] = [release("v3")]
        state, fresh = checker.check_all(self.repos, state)
        self.assertEqual(fresh, ["gitlab.com/a/four"])
        self.assertEqual(len(state.updates()), 4)


class RecheckTest(unittest.TestCase):
    """A result redone for a new version of yours, without asking the site."""

    def test_releases(self):
        old = checker.Result(checker.UPDATE, "Update available: v1.19.0", "v1.19.0", "2026-10-11T00:00:00+00:00")
        self.assertEqual(checker.recheck_against(old, "v1.19.0", by_branch=False).status, checker.UP_TO_DATE)
        self.assertEqual(checker.recheck_against(old, "1.19.0", by_branch=False).status, checker.UP_TO_DATE)
        self.assertEqual(checker.recheck_against(old, "-", by_branch=False).text, "Not installed \u00b7 newest v1.19.0")
        up = checker.recheck_against(old, "v1.19.0", by_branch=False)
        self.assertEqual(checker.recheck_against(up, "v1.18.0", by_branch=False).status, checker.UPDATE)
        self.assertEqual(up.checked_at, old.checked_at)  # still the time the site was asked

    def test_branch(self):
        old = checker.Result(checker.UPDATE, "1 new commit on main", "h" * 40)
        self.assertEqual(checker.recheck_against(old, "h" * 40, by_branch=True).status, checker.UP_TO_DATE)
        # Some other commit: can't tell without asking the site, so the last result stays.
        self.assertEqual(checker.recheck_against(old, "x" * 40, by_branch=True), old)


class StateTest(unittest.TestCase):
    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "sub" / "checks.json"
            state = checker.State(last_run="2026-10-11T00:00:00+00:00",
                                  results={"a/b/c": checker.Result(checker.UPDATE, "Update available: v2", "v2")},
                                  notified={"a/b/c": "v2"})
            checker.save_state(state, path)
            self.assertEqual(checker.load_state(path), state)
            path.write_text("{not json")
            self.assertEqual(checker.load_state(path), checker.State())  # a broken record is just started over

    def test_due(self):
        at = datetime(2026, 10, 11, 12, tzinfo=timezone.utc)
        daily = Settings(auto_check=True, check_interval_hours=24)
        self.assertTrue(checker.due(daily, checker.State(), at))
        state = checker.State(last_run=(at - timedelta(hours=23)).isoformat())
        self.assertFalse(checker.due(daily, state, at))
        self.assertTrue(checker.due(daily, checker.State(last_run=(at - timedelta(hours=25)).isoformat()), at))
        self.assertFalse(checker.due(Settings(auto_check=False), checker.State(), at))


if __name__ == "__main__":
    unittest.main()
