"""Click through the main screens with a simulated mouse and check what ends up marked: welcome screen choices, list
filters, the build-file picker, branches, and setting your version. Asks GitHub and gitgud.io for real data.

    python3 -I devtools/check_pages.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402

h = harness.start(settings={"firstLaunchDone": False})
b = h.backend
LS = "github.com/localsend/localsend"
AERO = "gitgud.io/aeroshell/atp/aerothemeplasma"
APP = "asset:LocalSend-1.18.2-linux-x86-64.AppImage"
TAR = "asset:LocalSend-1.18.2-linux-x86-64.tar.gz"


def checked(name):
    where = h.find(name)
    return where[2] if where else None


def expect(label, states):
    actual = {n: checked(n) for n in states}
    h.check(label, actual == states, f"got {actual}")


def details_ready(repo_id):
    return lambda: b.details(repo_id)["state"] == "ready"


def expand(tag, index):
    from PySide6.QtCore import QObject

    page = h.win.findChild(QObject, "repoDetailPage")
    page.toggle(tag, index)


h.run([
    (700, lambda: expect("welcome starts on Yes", {"autoYes": True, "autoNo": False})),
    (0, lambda: h.click("autoNo")),
    (200, lambda: expect("No unticks Yes", {"autoYes": False, "autoNo": True})),
    (0, lambda: h.shot("pages-0-welcome")),
    (0, lambda: h.call("firstLaunch", "done")),
    (300, lambda: h.check("Done saved No", b.settings["autoCheck"] is False)),
    (0, lambda: b.addRepo("", "https://github.com/localsend/localsend")),
    h.until(details_ready(LS)),
    (800, lambda: h.click(TAR)),
    (300, lambda: expect("pick the tarball", {APP: False, TAR: True})),
    (0, lambda: h.click(APP)),
    (300, lambda: expect("pick the AppImage instead", {APP: True, TAR: False})),
    (0, lambda: expand("v1.18.0", 2)),
    (300, lambda: h.click("mine:v1.18.0")),
    (300, lambda: h.check("Set as My Version", b.details(LS)["versionText"] == "v1.18.0")),
    (0, lambda: h.shot("pages-1-repo")),
    (0, lambda: h.click("markNotInstalled")),
    (300, lambda: h.check("Mark as Not Installed", b.details(LS)["versionText"] == "Not installed")),
    (0, lambda: h.click("markUpToDate")),
    (300, lambda: h.check("Mark as Up to Date", b.details(LS)["status"] == "Up to date")),
    (0, lambda: h.click("filter:all")),
    (200, lambda: expect("clicking the active filter keeps it", {"filter:all": True, "filter:github": False})),
    (0, lambda: h.click("filter:github")),
    (200, lambda: expect("switching filter", {"filter:all": False, "filter:github": True})),
    (0, lambda: h.click("filter:all")),
    (0, lambda: b.addRepo("", "https://gitgud.io/aeroshell/atp/aerothemeplasma")),
    h.until(details_ready(AERO)),
    (800, lambda: h.click("branch:master")),
    (300, lambda: expect("pick branch master", {"branch:master": True, "branch:Plasma/6.7": False})),
    (0, lambda: h.click("branch:Plasma/6.7")),
    (300, lambda: expect("back to Plasma/6.7", {"branch:master": False, "branch:Plasma/6.7": True})),
    (0, lambda: h.shot("pages-2-branches")),
    (0, lambda: h.win.openSettings()),
    (600, lambda: [w.grabWindow().save(str(harness.OUT / "pages-3-settings.png"))
                   for w in __import__("PySide6.QtGui", fromlist=["QGuiApplication"]).QGuiApplication.topLevelWindows()
                   if w.isVisible() and w.title() == "Settings"]),
])
