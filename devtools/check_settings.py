"""Check the welcome screen's scanning text and the Settings window's folder list: defaults marked, removing a
folder, folders a scan would skip, Reset Scan Folders; then Start at login, the tray, Restore to Defaults and Send Feedback.
No network, and nothing written outside a temporary folder.

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
    (0, lambda: b.addScanFolder("/root")),  # yours can't be opened: scans skip it, and Settings says why
    (300, lambda: h.check("a folder you can't open says scans skip it",
                          h.find("folderProblem:/root", h.window("Settings")) is not None)),
    (0, lambda: h.check("…as does one that isn't there", h.find("folderProblem:/mnt/My Drive", h.window("Settings"))
                        is not None)),
    (0, lambda: h.shot("settings-2-changed", h.window("Settings"))),
    (0, lambda: h.check("Reset Scan Folders shown once changed", h.find("restoreFolders", h.window("Settings")) is not None)),
    (0, lambda: h.click("restoreFolders", h.window("Settings"))),
    (300, lambda: h.check("restored", folders() == ["~", "/opt", "/usr/local", "/srv"])),
    (0, lambda: h.check("Reset Scan Folders hidden at the defaults", h.find("restoreFolders", h.window("Settings")) is None)),
    # Rows come and go inside the form layout here; make sure that's stable.
    *[step for _ in range(3) for step in (
        (0, lambda: [h.click("removeFolder:" + f, h.window("Settings")) for f in ("/srv", "/usr/local", "/opt", "~")]),
        (300, lambda: h.check("removed every folder", folders() == [])),
        (0, lambda: b.addScanFolder("/mnt/data")),
        (200, lambda: h.click("restoreFolders", h.window("Settings"))),
        (300, lambda: h.check("restored again", folders() == ["~", "/opt", "/usr/local", "/srv"])),
    )],
    # Start at login and the tray (as on a desktop with a tray); then Restore to Defaults, which asks first.
    (0, lambda: setattr(b, "tray_available", True) or b.settingsChanged.emit()),
    (200, lambda: h.click("startAtLogin", h.window("Settings"))),
    (200, lambda: h.click("keepInTray", h.window("Settings"))),
    (300, lambda: h.check("start at login and tray on", b.settings["startAtLogin"] and b.settings["keepInTray"])),
    (0, lambda: h.shot("settings-3-tray", h.window("Settings"))),
    (0, lambda: h.click("restoreDefaults", h.window("Settings"))),
    (500, lambda: h.shot("settings-4-restore", h.window("Settings"))),
    (0, lambda: h.shot("settings-4-restore-main")),
    (0, lambda: h.call("restoreDefaultsDialog", "accept")),
    (300, lambda: h.check("restored to defaults", b.settings["areDefault"] and not b.settings["keepInTray"])),
    # Send Feedback asks first (cancelled here: accepting opens the browser).
    (0, lambda: h.click("sendFeedback", h.window("Settings"))),
    (500, lambda: h.check("Send Feedback asks first, repos not included unless ticked",
                          (h.find("includeRepos", h.window("Settings")) or [0, 0, True])[2] is False)),
    (0, lambda: h.shot("settings-5-feedback", h.window("Settings"))),
    (0, lambda: h.call("feedbackDialog", "reject")),
])
