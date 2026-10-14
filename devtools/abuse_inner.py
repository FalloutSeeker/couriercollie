"""Rough handling, in a container (devtools/check_abuse.sh), through the real window (off-screen) and real projects:
the settings file edited by hand while the app is open, the results file broken, the install folders deleted,
Update clicked twice, Stop Tracking during an update, a clone's .git deleted, a program's link left dangling, and an
AppImage in a folder with spaces in its name. Prints what happened, and PASS/FAIL.

    python3 abuse_inner.py DISTRO
"""

import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, "/app/devtools")
import harness  # noqa: E402
import relay_client  # noqa: E402,F401

DISTRO = sys.argv[1]
HOME = Path(os.environ["HOME"])
h = harness.start(settings={"scanning": True})
b, app, win = h.backend, h.app, h.win
from couriercollie import config, updater  # noqa: E402

updater.ROOT = []
SETTINGS = Path(os.environ["COURIERCOLLIE_CONFIG"])
STATE = Path(os.environ["COURIERCOLLIE_STATE"])
failures = []


def check(label, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + label + (f"  ({detail})" if detail and not ok else ""), flush=True)
    if not ok:
        failures.append(label)
    return ok


def pump(cond=lambda: False, seconds=1.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.03)
    return cond()


def add(url, ending=""):
    before = {r.id for r in b._config.repos}
    b.addRepo("", url)
    pump(lambda: not b.adding and {r.id for r in b._config.repos} != before, 60)
    rid = next(r.id for r in b._config.repos if r.id not in before)
    if ending and not b._config.find(rid).asset_pattern:
        name = next(f["name"] for f in b.details(rid)["fileChoices"] if re.search(ending, f["name"]))
        b.pickAsset(rid, b._details[rid].releases[0].tag, name)
    return rid


def update(rid):
    b.updateRepo(rid)
    pump(lambda: rid not in b._updating, 600)
    return b.details(rid) if b._config.find(rid) else {}


def refresh(rid):
    win.openRepo(rid)
    b.loadDetails(rid, True)
    pump(lambda: b.details(rid)["state"] in ("ready", "error") and not b.details(rid).get("comparing"), 60)
    return b.details(rid)


def warnings():
    return [m for m in h.messages if "warning" in m.lower() or "error" in m.lower() or "traceback" in m.lower()]


# ---- The settings file edited by hand while the app is open ---------------------------------------------------------
print(f"=== {DISTRO}: the settings file edited by hand while the app is open", flush=True)
nvim = add("https://github.com/neovim/neovim", r"x86_64\.appimage$")
pump(seconds=1)
text = SETTINGS.read_text()
SETTINGS.write_text(text + '\n[[repos]]\nid = "github.com/charmbracelet/skate"\nname = "skate (added by hand)"\n'
                           'url = "https://github.com/charmbracelet/skate"\nhost = "github"\n')
pump(seconds=2)
b.renameRepo(nvim, "Neovim")  # the app saves
kept = "skate (added by hand)" in SETTINGS.read_text()
print(f"  the hand-added repo {'survived' if kept else 'was overwritten by'} the app's next save", flush=True)
check("an edit by hand while the app is open isn't silently lost", kept and b.repo("github.com/charmbracelet/skate"))

# ---- The results file broken ------------------------------------------------------------------------------------------
print(f"=== {DISTRO}: the results file broken", flush=True)
STATE.write_text('{"results": {"github.com/neovim/neovim": {"status": 7, "text": [1, 2]}}, "last_run": 12')
pump(seconds=2)
b.checkNow()
pump(lambda: b.checking, 3)
pump(lambda: not b.checking, 120)
check("a broken results file: the app carries on, and the next check writes a good one",
      '"results"' in STATE.read_text() and b.repo(nvim)["checkText"] != "", b.repo(nvim)["checkText"])

# ---- The install folders deleted ---------------------------------------------------------------------------------------
print(f"=== {DISTRO}: ~/Applications and ~/.local/bin deleted, then Install", flush=True)
shutil.rmtree(HOME / "Applications", ignore_errors=True)
shutil.rmtree(HOME / ".local/bin", ignore_errors=True)
d = update(nvim)
check("Install makes ~/Applications again", Path(b._config.find(nvim).local_path or "/x").is_file(), d.get("updateNote"))
lazy = add("https://github.com/jesseduffield/lazygit", r"_linux_x86_64\.tar\.gz$")
d = update(lazy)
check("…and ~/.local/bin", Path(b._config.find(lazy).local_path or "/x").exists(), d.get("updateNote"))

