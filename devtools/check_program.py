"""Installing and updating a real program from a release archive (ripgrep, ~2 MB from GitHub), with a simulated
mouse: Install, the checksum, the link in ~/.local/bin (and that the command runs), then Update from an older copy,
which is kept. Everything goes into temporary folders: your ~/.local/bin and settings aren't touched.

    python3 -I devtools/check_program.py
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402

work = Path(tempfile.mkdtemp())
os.environ.update(XDG_DATA_HOME=str(work / "data"), REPOPROJECT_BIN=str(work / "bin"))
ID = "github.com/burntsushi/ripgrep"
settings = work / "repos.toml"
settings.write_text(f'[[repos]]\nid = "{ID}"\nname = "ripgrep"\nurl = "https://{ID}"\nhost = "github"\n'
                    'follow = "releases"\nasset_pattern = "ripgrep-*-x86_64-unknown-linux-musl.tar.gz"\n'
                    'kind = "Program"\ninstalled = "-"\n')

h = harness.start(copy_settings_from=settings)
b = h.backend
from repoproject import updater  # noqa: E402

state = {}


def details():
    return b.details(ID)


def runs(link):
    try:
        return subprocess.run([str(link), "--version"], capture_output=True, text=True, timeout=10).stdout
    except OSError:
        return ""


def installed():
    link = updater.bin_dir() / "rg"
    state["link"] = link
    h.check("a link called rg in the bin folder", link.is_symlink())
    h.check("…that runs", runs(link).startswith("ripgrep "), runs(link)[:40])
    h.check("…checked against GitHub's checksum", details()["updateNoteKind"] == "done", details()["updateNote"])
    h.check("…and is your version now", details()["statusKind"] == "current" and details()["command"] == "rg")


def pretend_older():
    """Make the copy look like an older version: its folder renamed, the link pointed at it, that's your version."""
    current = state["link"].resolve()
    version_dir = updater.programs_dir() / "github.com_burntsushi_ripgrep" / updater.program_version(state["link"])
    older = version_dir.with_name("13.0.0")
    version_dir.rename(older)
    state["link"].unlink()
    state["link"].symlink_to(older / current.relative_to(version_dir))
    b._config.find(ID).installed = "13.0.0"
    state["older"] = older
    b.loadDetails(ID, True)


def updated():
    link = state["link"]
    h.check("the link now points at the new version", updater.program_version(link) == details()["newestText"],
            updater.program_version(link))
    h.check("…and runs", runs(link).startswith("ripgrep "))
    h.check("the older version is kept, to undo", state["older"].is_dir())
    h.check("up to date", details()["statusKind"] == "current")


h.run([
    (0, lambda: h.win.openRepo(ID)),
    h.until(lambda: details()["state"] == "ready", 60000),
    (500, lambda: h.check("Install offered", h.find("text:Install") is not None)),
    (0, lambda: h.shot("program-0-install")),
    (0, lambda: h.click("updateNow")),
    h.until(lambda: not details()["updating"], 300000),
    (500, installed),
    (0, lambda: h.shot("program-1-installed")),
    (0, pretend_older),
    h.until(lambda: details()["state"] == "ready", 60000),
    (500, lambda: h.check("Update offered for the older copy", h.find("text:Update") is not None)),
    (0, lambda: h.click("updateNow")),
    h.until(lambda: not details()["updating"], 300000),
    (500, updated),
    (0, lambda: h.shot("program-2-updated")),
    (0, lambda: h.click("undoUpdate")),
    h.until(lambda: not details()["updating"], 60000),
    (500, lambda: h.check("Undo: the link is back on the older version",
                          updater.program_version(state["link"]) == "13.0.0" and runs(state["link"]).startswith("ripgrep "))),
    (0, lambda: h.check("…which is your version, with Update offered again",
                        b._config.find(ID).installed == "13.0.0" and h.find("text:Update") is not None)),
])
