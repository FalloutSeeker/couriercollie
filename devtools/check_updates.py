"""Check for updates from the window (a copy of your settings and a temporary results file): Check Now, the status
line, each repo's result and update icon. Asks GitHub and GitLab for real. No notifications, badge or timer.

    python3 -I devtools/check_updates.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402

h = harness.start(copy_settings_from=Path.home() / ".config/repoproject/repos.toml")
b = h.backend


def report():
    c = b.checks
    for r in b._config.repos:
        row = b.repo(r.id)
        print(f"  {r.name:12} {row['checkStatus']:13} {row['checkText']}")
        h.check(f"{r.name}: update icon only for updates",
                (h.find("updateIcon:" + r.id) is not None) == row["updateAvailable"])
    h.check("summary counts the updates", c["updates"] == sum(b.repo(r.id)["updateAvailable"] for r in b._config.repos))
    h.check("last checked shown", c["lastChecked"] != "")
    h.shot("updates")


def choose_newest_steps():
    """Open a repo with an update, click "Set as My Version" on its newest release: the list updates at once."""
    picked = {}

    def open_one():
        repo = next((r for r in b._config.repos if b.repo(r.id)["updateAvailable"] and r.follow == "releases"), None)
        picked["repo"], picked["count"] = repo, b.checks["updates"]
        if repo:
            h.win.openRepo(repo.id)

    def click_newest():
        repo = picked["repo"]
        if repo:
            newest = b._checks.results[repo.id].newest
            h.click("mine:" + newest)

    def verify():
        repo = picked["repo"]
        if not repo:
            print("  (no repo with a release update to try this on)")
            return
        h.check(f"{repo.name}: update icon gone at once", h.find("updateIcon:" + repo.id) is None)
        h.check("update count went down by one", b.checks["updates"] == picked["count"] - 1)
        h.shot("updates-chose-newest")

    return [(0, open_one), h.until(lambda: not picked["repo"] or b.details(picked["repo"].id)["state"] == "ready"),
            (800, click_newest), (500, verify)]


def rate_limited():
    """Pretend GitHub's hourly limit stopped one repo being checked."""
    from repoproject import checker

    repo_id = next(r.id for r in b._config.repos if r.host == "github")
    b._checks.results[repo_id] = checker.Result(checker.RATE_LIMITED, "Not checked: GitHub\u2019s hourly limit was "
                                                "reached", retry_after="2026-10-11T02:24:00+00:00")
    b.checksChanged.emit()
    b.reposChanged.emit()


h.run([
    (500, lambda: h.check("not checked yet at first", b.checks["lastChecked"] == "")),
    (0, lambda: h.click("text:Check Now")),
    (200, lambda: h.check("checking", b.checking)),
    h.until(lambda: not b.checking, 60000),
    (500, report),
    *choose_newest_steps(),
    (0, rate_limited),
    (500, lambda: (h.check("rate-limit bar shown", h.find("rateLimitBar") is not None), h.shot("updates-rate-limited"))),
])
