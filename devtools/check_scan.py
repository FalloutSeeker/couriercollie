"""Check scanning end to end on this computer: welcome screen with scanning ticked, the real scan (reads your home
folder; asks GitHub/GitLab about new finds), results, Select all, Track selected.

Uses a copy of your settings file, so your real list isn't changed.

    python3 -I devtools/check_scan.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402

# The copy has the welcome screen done already; show it again for this check.
h = harness.start(copy_settings_from=Path.home() / ".config/couriercollie/repos.toml",
                  settings={"firstLaunchDone": False, "scanning": False})
b = h.backend
before = len(b._config.repos)


def after_scan():
    items = b.scanItems
    h.check("scan finished without an error", b.scanError == "", b.scanError)
    h.check("results list new finds", len(items) > 0)
    print("  updated automatically:", b.scanUpdated)
    for i in items:
        print(f"  {i['status']:8} {i['address']:48} {i['note']}")
    h.shot("scan-1-results")


def press_track_selected():
    from PySide6.QtCore import QObject

    count = h.win.findChild(QObject, "scanDialog").property("pickedCount")
    h.press("scanDialog", f"Track Selected ({count})")


def all_ticked():
    # (Not a problem, nor couriercollie itself: "Added by default", it can't be ticked.)
    return all((h.find("found:" + i["address"]) or [0, 0, False])[2] for i in b.scanItems
               if i["status"] not in ("problem", "default"))


h.run([
    (700, lambda: h.check("welcome screen shows", h.visible("firstLaunch"))),
    (0, lambda: h.shot("scan-0-welcome")),
    (0, lambda: h.click("scanBox")),
    (300, lambda: h.call("firstLaunch", "done")),
    (300, lambda: h.check("scan started from the welcome screen", b.scanState == "scanning")),
    h.until(lambda: b.scanState == "done"),
    (500, after_scan),
    (0, lambda: h.check("every find is shown", all(h.find("found:" + i["address"]) for i in b.scanItems))),
    (0, lambda: h.check("new finds ticked to start with, the rest not", all(
        (h.find("found:" + i["address"]) or [0, 0, None])[2] == (i["status"] == "new") for i in b.scanItems))),
    (0, lambda: h.click("selectAll")),
    (300, lambda: h.check("Select all ticks every trackable find", all_ticked())),
    (0, lambda: h.shot("scan-2-all-selected")),
    (0, lambda: h.click("selectNone")),
    (300, lambda: h.check("Select none clears them", not any(
        (h.find("found:" + i["address"]) or [0, 0, False])[2] for i in b.scanItems))),
    (0, lambda: h.click("selectAll")),
    (300, press_track_selected),  # (the window's own button: QML hands its keys over as numbers, 3.0)
    (500, lambda: h.check("Track Selected tracks them", len(b._config.repos) > before, f"{before} -> {len(b._config.repos)}")),
    (0, lambda: h.check("tracked without duplicates",
                          len({r.id.lower() for r in b._config.repos}) == len(b._config.repos))),
    (0, lambda: print(f"  repos before: {before}, after: {len(b._config.repos)}")),
    (0, lambda: [print(f"  {r.source:8} {r.name:28} {r.id}  aliases={r.aliases}") for r in b._config.repos]),
    (0, lambda: h.call("scanDialog", "close")),
    (600, lambda: h.shot("scan-3-list")),
])
