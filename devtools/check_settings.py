"""Check the welcome screen's scanning text and the Settings window's folder list: defaults marked, removing a
folder, Restore Defaults. No network.

    python3 -I devtools/check_settings.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402

h = harness.start(settings={"firstLaunchDone": False})
b = h.backend


def folders():
    return [f["path"] for f in b.settings["scanFolders"]]


h.run([
    (700, lambda: h.click("scanBox")),
    (300, lambda: h.shot("settings-0-welcome")),
    (0, lambda: h.call("firstLaunch", "done")),
    (300, lambda: h.call("scanDialog", "close")),
    (300, lambda: h.win.openSettings()),
    (700, lambda: h.shot("settings-1-defaults", h.window("Settings"))),
    (0, lambda: h.check("defaults listed", folders() == ["~", "/opt", "/usr/local", "/srv"])),
    (0, lambda: h.click("removeFolder:/srv", h.window("Settings"))),
    (300, lambda: h.check("remove a folder", folders() == ["~", "/opt", "/usr/local"])),
    (0, lambda: b.addScanFolder("file:///mnt/My%20Drive")),
    (300, lambda: h.check("add a folder (spaces decoded)", folders()[-1] == "/mnt/My Drive")),
    (0, lambda: h.shot("settings-2-changed", h.window("Settings"))),
    (0, lambda: h.check("Restore Defaults shown once changed", h.find("restoreFolders", h.window("Settings")) is not None)),
    (0, lambda: h.click("restoreFolders", h.window("Settings"))),
    (300, lambda: h.check("restored", folders() == ["~", "/opt", "/usr/local", "/srv"])),
    (0, lambda: h.check("Restore Defaults hidden at the defaults", h.find("restoreFolders", h.window("Settings")) is None)),
    # Rows come and go inside the form layout here; make sure that's stable.
    *[step for _ in range(3) for step in (
        (0, lambda: [h.click("removeFolder:" + f, h.window("Settings")) for f in ("/srv", "/usr/local", "/opt", "~")]),
        (300, lambda: h.check("removed every folder", folders() == [])),
        (0, lambda: b.addScanFolder("/mnt/data")),
        (200, lambda: h.click("restoreFolders", h.window("Settings"))),
        (300, lambda: h.check("restored again", folders() == ["~", "/opt", "/usr/local", "/srv"])),
    )],
])
