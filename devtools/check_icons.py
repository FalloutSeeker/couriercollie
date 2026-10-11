"""Look up icons for your tracked repos (from a copy of your settings, with a temporary cache folder) and show
what each one got: an installed app's icon, the project's picture from its site, or the default. Also checks the
corner mark on scanned repos, and that icons aren't looked up a second time.

    python3 -I devtools/check_icons.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402

h = harness.start(copy_settings_from=Path.home() / ".config/couriercollie/repos.toml", find_icons=True)
b = h.backend
for r in b._config.repos:
    r.icon = ""  # look everything up afresh in this copy

calls = []


def report():
    for r in b._config.repos:
        print(f"  {r.name:8} {r.source:8} -> {r.icon or '(still looking)'}   shown as: {b.repo(r.id)['icon']}")
        h.check(f"{r.name}: corner mark only if scanned",
                (h.find("scannedMark:" + r.id) is not None) == (r.source == "scanned"))
    h.shot("icons")
    import couriercollie.icons as icons
    real = icons.resolve
    icons.resolve = lambda *a, **k: calls.append(a) or real(*a, **k)
    b.loadIcons()  # e.g. the window shown again: nothing to look up


h.run([
    h.until(lambda: all(r.icon for r in b._config.repos), 60000),
    (500, report),
    (1000, lambda: h.check("not looked up a second time", calls == [], str(calls))),
])
