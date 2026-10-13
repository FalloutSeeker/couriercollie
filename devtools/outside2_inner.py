"""More changes made outside couriercollie, in a container (devtools/check_outside.sh, second round), through the real
window (off-screen) and real projects:

- An AppImage moved to another folder by hand, then a scan.
- A newer AppImage downloaded by hand (and the old one deleted), then a scan.
- A program's command link deleted by hand: Install puts it back, without leaving the old copy behind.
- The distro's own package of a tracked program installed with the package manager.

    python3 outside2_inner.py DISTRO
"""

import os
import re
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
from couriercollie import sources, updater  # noqa: E402

updater.ROOT = []
failures = []
shots = [0]


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


def sh(command):
    r = subprocess.run(command, shell=True, capture_output=True, text=True)
    return (r.stdout + r.stderr).strip()


def shot(name):
    pump(seconds=0.6)
    shots[0] += 1
    win.grabWindow().save(f"/out/2-{shots[0]:02d}-{name}.png")


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
    pump(lambda: not b.details(rid)["updating"], 600)
    return b.details(rid)


def refresh(rid):
    win.openRepo(rid)
    b.loadDetails(rid, True)
    pump(lambda: b.details(rid)["state"] in ("ready", "error") and not b.details(rid).get("comparing"), 60)
    return b.details(rid)


def scan():
    b.startScan()
    pump(lambda: b.scanState == "scanning", 5)
    pump(lambda: b.scanState != "scanning", 300)
    return b.scanItems, b.scanUpdated


def says(rid, when):
    d, row = b.details(rid), b.repo(rid)
    print(f"  {when}: page '{d.get('headline')}' ({d.get('versionText')}) at {b._config.find(rid).local_path}"
          f" | list '{row['checkText']}'", flush=True)
    return d, row


# ---- An AppImage moved by hand --------------------------------------------------------------------------------------
print(f"=== {DISTRO}: an AppImage moved to another folder", flush=True)
nvim = add("https://github.com/neovim/neovim", r"x86_64\.appimage$")
update(nvim)
old = Path(b._config.find(nvim).local_path)
moved = HOME / "Apps" / old.name
moved.parent.mkdir(exist_ok=True)
print(f"  $ mv {old} {moved}", flush=True)
old.rename(moved)
says(nvim, "after Refresh") if refresh(nvim) else None
items, updated = scan()
print(f"  scan: updated {updated}; new {[i['address'] for i in items if i['status'] == 'new']}", flush=True)
d, row = says(nvim, "after the scan")
check("a scan finds where it went, and the entry follows it (no second one)",
      b._config.find(nvim).local_path == str(moved) and len([r for r in b._config.repos if r.id == nvim]) == 1,
      b._config.find(nvim).local_path)
d = refresh(nvim)
check("…and it's up to date there", d["statusKind"] == "current", d["headline"])

# ---- A newer AppImage downloaded by hand ------------------------------------------------------------------------------
print(f"=== {DISTRO}: an older AppImage, then the newest downloaded by hand", flush=True)
ls = add("https://github.com/localsend/localsend", r"-linux-x86-64\.AppImage$")
rels = [r for r in b._details[ls].releases if not r.prerelease and re.search(r"\d", r.tag)]
older = next(r for r in rels[1:] if any(a.name.endswith("-linux-x86-64.AppImage") for a in r.assets))
real = b._details[ls].releases
b._details[ls].releases = [older]  # installed a while ago
update(ls)
b._details[ls].releases = real
first = Path(b._config.find(ls).local_path)
says(ls, f"installed {older.tag} through couriercollie")
newest = next(a for a in rels[0].assets if a.name.endswith("-linux-x86-64.AppImage"))
print(f"  $ download {newest.name} by hand; rm the old one", flush=True)
sh(f"curl -sL -o {first.parent / newest.name} {newest.url} && chmod +x {first.parent / newest.name}")
first.unlink()
d, row = says(ls, "after Refresh") if refresh(ls) else (None, None)
shot("appimage-newer-by-hand")
items, updated = scan()
print(f"  scan: updated {updated}; new {[i['address'] for i in items if i['status'] == 'new']}", flush=True)
d, row = says(ls, "after the scan")
check("a scan finds the newer one, and the entry follows it", Path(b._config.find(ls).local_path).name == newest.name,
      b._config.find(ls).local_path)
d = refresh(ls)
check("…and it's up to date", d["statusKind"] == "current", (d["headline"], d["versionText"]))

# ---- A program's link deleted by hand ---------------------------------------------------------------------------------
print(f"=== {DISTRO}: a program's command link deleted by hand", flush=True)
lazy = add("https://github.com/jesseduffield/lazygit", r"_linux_x86_64\.tar\.gz$")
update(lazy)
link = Path(b._config.find(lazy).local_path)
folder = link.resolve().parent
print(f"  $ rm {link} (its folder {folder} stays)", flush=True)
link.unlink()
d, row = says(lazy, "after Refresh") if refresh(lazy) else (None, None)
d = update(lazy)
print(f"  Install: {d['updateNote']}", flush=True)
check("Install puts the link back", Path(b._config.find(lazy).local_path).exists(), d["updateNote"])
copies = sorted(p.name for p in updater.programs_dir().glob("*lazygit*/*"))
check("…without a second copy beside the old one", len(copies) <= 1, copies)

# ---- The distro's own package of a tracked program --------------------------------------------------------------------
print(f"=== {DISTRO}: the distro's own package of a tracked program (fzf)", flush=True)
fzf = add("https://github.com/junegunn/fzf", r"linux_amd64\.tar\.gz$")
update(fzf)
install = {"fedora": "dnf install -y -q fzf", "opensuse": "zypper -q -n install fzf",
           "ubuntu": "apt-get install -y -qq fzf", "debian": "apt-get install -y -qq fzf",
           "arch": "pacman -S --noconfirm --needed fzf"}[DISTRO]
print(f"  $ {install}", flush=True)
sh(install)
d, row = says(fzf, "after Refresh") if refresh(fzf) else (None, None)
shot("distro-package-too")
b.checkNow()
pump(lambda: b.checking, 3)
pump(lambda: not b.checking, 300)
d, row = says(fzf, "after Check Now")
check("the package manager's copy is noticed: shown, not updated here", row["checkText"].startswith("Installed with")
      and not d["canUpdate"], (d["headline"], row["checkText"]))
print(f"  which fzf: {sh('command -v fzf')} | {sh('fzf --version')}", flush=True)

win.closeRepo()
shot("list")
print(f"=== {DISTRO}: {len(failures)} failures", flush=True)
for f in failures:
    print("  - " + f, flush=True)
