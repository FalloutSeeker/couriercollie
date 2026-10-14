"""The first scan, as a person goes through it, with a simulated mouse and keyboard: the welcome screen with scanning
ticked, the results (new finds ticked, couriercollie itself greyed out as "Added by default", a find that can't be
tracked), unticking one, Track Selected, Select None and Select All, Space on a row, scanning again (nothing twice, a
mirror offered to link), and closing the window mid-scan. A made-up home folder with clones in it; the sites' answers
are faked and nothing is checked online, so it runs anywhere, offline.

    python3 -I devtools/check_first_scan.py
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

HOME = Path(tempfile.mkdtemp())
os.environ["HOME"] = str(HOME)  # (the scan's "~": this made-up home, never yours)
ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
       "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_GLOBAL": "/dev/null"}


def clone(folder: str, remote: str):
    """A clone as one made with git clone would look: a commit, and its remote."""
    path = HOME / folder
    path.mkdir(parents=True)
    for args in (["init", "-q", "-b", "main"], ["commit", "-q", "--allow-empty", "-m", "first"],
                 ["remote", "add", "origin", remote]):
        subprocess.run(["git", "-C", str(path), *args], check=True, env=ENV)


clone("code/alpha", "https://github.com/example/alpha.git")
clone("code/beta", "https://github.com/example/beta.git")
clone("code/ghost", "https://github.com/example/ghost.git")  # (removed from its site: can't be tracked)
clone("src/couriercollie", "https://github.com/FalloutSeeker/couriercollie.git")

# As after `couriercollie --reset` and a new start: only couriercollie itself, and the welcome screen to come.
settings = HOME / "seed.toml"
settings.write_text('[settings]\nfirst_launch_done = false\ntracked_itself = true\n\n[[repos]]\n'
                    'id = "github.com/FalloutSeeker/couriercollie"\nname = "couriercollie"\n'
                    'url = "https://github.com/FalloutSeeker/couriercollie"\nhost = "github"\nfollow = "branch"\n'
                    'branch = "main"\nkind = "git"\nsource = "scanned"\n'
                    f'local_path = "{HOME / "src/couriercollie"}"\n')

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402

h = harness.start(copy_settings_from=settings, settings={"firstLaunchDone": False})
b, win = h.backend, h.win
from PySide6.QtCore import QObject, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from couriercollie import checker, scan, sources  # noqa: E402

# The sites' answers, made up; no update checks; only the made-up home is scanned (not this computer's packages).
PROJECTS = {"github.com/example/alpha": ("github", "alpha", "A tool."),
            "github.com/example/beta": ("github", "beta", "Another tool."),
            "gitlab.com/mirrors/alpha": ("gitlab", "alpha", "A tool.")}  # (alpha's mirror: same name and words)


def project_info(ref):
    if ref.id not in PROJECTS:
        raise sources.NotFound(ref.id)
    host, name, description = PROJECTS[ref.id]
    return sources.ProjectInfo(ref, host, name, description, "main")


sources.project_info = project_info
checker.check_all = lambda repos, previous: (previous or checker.State(), [])
real_find_all = scan.find_all
scan.find_all = lambda folders, **_: real_find_all(["~"], system_packages=lambda: [], bundles=lambda: [])


def dialog():
    return win.findChild(QObject, "scanDialog")


def items():
    return {i["address"]: i for i in b.scanItems}


def ticked(address):
    return bool((h.find("found:" + address) or [0, 0, False])[2])


def track_selected():
    """The footer's Track Selected (N), as clicking it does."""
    h.press("scanDialog", f"Track Selected ({dialog().property('pickedCount')})")


def tracked():
    return sorted(r.id for r in b._config.repos)


def space_on(address):
    """Space on a row, once Tab has put it there."""
    QTest.keyClick(win, Qt.Key.Key_Tab)  # (so the window has the keyboard)
    # (A dialog's rows are in the window's overlay: found by walking the items, in QML's own JavaScript.)
    from PySide6.QtQml import QJSValue

    focused = h.engine.evaluate("""(function (root, name) {
        const walk = item => {
            if (item.objectName === name) { item.forceActiveFocus(Qt.TabFocusReason); return true; }
            for (let i = 0; i < item.children.length; i++)
                if (walk(item.children[i])) return true;
            return false;
        };
        return walk(root);
    })""").call([h.engine.newQObject(win.contentItem().parent()), QJSValue("found:" + address)]).toBool()
    h.check("the row takes the keyboard", focused)
    QTest.keyClick(win, Qt.Key.Key_Space)


ALPHA, BETA, GHOST, MYSELF = ("github.com/example/alpha", "github.com/example/beta", "github.com/example/ghost",
                              "github.com/FalloutSeeker/couriercollie")
