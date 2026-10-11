"""Installing and updating a real AppImage (LocalSend, ~63 MB from GitHub), with a simulated mouse: Install, the
download's progress, the checksum, the menu entry, then Update from an older copy (which is then removed).
Everything goes into temporary folders: your ~/Applications, menu and settings aren't touched.

    python3 -I devtools/check_appimage.py
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402

work = Path(tempfile.mkdtemp())
os.environ.update(XDG_DATA_HOME=str(work / "data"), REPOPROJECT_APPS=str(work / "Applications"))
ID = "github.com/localsend/localsend"
settings = work / "repos.toml"
settings.write_text(f'[[repos]]\nid = "{ID}"\nname = "LocalSend"\nurl = "https://{ID}"\nhost = "github"\n'
                    'follow = "releases"\nasset_pattern = "LocalSend-*-linux-x86-64.AppImage"\nkind = "AppImage"\n'
                    'installed = "-"\n')

h = harness.start(copy_settings_from=settings)
b = h.backend
from repoproject import updater  # noqa: E402

state = {}


def details():
    return b.details(ID)


def installed():
    repo = b._config.find(ID)
    state["app"] = Path(repo.local_path) if repo.local_path else None
    app = state["app"]
    h.check("installed into Applications", bool(app) and app.parent == updater.apps_dir() and app.is_file(), str(app))
    h.check("…runnable, and really an AppImage", bool(app) and os.access(app, os.X_OK) and updater.is_appimage(app))
    h.check("…checked against GitHub's checksum", details()["updateNoteKind"] == "done", details()["updateNote"])
    h.check("…with a menu entry", bool(app) and updater.menu_entry_for(app))
    h.check("…and is your version now", repo.installed == details()["newestText"] and details()["statusKind"] == "current")


def pretend_older():
    """Make the copy look like last month's: renamed to v1.18.0, and that's your version."""
    older = state["app"].with_name("LocalSend-1.18.0-linux-x86-64.AppImage")
    state["app"].rename(older)
    updater.repoint_menu_entries(state["app"], older)
    repo = b._config.find(ID)
    repo.local_path, repo.installed = str(older), "v1.18.0"
    state["older"] = older
    b.loadDetails(ID, True)


def updated():
    repo = b._config.find(ID)
    new = Path(repo.local_path)
    h.check("updated in place of the older one", new.parent == state["older"].parent and new.is_file()
            and not state["older"].exists())
    h.check("the older one is removed", not any(state["older"].parent.glob("LocalSend-1.18.0*")))
    h.check("the menu entry starts the new one", updater.menu_entry_for(new) and not updater.menu_entry_for(state["older"]))
    h.check("up to date", details()["statusKind"] == "current", details()["statusKind"])


def mid_download():
    p = details()["progress"]
    if 0.2 < p < 0.8 and "mid" not in state:
        from PySide6.QtCore import QObject

        bar = h.win.findChild(QObject, "downloadProgress")
        state["mid"] = True
        state["bar"] = (bar.property("visible"), bar.property("width"), bar.property("value")) if bar else None
        h.shot("appimage-1-downloading")
    return not details()["updating"]


h.run([
    (0, lambda: h.win.openRepo(ID)),
    h.until(lambda: details()["state"] == "ready", 60000),
    (500, lambda: h.check("Install offered when you don't have it", h.find("text:Install") is not None)),
    (0, lambda: h.shot("appimage-0-install")),
    (0, lambda: h.click("updateNow")),
    h.until(mid_download, 600000),
    (500, installed),
    (0, lambda: h.check("progress was shown while downloading", state.get("mid", False))),
    (0, lambda: h.check("…with a progress bar", bool(state.get("bar")) and state["bar"][0] and state["bar"][1] > 50,
                        str(state.get("bar")))),
    (0, lambda: h.shot("appimage-2-installed")),
    (0, pretend_older),
    h.until(lambda: details()["state"] == "ready", 60000),
    (500, lambda: h.check("Update offered for the older copy", h.find("text:Update") is not None)),
    (0, lambda: h.click("updateNow")),
    h.until(lambda: not details()["updating"], 600000),
    (500, updated),
    (0, lambda: h.shot("appimage-3-updated")),
])
