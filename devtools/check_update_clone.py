"""Updating a git clone, with a simulated mouse: the Update button on the repo page and in the list, the result,
showing then running an install script, and a clone that follows releases moving to the newest. Uses a temporary project repo and clone, and no network: the site's answers
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

from couriercollie import checker, sources, updater  # noqa: E402

releases = []  # the project's releases, as the site would list them; one is added later
sources.releases = lambda ref, host, **_: list(releases)
sources.branches = lambda ref: ("main", [sources.Branch("main", newest)])
sources.compare = lambda ref, host, yours, head: sources.Comparison(
    sources.SAME if yours == head else sources.BEHIND, 2, [sources.Commit(newest, "change 2")])
updater.terminal_command = lambda path, name: ("/bin/sh", [f"./{name}"])  # instead of a terminal window


released = {}


def tag_release():
    (other / "README.md").write_text("release 3\n")
    git("commit", "-q", "-am", "release 3", cwd=other)
    git("tag", "v3", cwd=other)
    git("push", "-q", "origin", "HEAD:main", "v3", cwd=other)
    released["sha"] = git("rev-parse", "HEAD", cwd=other)
    releases.append(sources.Release("v3", "v3", None, False, "", "",
                                    [sources.Asset("project.tar.gz", "https://example.invalid/project.tar.gz")]))


def newer_release_checked():
    releases.insert(0, sources.Release("v4", "v4", None, False, "", "", []))
    checker.check_all = lambda repos, previous: (checker.State(results={ID: checker.Result(
        checker.UPDATE, "Update available: v4", "v4")}), [])
    b.checkNow()


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
    (0, lambda: h.check("says what it did", details()["updateNote"].startswith("Pulled 2 new commits. If the project"),
                        details()["updateNote"])),
    (0, lambda: h.check("now up to date", details()["statusKind"] == "current")),
    (0, lambda: h.check("Update gone from page and list", h.find("updateNow") is None
                        and h.find("updateButton:" + ID) is None)),
    (0, lambda: h.shot("update-clone-1-pulled")),
    # Refresh: back to the page as it is now, with the new version and no note.
    (0, lambda: h.click("text:Refresh")),
    h.until(lambda: details()["state"] == "ready"),
    (500, lambda: h.check("Refresh clears the note", h.find("updateNote") is None and details()["updateNote"] == "")),
    (0, lambda: h.check("…showing the new version, up to date", details()["versionText"] == f"commit {newest[:7]}"
                        and details()["statusKind"] == "current", details()["versionText"])),
    (0, lambda: h.click("showScript:install.sh")),
    (500, lambda: h.check("the script is shown before running", h.visible("scriptDialog"))),
    (0, lambda: h.check("…all of it", "echo installed" in (h.win.findChild(QObject, "scriptText").property("text")
                                                          or ""))),
    (0, lambda: h.check("not run just by showing it", not (clone / "installed.txt").exists())),
    (0, lambda: h.shot("update-clone-2-script")),
    (0, lambda: h.click("text:Run in Terminal")),
    h.until(lambda: (clone / "installed.txt").exists(), 10000),
    (300, lambda: h.check("Run in Terminal runs it, in the clone's folder", (clone / "installed.txt").exists())),
    (300, lambda: h.check("…and the button then offers to run it again",
                          h.find("text:Run install.sh Again\u2026") is not None)),
    (0, lambda: h.shot("update-clone-2b-script-ran")),
    # From the list, an update that's refused (the clone was switched to another branch) opens the page to say why.
    (0, lambda: (git("switch", "-q", "-c", "mine", cwd=clone), git("reset", "-q", "--hard", start, cwd=clone))),
    (0, lambda: (setattr(b._config.find(ID), "installed", start), checked_once(), h.win.closeRepo())),
    (300, lambda: h.click("updateButton:" + ID)),
    h.until(lambda: not details()["updating"], 30000),
    (500, lambda: h.check("refused from the list: its page opens", h.win.property("currentRepoId") == ID)),
    (0, lambda: h.check("…saying why", "not main" in details()["updateNote"], details()["updateNote"])),
    (0, lambda: h.check("…and nothing changed", git("rev-parse", "HEAD", cwd=clone) == start)),
    (0, lambda: h.shot("update-clone-3-refused")),
    # Following releases: the project tags a release; the clone (on its own branch, not at a tag) moves to it.
    (0, tag_release),
    (0, lambda: b.setFollow(ID, "releases")),
    (0, lambda: b.loadDetails(ID, True)),
    h.until(lambda: details()["state"] == "ready"),
    (500, lambda: h.check("releases: your version is the clone's commit", details()["versionText"].startswith("commit "),
                          details()["versionText"])),
    (0, lambda: h.check("…and v3 is offered", details()["newestText"] == "v3" and h.find("updateNow") is not None)),
    (0, lambda: h.check("…with no build-file picker for a clone", h.find("asset:project.tar.gz") is None)),
    (0, lambda: h.shot("update-clone-4-releases")),
    (0, lambda: h.click("updateNow")),
    h.until(lambda: not details()["updating"], 30000),
    (500, lambda: h.check("moved to v3", git("rev-parse", "HEAD", cwd=clone) == released["sha"])),
    (0, lambda: h.check("your version is v3, up to date", b._config.find(ID).installed == "v3"
                        and details()["statusKind"] == "current")),
    (0, lambda: h.check("says your branch is kept", "Your branch mine is unchanged" in details()["updateNote"],
                        details()["updateNote"])),
    (0, lambda: h.shot("update-clone-5-release")),
    # With the page open, a check finds a newer release: the page loads it again rather than waiting forever.
    (0, newer_release_checked),
    h.until(lambda: details()["state"] == "ready" and details()["newestText"] == "v4", 10000),
    (300, lambda: h.check("an open page follows a check that found something newer", details()["newestText"] == "v4")),
])
