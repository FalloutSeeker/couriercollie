"""Open a scanned clone's page (SMOD, from a copy of your settings) and check: the version is read from the clone on
disk, what's new on the branch is listed, the "Mark as…" buttons are hidden, and switching to another branch and back
changes nothing. Reads the clone; asks gitgud.io.

    python3 -I devtools/check_scanned_repo.py [repo address]
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402

REPO = sys.argv[1] if len(sys.argv) > 1 else "gitgud.io/aeroshell/smod"
h = harness.start(copy_settings_from=Path.home() / ".config/repoproject/repos.toml")
b = h.backend
repo = b._config.find(REPO)
if not repo or repo.source != "scanned":
    sys.exit(f"{REPO} isn't a scanned repo in your settings; scan first.")
on_disk = subprocess.run(["git", "-C", repo.local_path, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
print(f"  saved version: {repo.installed[:7]}   on disk: {on_disk[:7]}")


def report():
    d = b.details(REPO)
    print(f"  page: your version {d['versionText']!r}; status {d['status']!r}")
    for c in d["newCommits"]:
        print(f"    {c['sha']}  {c['title']}")
    h.check("version read from disk", b._config.find(REPO).installed == on_disk)
    h.check("no Mark buttons for a scanned repo", h.find("markUpToDate") is None and h.find("markNotInstalled") is None)
    if d["updateAvailable"]:
        h.check("what's new is listed", d["newCommitsTotal"] > 0)
    h.shot("scanned-repo")


def other_branch():
    return next(x["name"] for x in b.details(REPO)["branches"] if not x["selected"])


picked = {}


def after_switching_back():
    d = b.details(REPO)
    print(f"  after switching to {picked['branch']} and back: status {d['status']!r}")
    h.check("switching branch and back keeps the version on disk", b._config.find(REPO).installed == on_disk)
    h.check("status unchanged by switching back", d["status"] == picked["status"])


h.run([
    (300, lambda: h.win.openRepo(REPO)),
    h.until(lambda: b.details(REPO)["state"] == "ready"),
    (800, report),
    (0, lambda: picked.update(branch=other_branch(), status=b.details(REPO)["status"], home=repo.branch)),
    (0, lambda: h.click("branch:" + picked["branch"])),
    (2500, lambda: h.click("branch:" + picked["home"])),
    (2500, after_switching_back),
    # Other branches aren't updates: SMOD's master is behind the clone, hidpi-functionality split off earlier.
    *([] if REPO != "gitgud.io/aeroshell/smod" else [
        (0, lambda: h.click("branch:master")),
        (2500, lambda: h.check("master: your version is newer",
                               b.details(REPO)["status"] == "Your version is newer than master", b.details(REPO)["status"])),
        (0, lambda: h.click("branch:hidpi-functionality")),
        (2500, lambda: h.check("hidpi-functionality: not comparable, clone is on Plasma/6.7",
                               b.details(REPO)["status"] == "Not comparable with hidpi-functionality: your clone is on Plasma/6.7.",
                               b.details(REPO)["status"])),
        (0, lambda: h.shot("scanned-repo-other-branch")),
        (0, lambda: h.click("branch:Plasma/6.7")),
        (2500, lambda: h.check("back on Plasma/6.7: newer commits", b.details(REPO)["updateAvailable"])),
    ]),
])
