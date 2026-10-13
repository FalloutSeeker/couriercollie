"""Installing a project added by hand that follows a branch, with a simulated mouse: Install clones it, after which
it's a clone like one a scan found. Uses a temporary project repo and clones folder, and no network: the project's
address is pointed at the temporary repo, and the site's answers are faked.

    python3 -I devtools/check_install_clone.py
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
upstream, other, clones = work / "upstream.git", work / "other", work / "src"


def git(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True, env=ENV).stdout.strip()


git("init", "-q", "--bare", "-b", "main", str(upstream))
git("clone", "-q", str(upstream), str(other))
(other / "install.sh").write_text("#!/bin/sh\necho installed\n")
git("add", ".", cwd=other)
git("commit", "-q", "-m", "first", cwd=other)
git("push", "-q", "origin", "HEAD:main", cwd=other)
newest = git("rev-parse", "HEAD", cwd=other)

ID = "github.com/example/project"
os.environ.update(COURIERCOLLIE_CLONES=str(clones), GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0=f"url.{upstream}.insteadOf",
                  GIT_CONFIG_VALUE_0=f"https://{ID}.git")
settings = work / "repos.toml"
settings.write_text(f'[[repos]]\nid = "{ID}"\nname = "Project"\nurl = "https://{ID}"\nhost = "github"\n'
                    f'follow = "branch"\nbranch = "main"\ninstalled = "-"\n')

h = harness.start(copy_settings_from=settings)
b = h.backend
from PySide6.QtCore import QObject  # noqa: E402

from couriercollie import sources  # noqa: E402

sources.releases = lambda ref, host, **_: []
sources.branches = lambda ref: ("main", [sources.Branch("main", newest)])


def details():
    return b.details(ID)


h.run([
    (0, lambda: h.win.openRepo(ID)),
    h.until(lambda: details()["state"] == "ready"),
    (500, lambda: h.check("not installed: Clone Source Code offered", h.find("updateNow") is not None
                          and h.win.findChild(QObject, "updateNow").property("text") == "Clone Source Code")),
    (0, lambda: h.check("…saying where it goes", h.find(f"text:Clones the project’s main branch into a folder in "
                                                       f"{clones}.") is not None)),
    (0, lambda: h.shot("install-clone-0")),
    (0, lambda: h.click("updateNow")),
    h.until(lambda: not details()["updating"], 30000),
    (500, lambda: h.check("cloned", git("rev-parse", "HEAD", cwd=clones / "project") == newest)),
    (0, lambda: h.check("…then asks whether to run its install script, showing it", h.visible("stepDialog")
                        and "Run install.sh" in str(details()["stepChoices"]))),
    (0, lambda: h.shot("install-clone-0b-asks")),
    (0, lambda: h.press("stepDialog", "Not Now")),
    (0, lambda: h.check("says where", details()["updateNote"].startswith(f"Cloned main into {clones / 'project'}."),
                        details()["updateNote"])),
    (0, lambda: h.check("up to date, found on this computer", details()["statusKind"] == "current"
                        and h.find("text:Found on this computer") is not None)),
    (0, lambda: h.check("Not Now: asked again at the next update", h.find("stepSummary") is not None
                        and details()["updateAsks"])),
    (0, lambda: h.check("no Install any more", h.find("updateNow") is None)),
    (0, lambda: h.shot("install-clone-1")),
])
