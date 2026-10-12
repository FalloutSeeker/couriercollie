"""A brand-new user's first run, in a container (devtools/check_first_run.sh), through the real window (off-screen):
welcome screen, first scan, add a repo, install it, Check Now, Settings. Screenshots of each step in /out; what
happened is printed, to read alongside them."""
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, "/app/devtools")
import harness  # noqa: E402

HOME = Path(os.environ["HOME"])
# What a person might already have: an AppImage they downloaded a while ago, and an old clone.
apps = HOME / "Applications"
apps.mkdir(exist_ok=True)
subprocess.run(["curl", "-sL", "-o", str(apps / "nvim.appimage"),
                "https://github.com/neovim/neovim/releases/download/v0.11.0/nvim-linux-x86_64.appimage"], check=True)
(apps / "nvim.appimage").chmod(0o755)
(HOME / "code").mkdir(exist_ok=True)
subprocess.run(["git", "clone", "-q", "https://github.com/junegunn/vim-plug.git", str(HOME / "code/vim-plug")])
subprocess.run(["git", "-C", str(HOME / "code/vim-plug"), "reset", "-q", "--hard", "HEAD~3"])

h = harness.start(settings={"firstLaunchDone": False})
b, app, win = h.backend, h.app, h.win
from couriercollie import updater  # noqa: E402

updater.ROOT = []  # root in the container: no password prompt
win.resize(1000, 720)
OUT = Path("/out")
n = [0]


def pump(cond=lambda: False, seconds=1.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.03)
    return cond()


def shot(name, window=None):
    pump(seconds=0.8)
    n[0] += 1
    (window or win).grabWindow().save(str(OUT / f"{n[0]:02d}-{name}.png"))
    print("shot", n[0], name, flush=True)


pump(lambda: h.visible("firstLaunch"), 5)
shot("welcome")
h.click("scanBox")
shot("welcome-scan-ticked")
h.call("firstLaunch", "done")
pump(lambda: b.scanState == "scanning", 5)
shot("scanning")
pump(lambda: b.scanState == "done", 300)
shot("scan-results")
print("scan found:", [(i.get("name"), i.get("status")) for i in b.scanItems], flush=True)
b.trackFound([str(i["key"]) for i in b.scanItems if i.get("status") != "problem"])
h.call("scanDialog", "close")
pump(lambda: not b.checking, 120)
shot("list-after-scan")
nv = next(r.id for r in b._config.repos if r.id.endswith("neovim"))
print("neovim:", b._config.find(nv).asset_pattern, "|", b.repo(nv)["checkText"], flush=True)
win.openRepo(nv)
pump(lambda: b.details(nv)["state"] in ("ready", "error"), 60)
shot("neovim-page")
print("neovim page:", b.details(nv).get("headline"), "|", b.details(nv).get("status"), "| newCopy",
      b.details(nv).get("newCopy"), flush=True)
h.click("updateNow")
pump(lambda: not b.details(nv)["updating"], 300)
shot("neovim-updated")
print("neovim after update:", b.details(nv).get("updateNote"), "|", b.repo(nv)["checkText"], "| files:",
      sorted(p.name for p in apps.iterdir()), "| at:", b._config.find(nv).local_path, flush=True)
win.closeRepo()

h.call("addDialog", "open")
shot("add-empty")
from PySide6.QtCore import QObject  # noqa: E402
win.findChild(QObject, "addUrl").setProperty("text", "https://github.com/jesseduffield/lazygit")
shot("add-typed")
h.call("addDialog", "add")
pump(lambda: not b.adding and any(r.id.endswith("lazygit") for r in b._config.repos), 60)
pump(seconds=3)
shot("after-add")
rid = next(r.id for r in b._config.repos if r.id.endswith("lazygit"))
win.openRepo(rid)
pump(lambda: b.details(rid)["state"] in ("ready", "error"), 60)
shot("lazygit-page")
d = b.details(rid)
print("lazygit:", d.get("headline"), "|", d.get("status"), "| canUpdate", d.get("canUpdate"),
      "| picked", b._config.find(rid).asset_pattern, flush=True)
if d.get("canUpdate"):
    h.click("updateNow")
    pump(lambda: not b.details(rid)["updating"], 300)
    shot("lazygit-installed")
    print("note:", b.details(rid).get("updateNote"), flush=True)
win.closeRepo()
b.checkNow()
pump(lambda: not b.checking, 300)
shot("list-after-check")
for r in b._config.repos:
    print(" ", r.name, "|", b.repo(r.id)["checkText"], flush=True)
win.openSettings()
pump(seconds=1)
shot("settings", h.window("Settings"))
print("qt messages:", [m for m in h.messages if "warning" in m.lower() or "error" in m.lower()][:10], flush=True)
