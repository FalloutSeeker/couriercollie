"""The README's screenshot (docs/screenshot.png), in a container (devtools/readme_shot.sh), in Breeze Dark: real
projects, really installed. Some at an older release (installed as it was, then the newest is out), so the list has
updates to show; a clone a few commits behind; one not installed. Then a real check, and LocalSend's page.
"""

import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, "/app/devtools")
import harness  # noqa: E402
import relay_client  # noqa: E402,F401  (GitHub's API through the relay, with your login)

HOME = Path(os.environ["HOME"])
# A clone of tmux's plugin manager from a while ago: a few commits behind.
subprocess.run(["git", "clone", "-q", "https://github.com/tmux-plugins/tpm.git", str(HOME / "src/tpm")], check=True)
subprocess.run(["git", "-C", str(HOME / "src/tpm"), "reset", "-q", "--hard", "HEAD~3"], check=True)

h = harness.start(settings={"scanning": True, "autoCheck": True})
b, app, win = h.backend, h.app, h.win
from couriercollie import assets, updater  # noqa: E402

updater.ROOT = []
win.resize(1150, 800)


def pump(cond=lambda: False, seconds=1.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.03)
    return cond()


def add(url, file_ending=""):
    before = {r.id for r in b._config.repos}
    b.addRepo("", url)
    pump(lambda: not b.adding and {r.id for r in b._config.repos} != before, 60)
    rid = next(r.id for r in b._config.repos if r.id not in before)
    if file_ending and not b._config.find(rid).asset_pattern:
        name = next(f["name"] for f in b.details(rid)["fileChoices"] if f["name"].endswith(file_ending))
        b.pickAsset(rid, b._details[rid].releases[0].tag, name)
    print("added", rid, b._config.find(rid).asset_pattern, flush=True)
    return rid


def install(rid, older=False):
    """Install the newest, or (older) the release before it, as it was installed back then."""
    d = b._details[rid]
    real = d.releases
    stable = [r for r in real if not r.prerelease]
    if older:  # the latest before the newest that has the file (LocalSend's v1.18.1 has no AppImage)
        pattern = b._config.find(rid).asset_pattern
        d.releases = [next(r for r in stable[1:] if assets.pick(pattern, [a.name for a in r.assets]))]
    b.updateRepo(rid)
    pump(lambda: not b.details(rid)["updating"], 600)
    d.releases = real
    print(" ", rid, "->", b._config.find(rid).installed, b.details(rid)["updateNote"][:80], flush=True)


# couriercollie itself, as on a real first start: tracked from its package, at the top of the list.
b._config.settings.tracked_itself = False
b._track_myself()
localsend = add("https://github.com/localsend/localsend", "-linux-x86-64.AppImage")
b.renameRepo(localsend, "LocalSend")
install(localsend, older=True)
neovim = add("https://github.com/neovim/neovim", "x86_64.appimage")
b.renameRepo(neovim, "Neovim")
install(neovim, older=True)
ripgrep = add("https://github.com/BurntSushi/ripgrep", "x86_64-unknown-linux-musl.tar.gz")
install(ripgrep)
glab = add("https://gitlab.com/gitlab-org/cli", "_linux_amd64.tar.gz")
b.renameRepo(glab, "glab")  # the project is called "cli"
install(glab)
b.startScan()  # finds the clone
pump(lambda: b.scanState == "done", 120)
b.trackFound([i["key"] for i in b.scanItems if i["status"] == "new"])
b.addCategory("Tools")
lazygit = add("https://github.com/jesseduffield/lazygit", "_linux_x86_64.tar.gz")
install(lazygit, older=True)
zed = add("https://github.com/zed-industries/zed", "zed-linux-x86_64.tar.gz")  # not installed
for rid in (lazygit, zed):
    b.moveRepo(rid, "Tools", "")
pump(lambda: not b.checking, 300)
b.checkNow()
pump(lambda: b.checking, 5)
pump(lambda: not b.checking, 300)
for r in b._config.repos:
    print(f"  {r.name}: {b.repo(r.id)['checkText']}", flush=True)
h.win.openRepo(localsend)
pump(lambda: b.details(localsend)["state"] == "ready", 60)
pump(seconds=2)
win.grabWindow().save("/work/out/screenshot.png")
print("saved", flush=True)
