"""Updating a git clone, with a simulated mouse: the Update button on the repo page and in the list, the result, and
showing then running an install script. Uses a temporary project repo and clone, and no network: the site's answers
are faked, and the "terminal" is a plain shell that leaves a file behind, so nothing on this computer is touched.

    python3 -I devtools/check_update_clone.py
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402

ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
       "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_GLOBAL": "/dev/null"}
work = Path(tempfile.mkdtemp())
upstream, clone, other = work / "upstream.git", work / "project", work / "other"


def git(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True, env=ENV).stdout.strip()


git("init", "-q", "--bare", "-b", "main", str(upstream))
git("clone", "-q", str(upstream), str(other))
(other / "README.md").write_text("first\n")
git("add", ".", cwd=other)
git("commit", "-q", "-m", "first", cwd=other)
git("push", "-q", "origin", "HEAD:main", cwd=other)
git("clone", "-q", str(upstream), str(clone))
start = git("rev-parse", "HEAD", cwd=clone)
(clone / "install.sh").write_text("#!/bin/sh\necho installed > installed.txt\n")
for i in (1, 2):
    (other / "README.md").write_text(f"change {i}\n")
    git("commit", "-q", "-am", f"change {i}", cwd=other)
git("push", "-q", "origin", "HEAD:main", cwd=other)
newest = git("rev-parse", "HEAD", cwd=other)

ID = "github.com/example/project"
settings = work / "repos.toml"
settings.write_text(f'[[repos]]\nid = "{ID}"\nname = "Project"\nurl = "https://{ID}"\nhost = "github"\n'
                    f'follow = "branch"\nbranch = "main"\nkind = "git"\nsource = "scanned"\n'
                    f'local_path = "{clone}"\ninstalled = "{start}"\n')

h = harness.start(copy_settings_from=settings)
b = h.backend
from PySide6.QtCore import QObject  # noqa: E402

from repoproject import checker, sources, updater  # noqa: E402

sources.releases = lambda ref, host: []
sources.branches = lambda ref: ("main", [sources.Branch("main", newest)])
sources.compare = lambda ref, host, yours, head: sources.Comparison(
    sources.SAME if yours == head else sources.BEHIND, 2, [sources.Commit(newest, "change 2")])
updater.terminal_command = lambda path, name: ("/bin/sh", [f"./{name}"])  # instead of a terminal window


def checked_once():
    b._checks.results[ID] = checker.Result(checker.UPDATE, "Update available", newest)
    b.checksChanged.emit()
    b.reposChanged.emit()


def details():
    return b.details(ID)


h.run([
    (300, checked_once),
    (300, lambda: h.check("list: the update icon is a button for a clone", h.find("updateButton:" + ID) is not None)),
    (0, lambda: h.win.openRepo(ID)),
    h.until(lambda: details()["state"] == "ready"),
    (500, lambda: h.check("page: Update offered when behind", h.find("updateNow") is not None)),
    (0, lambda: h.shot("update-clone-0-behind")),
    (0, lambda: h.click("updateNow")),
    h.until(lambda: not details()["updating"], 30000),
    (500, lambda: h.check("pulled to the newest commit", git("rev-parse", "HEAD", cwd=clone) == newest)),
    (0, lambda: h.check("your version follows", b._config.find(ID).installed == newest)),
    (0, lambda: h.check("says what it did", details()["updateNote"] == "Pulled 2 new commits.", details()["updateNote"])),
    (0, lambda: h.check("now up to date", details()["statusKind"] == "current")),
    (0, lambda: h.check("Update gone from page and list", h.find("updateNow") is None
                        and h.find("updateButton:" + ID) is None)),
    (0, lambda: h.shot("update-clone-1-pulled")),
    (0, lambda: h.click("showScript:install.sh")),
    (500, lambda: h.check("the script is shown before running", h.visible("scriptDialog"))),
    (0, lambda: h.check("…all of it", "echo installed" in (h.win.findChild(QObject, "scriptText").property("text")
                                                          or ""))),
    (0, lambda: h.check("not run just by showing it", not (clone / "installed.txt").exists())),
    (0, lambda: h.shot("update-clone-2-script")),
    (0, lambda: h.click("text:Run in Terminal")),
    h.until(lambda: (clone / "installed.txt").exists(), 10000),
    (300, lambda: h.check("Run in Terminal runs it, in the clone's folder", (clone / "installed.txt").exists())),
    # From the list, an update that's refused (the clone was switched to another branch) opens the page to say why.
    (0, lambda: (git("switch", "-q", "-c", "mine", cwd=clone), git("reset", "-q", "--hard", start, cwd=clone))),
    (0, lambda: (setattr(b._config.find(ID), "installed", start), checked_once(), h.win.closeRepo())),
    (300, lambda: h.click("updateButton:" + ID)),
    h.until(lambda: not details()["updating"], 30000),
    (500, lambda: h.check("refused from the list: its page opens", h.win.property("currentRepoId") == ID)),
    (0, lambda: h.check("…saying why", "not main" in details()["updateNote"], details()["updateNote"])),
    (0, lambda: h.check("…and nothing changed", git("rev-parse", "HEAD", cwd=clone) == start)),
    (0, lambda: h.shot("update-clone-3-refused")),
])