# ---- Update clicked twice ---------------------------------------------------------------------------------------------
print(f"=== {DISTRO}: Update clicked twice", flush=True)
fzf = add("https://github.com/junegunn/fzf", r"linux_amd64\.tar\.gz$")
b.updateRepo(fzf)
b.updateRepo(fzf)  # a double-click
pump(lambda: fzf not in b._updating, 600)
copies = sorted(p.name for p in updater.programs_dir().glob("*fzf*/*"))
check("a double-click installs once", len(copies) == 1 and b.details(fzf)["updateNoteKind"] != "error",
      (copies, b.details(fzf)["updateNote"]))

# ---- Stop Tracking during an update -----------------------------------------------------------------------------------
print(f"=== {DISTRO}: Stop Tracking during an update", flush=True)
ls = add("https://github.com/localsend/localsend", r"-linux-x86-64\.AppImage$")
b.updateRepo(ls)
pump(lambda: b.details(ls)["progress"] > 0.1, 60)
b.removeRepo(ls)  # (refused: what it's installing would land for a repo that's gone)
check("not removed mid-update: it waits for the update", b._config.find(ls) is not None)
pump(lambda: ls not in b._updating, 300)
pump(seconds=2)
b.removeRepo(ls)
check("…then removed: no crash, not tracked any more", b._config.find(ls) is None and not warnings(), warnings())
leftover = sorted(p.name for p in (HOME / "Applications").glob(".*.part"))
check("…and nothing half-downloaded left", leftover == [], leftover)

# ---- A clone's .git deleted -------------------------------------------------------------------------------------------
print(f"=== {DISTRO}: a clone's .git deleted (the folder stays)", flush=True)
tpm = add("https://github.com/tmux-plugins/tpm")
update(tpm)
clone = Path(b._config.find(tpm).local_path)
shutil.rmtree(clone / ".git")
d = refresh(tpm)
print(f"  page '{d['headline']}' ({d['versionText']}) | list '{b.repo(tpm)['checkText']}' | Update: {d['canUpdate']}",
      flush=True)
check("no longer a clone: not up to date, and Update doesn't try to pull", d["statusKind"] != "current"
      and not (d["canUpdate"] and d["updateAvailable"]), (d["headline"], d["canUpdate"]))
d = update(tpm)
check("…and an Update click does no harm", clone.is_dir() and not warnings(), d.get("updateNote"))

# ---- A program's link left dangling -----------------------------------------------------------------------------------
print(f"=== {DISTRO}: a program's link left dangling", flush=True)
link = Path(b._config.find(lazy).local_path)
shutil.rmtree(link.resolve().parent)  # the program's folder deleted; the link stays, pointing nowhere
d = refresh(lazy)
print(f"  page '{d['headline']}' | list '{b.repo(lazy)['checkText']}'", flush=True)
check("a dangling link: not found", d["headline"] == "Not found on this computer", d["headline"])
d = update(lazy)
check("…and Install puts it back", link.exists(), d.get("updateNote"))

# ---- An AppImage in a folder with spaces ------------------------------------------------------------------------------
print(f"=== {DISTRO}: an AppImage in a folder with spaces in its name", flush=True)
old = Path(b._config.find(nvim).local_path)
spaced = HOME / "My Apps" / "Neo Vim's" / old.name
spaced.parent.mkdir(parents=True)
old.rename(spaced)
b._config.find(nvim).local_path = str(spaced)
b._config.find(nvim).installed = "v0.1.0"  # (as if older, so Update replaces it)
d = update(nvim)
entry = updater.menu_entry_for(Path(b._config.find(nvim).local_path))
desktop = next((p for p in updater.menu_dir().glob("*.desktop") if "Neo Vim" in p.read_text()), None)
exec_line = next((ln for ln in desktop.read_text().splitlines() if ln.startswith("Exec=")), "") if desktop else ""
print(f"  {d['updateNote']} | menu entry: {exec_line}", flush=True)
check("updated in place, its menu entry pointing at it, quoted", Path(b._config.find(nvim).local_path).parent
      == spaced.parent and entry and '"' in exec_line, (b._config.find(nvim).local_path, exec_line))
args = subprocess.run(["sh", "-c", f"printf '%s|' {exec_line.removeprefix('Exec=').split(' %')[0]}"],
                      capture_output=True, text=True).stdout
check("…and the menu entry's command is one argument", args.count("|") == 1, args)

print(f"qt warnings: {warnings()[:5]}", flush=True)
print(f"=== {DISTRO}: {len(failures)} failures", flush=True)
for f in failures:
    print("  - " + f, flush=True)