h.run([
    (500, lambda: h.check("the welcome screen opens", h.visible("firstLaunch"))),
    (0, lambda: h.click("scanBox")),
    (300, lambda: h.call("firstLaunch", "done")),
    h.until(lambda: b.scanState == "done", 60000),
    (600, lambda: h.shot("first-scan-1-results")),
    (0, lambda: h.check("every find is listed", set(items()) == {ALPHA, BETA, GHOST, MYSELF}, sorted(items()))),
    (0, lambda: h.check("new finds are ticked to start with", ticked(ALPHA) and ticked(BETA))),
    (0, lambda: h.check("couriercollie itself: listed as added by default, not ticked",
                        items()[MYSELF]["status"] == "default" and not ticked(MYSELF))),
    (0, lambda: h.check("a find that can't be tracked says why, and isn't ticked",
                        items()[GHOST]["status"] == "problem" and "Not found" in items()[GHOST]["note"]
                        and not ticked(GHOST), items()[GHOST])),
    (0, lambda: h.check("the button counts what's ticked", dialog().property("pickedCount") == 2)),
    # Untick beta, then Track Selected: alpha only.
    (0, lambda: h.click("found:" + BETA)),
    (300, lambda: h.check("a click unticks a find", not ticked(BETA) and dialog().property("pickedCount") == 1)),
    (0, track_selected),
    (600, lambda: h.check("Track Selected tracks what's ticked, and only that", tracked() == [MYSELF, ALPHA],
                          tracked())),
    (0, lambda: h.check("…it leaves the list; what wasn't ticked stays, unticked",
                        ALPHA not in items() and BETA in items() and not ticked(BETA), sorted(items()))),
    (0, lambda: h.shot("first-scan-2-tracked-one")),
    # Select None, then Select All, then Track Selected.
    (0, lambda: h.click("selectNone")),
    (300, lambda: h.check("Select None: nothing to track", dialog().property("pickedCount") == 0)),
    (0, lambda: h.click("selectAll")),
    (300, lambda: h.check("Select All ticks what can be tracked, nothing else",
                          ticked(BETA) and not ticked(GHOST) and not ticked(MYSELF))),
    (0, lambda: space_on(BETA)),
    (300, lambda: h.check("Space unticks a row", not ticked(BETA))),
    (0, lambda: space_on(BETA)),
    (300, lambda: h.check("…and ticks it again", ticked(BETA))),
    (0, track_selected),
    (600, lambda: h.check("then the rest is tracked", tracked() == [MYSELF, ALPHA, BETA], tracked())),
    (0, lambda: h.check("nothing tracked twice", len({r.id.lower() for r in b._config.repos}) == len(b._config.repos))),
    (0, lambda: h.call("scanDialog", "close")),
    # Scanning again, with a mirror of alpha found since: nothing listed twice, the mirror offered to link.
    (500, lambda: clone("code/alpha-mirror", "https://gitlab.com/mirrors/alpha.git")),
    (0, lambda: h.call("scanDialog", "openAndScan")),
    h.until(lambda: b.scanState == "done", 60000),
    (600, lambda: h.shot("first-scan-3-again")),
    (0, lambda: h.check("scanning again lists nothing already tracked as new",
                        not any(i["status"] == "new" for i in b.scanItems), [(i["address"], i["status"])
                                                                             for i in b.scanItems])),
    (0, lambda: h.check("a mirror of a tracked repo is offered to link, not ticked",
                        items().get("gitlab.com/mirrors/alpha", {}).get("status") == "similar"
                        and not ticked("gitlab.com/mirrors/alpha"), items().get("gitlab.com/mirrors/alpha"))),
    (0, lambda: h.click("found:gitlab.com/mirrors/alpha")),
    (300, track_selected),
    (600, lambda: h.check("ticked and tracked, it's linked to alpha, not added",
                          tracked() == [MYSELF, ALPHA, BETA]
                          and "gitlab.com/mirrors/alpha" in b._config.find(ALPHA).aliases, tracked())),
    (0, lambda: h.call("scanDialog", "close")),
    # Closed mid-scan: no harm; the results are there when it's opened again.
    (300, lambda: h.call("scanDialog", "openAndScan")),
    (0, lambda: h.call("scanDialog", "close")),
    h.until(lambda: b.scanState == "done", 60000),
    (300, lambda: h.call("scanDialog", "open")),
    (600, lambda: h.check("closed mid-scan, opened again: the results are shown", h.visible("scanDialog")
                          and h.find("found:" + GHOST) is not None)),
    (0, lambda: h.call("scanDialog", "close")),
    (300, lambda: h.check("the list shows what was tracked", all(h.find("repo:" + r) for r in (ALPHA, BETA)))),
    (0, lambda: h.shot("first-scan-4-list")),
])
