"""What couriercollie makes of changes made outside it, in a container (devtools/check_outside.sh), through the real
window (off-screen) and real projects: each kind is installed through couriercollie, then changed from the command
line (removed, put back at an older version, updated by hand), and the list and page are read after a Refresh and a
Check Now. Screenshots of each in /out.

    python3 outside_inner.py DISTRO
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
import relay_client  # noqa: E402,F401  (GitHub's API through the relay)

DISTRO = sys.argv[1]
HOME = Path(os.environ["HOME"])
h = harness.start(settings={"scanning": True})
b, app, win = h.backend, h.app, h.win
from couriercollie import assets, packages, sources, updater  # noqa: E402

updater.ROOT = []  # root in the container: package installs without a password prompt
KIND = {"fedora": assets.KIND_RPM, "opensuse": assets.KIND_RPM, "ubuntu": assets.KIND_DEB,
        "debian": assets.KIND_DEB}.get(DISTRO, "")
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
    win.grabWindow().save(f"/out/{shots[0]:02d}-{name}.png")


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


def check_now():
    b.checkNow()
    pump(lambda: b.checking, 3)
    pump(lambda: not b.checking, 300)


def says(rid, when):
    """What the page and the list say now (printed, to read alongside the screenshots)."""
    d, row = b.details(rid), b.repo(rid)
    print(f"  {when}: page '{d.get('headline')}' ({d.get('versionText')}) missing={d.get('localMissing')} "
          f"update={d.get('canUpdate') and (d.get('updateAvailable') or d.get('newCopy') or d.get('statusKind') == 'notInstalled')}"
          f" | list '{row['checkText']}'", flush=True)
    return d, row


# ---- An AppImage ----------------------------------------------------------------------------------------------------
print(f"=== {DISTRO}: an AppImage (Neovim)", flush=True)
nvim = add("https://github.com/neovim/neovim", r"x86_64\.appimage$")
d = update(nvim)
path = Path(b._config.find(nvim).local_path)
check("installed through couriercollie", path.is_file(), d["updateNote"])
print("  $ rm the AppImage", flush=True)
path.unlink()
d, row = says(nvim, "after Refresh") if refresh(nvim) else (None, None)
shot("appimage-removed")
check("removed by hand: the page says it's gone", d["localMissing"] or d["statusKind"] == "notInstalled",
      (d["headline"], d["localMissing"]))
check_now()
d, row = says(nvim, "after Check Now")
check("…and the list doesn't say it's up to date", row["checkText"] != "Up to date", row["checkText"])
d = update(nvim)
print(f"  Update/Install again: {d['updateNote']}", flush=True)
check("…and it can be put back from the page", any(Path(b._config.find(nvim).local_path or "/x").parent.glob("*.appimage")),
      d["updateNote"])

# ---- A program --------------------------------------------------------------------------------------------------------
print(f"=== {DISTRO}: a program (lazygit)", flush=True)
lazy = add("https://github.com/jesseduffield/lazygit", r"_linux_x86_64\.tar\.gz$")
d = update(lazy)
link = Path(b._config.find(lazy).local_path)
check("installed through couriercollie", link.is_symlink() and link.exists(), d["updateNote"])
print("  $ rm ~/.local/bin/lazygit, and its folder", flush=True)
target = link.resolve().parent
link.unlink()
shutil.rmtree(target, ignore_errors=True)
d, row = says(lazy, "after Refresh") if refresh(lazy) else (None, None)
shot("program-removed")
check("removed by hand: the page says it's gone", d["localMissing"] or d["statusKind"] == "notInstalled",
      (d["headline"], d["localMissing"]))
check_now()
d, row = says(lazy, "after Check Now")
check("…and the list doesn't say it's up to date", row["checkText"] != "Up to date", row["checkText"])
d = update(lazy)
print(f"  Update/Install again: {d['updateNote']}", flush=True)
check("…and it can be put back from the page", Path(b._config.find(lazy).local_path or "/x").exists(), d["updateNote"])

# ---- A package --------------------------------------------------------------------------------------------------------
if KIND:
    remove = {"fedora": "dnf remove -y -q skate", "opensuse": "zypper -q -n remove skate",
              "ubuntu": "apt-get remove -y -qq skate", "debian": "apt-get remove -y -qq skate"}[DISTRO]
    print(f"=== {DISTRO}: a package (skate, {KIND})", flush=True)
    skate = add("https://github.com/charmbracelet/skate", r"(x86_64\.rpm|amd64\.deb)$")
    d = update(skate)
    check("installed through couriercollie", packages.installed_version(KIND, "skate")[1], d["updateNote"])
    print(f"  $ {remove}", flush=True)
    sh(remove)
    d, row = says(skate, "after Refresh") if refresh(skate) else (None, None)
    shot("package-removed")
    check("removed by hand: the page says it's gone", d["localMissing"] or d["statusKind"] == "notInstalled",
          (d["headline"], d["localMissing"]))
    check_now()
    d, row = says(skate, "after Check Now")
    check("…and the list doesn't say it's up to date", row["checkText"] != "Up to date", row["checkText"])
    # An older version, installed by hand from its release.
    rels = [r for r in sources.newest_releases(sources.RepoRef("github.com", "charmbracelet/skate"), "github", 5, False)]
    mine = r"x86_64\.rpm$" if KIND == assets.KIND_RPM else r"amd64\.deb$"  # (this distro's kind)
    old = next(a for a in rels[1].assets if re.search(mine, a.name))
    sh(f"curl -sL -o /tmp/{old.name} {old.url}")
    install = {"fedora": f"dnf install -y -q /tmp/{old.name}", "opensuse": f"zypper -q -n --no-gpg-checks install --allow-unsigned-rpm /tmp/{old.name}",
               "ubuntu": f"apt-get install -y -qq /tmp/{old.name}", "debian": f"apt-get install -y -qq /tmp/{old.name}"}[DISTRO]
    print(f"  $ install {old.name} by hand", flush=True)
    if out := sh(install):
        print("    " + out.replace("\n", "\n    ")[-600:], flush=True)
    d, row = says(skate, "after Refresh") if refresh(skate) else (None, None)
    shot("package-older-by-hand")
    check(f"the older version installed by hand is read ({rels[1].tag})", assets.same_version(d["versionText"], rels[1].tag)
          and d["updateAvailable"], (d["versionText"], d["headline"]))
    d = update(skate)
    check("…and Update brings it to the newest", packages.installed_version(KIND, "skate")[0].startswith(
        rels[0].tag.lstrip("v")), d["updateNote"])
    says(skate, "after Update")

# ---- A clone ----------------------------------------------------------------------------------------------------------
print(f"=== {DISTRO}: a clone (tmux's plugin manager)", flush=True)
tpm = add("https://github.com/tmux-plugins/tpm")
d = update(tpm)
clone = Path(b._config.find(tpm).local_path)
check("cloned through couriercollie (Install)", (clone / ".git").exists(), d["updateNote"])
print("  $ git reset --hard HEAD~3 (as if it were older)", flush=True)
sh(f"git -C {clone} reset -q --hard HEAD~3")
d, row = says(tpm, "after Refresh") if refresh(tpm) else (None, None)
check("an older commit by hand: the page says there are new commits", d["updateAvailable"], d["headline"])
print("  $ git pull (updated by hand)", flush=True)
sh(f"git -C {clone} pull -q")
d, row = says(tpm, "after Refresh") if refresh(tpm) else (None, None)
check("pulled by hand: up to date", d["statusKind"] == "current", d["headline"])
check_now()
d, row = says(tpm, "after Check Now")
check("…in the list too", row["checkText"] == "Up to date", row["checkText"])
print("  $ rm -rf the clone", flush=True)
shutil.rmtree(clone)
d, row = says(tpm, "after Refresh") if refresh(tpm) else (None, None)
shot("clone-removed")
check("removed by hand: the page says it's gone", d["localMissing"], (d["headline"], d["localMissing"]))
check_now()
d, row = says(tpm, "after Check Now")
check("…and the list doesn't say it's up to date", row["checkText"] != "Up to date", row["checkText"])

win.closeRepo()
shot("list")
print(f"=== {DISTRO}: {len(failures)} failures", flush=True)
for f in failures:
    print("  - " + f, flush=True)
