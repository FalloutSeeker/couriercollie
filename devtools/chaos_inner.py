"""GitHub misbehaving, in a container (devtools/check_chaos.sh), through the real window (off-screen) and real
projects: while a share of GitHub's answers go wrong (devtools/github_relay.py's chaos), projects are added, checked
again and again, their pages opened, installed and updated. Then GitHub behaves again, and everything must come
right. Checks: nothing crashes, every message is one written for you (not a Python error), a version only changes
when an install really happened, nothing half-downloaded is left, and it all recovers. Prints PASS/FAIL.

    python3 chaos_inner.py DISTRO     (with /work/chaos, the relay's chaos file, writable)
"""

import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, "/app/devtools")
import harness  # noqa: E402
import relay_client  # noqa: E402,F401

DISTRO = sys.argv[1]
HOME = Path(os.environ["HOME"])
CHAOS = Path("/work/chaos")
h = harness.start()
b, app, win = h.backend, h.app, h.win
from couriercollie import updater  # noqa: E402

updater.ROOT = []
failures = []
said: list[str] = []  # every message shown, to read at the end
b.addFailed.connect(said.append)

# Real projects, each a different kind: (address, the file followed, ending).
PROJECTS = [
    ("https://github.com/junegunn/fzf", r"linux_amd64\.tar\.gz$"),
    ("https://github.com/jesseduffield/lazygit", r"_linux_x86_64\.tar\.gz$"),
    ("https://github.com/charmbracelet/skate", r"_Linux_x86_64\.tar\.gz$"),
    ("https://github.com/neovim/neovim", r"x86_64\.appimage$"),
    ("https://github.com/BurntSushi/ripgrep", r"x86_64-unknown-linux-musl\.tar\.gz$"),
    ("https://github.com/sharkdp/bat", r"x86_64-unknown-linux-gnu\.tar\.gz$"),
    ("https://github.com/tmux-plugins/tpm", ""),
]
# Python's own errors, never meant to be shown.
RAW = re.compile(r"Something went wrong|Traceback|Errno|Error\(|KeyError|TypeError|AttributeError|IndexError|"
                 r"JSONDecodeError|NoneType|object has no|unexpected keyword|invalid literal|<html", re.I)


def check(label, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + label + (f"  ({detail})" if detail and not ok else ""), flush=True)
    if not ok:
        failures.append(label)
    return ok


def chaos(rate):
    CHAOS.write_text(str(rate))


def pump(cond=lambda: False, seconds=1.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.03)
    return cond()


def warnings():
    return [m for m in h.messages if "warning" in m.lower() or "error" in m.lower() or "traceback" in m.lower()]


def shown(rid):
    """Every text the list and the page show for this repo, kept to read at the end."""
    r, d = b.repo(rid), b.details(rid)
    texts = [r.get("checkText", ""), r.get("checkDetail", ""), d.get("error", ""), d.get("updateNote", ""), d.get("headline", ""),
             d.get("status", "")]
    said.extend(t for t in texts if t)
    return texts


def add(url, ending):
    """Add a project, trying again while GitHub misbehaves; returns its id or ""."""
    for _ in range(8):
        before = {r.id for r in b._config.repos}
        b.addRepo("", url)
        pump(lambda: not b.adding, 90)
        new = [r.id for r in b._config.repos if r.id not in before]
        if new:
            rid = new[0]
            for _ in range(8):
                if not ending or b._config.find(rid).asset_pattern:
                    return rid
                d = refresh(rid)
                name = next((f["name"] for f in d.get("fileChoices", []) if re.search(ending, f["name"])), "")
                if name:
                    b.pickAsset(rid, b._details[rid].releases[0].tag, name)
            return rid
    return ""


def refresh(rid):
    b.loadDetails(rid, True)
    pump(lambda: b.details(rid)["state"] in ("ready", "error") and not b.details(rid).get("comparing"), 90)
    shown(rid)
    return b.details(rid)


def check_now():
    b.checkNow()
    pump(lambda: b.checking, 3)
    pump(lambda: not b.checking, 600)
    for r in b._config.repos:
        shown(r.id)


def installed_ok(rid):
    r = b._config.find(rid)
    return r and r.installed not in ("", "-") and r.local_path and Path(r.local_path).exists()


def half_files():
    return sorted(str(p) for root in (HOME / "Applications", updater.programs_dir(), HOME / ".local/bin")
                  if root.exists() for p in root.rglob("*") if p.name.endswith(".part") or ".tmp" in p.name)


# ---- Adding, while 40% of GitHub's answers go wrong ---------------------------------------------------------------------
print(f"=== {DISTRO}: adding {len(PROJECTS)} projects, 40% of answers going wrong", flush=True)
chaos(0.4)
ids = [rid for url, ending in PROJECTS if (rid := add(url, ending))]
check("every project could be added, trying again", len(ids) == len(PROJECTS), [r.id for r in b._config.repos])

# ---- Checking, again and again --------------------------------------------------------------------------------------------
print(f"=== {DISTRO}: Check Now five times, 40% going wrong", flush=True)
for i in range(5):
    check_now()
    pump(seconds=1)
check("still running, no Qt warnings", not warnings(), warnings()[:3])

# ---- Pages, opened and refreshed -------------------------------------------------------------------------------------------
print(f"=== {DISTRO}: each page opened and refreshed three times", flush=True)
for rid in ids:
    win.openRepo(rid)
    for _ in range(3):
        refresh(rid)
check("…still no Qt warnings", not warnings(), warnings()[:3])

# ---- Installing, under chaos: either done, or not done and said why --------------------------------------------------------
print(f"=== {DISTRO}: Install each, 40% going wrong", flush=True)
for rid in ids:
    before = b._config.find(rid).installed
    refresh(rid)
    b.updateRepo(rid)
    pump(lambda: rid not in b._updating, 600)
    pump(seconds=0.5)
    d = b.details(rid)
    shown(rid)
    after = b._config.find(rid).installed
    if after != before:
        check(f"{rid}: version changed only with it installed", installed_ok(rid), (before, after, d["updateNote"]))
    print(f"  {rid}: {before!r} -> {after!r} | {d['updateNote'][:120]}", flush=True)
check("nothing half-downloaded left", half_files() == [], half_files())

# ---- GitHub behaves again: everything comes right --------------------------------------------------------------------------
print(f"=== {DISTRO}: GitHub behaves again", flush=True)
chaos(0)
pump(seconds=7)  # past the rate limits' reset
check_now()
failed = {r.id: (b.repo(r.id)["checkText"], b.repo(r.id)["checkDetail"]) for r in b._config.repos
          if b.repo(r.id)["checkText"].startswith("Couldn\u2019t") or "not rechecked" in b.repo(r.id)["checkText"]}
check("one check later, every project is checked", not failed, failed)
for rid in ids:
    if not installed_ok(rid):
        refresh(rid)
        b.updateRepo(rid)
        pump(lambda: rid not in b._updating, 600)
    shown(rid)
missing = [rid for rid in ids if not installed_ok(rid)]
check("…and every one installs", not missing, {rid: b.details(rid)["updateNote"] for rid in missing})
check_now()
behind = {r.id: b.repo(r.id)["checkText"] for r in b._config.repos if b.repo(r.id)["updateAvailable"]}
check("…and is up to date", not behind, behind)
check("nothing half-downloaded left at the end", half_files() == [], half_files())

raw = sorted({t for t in said if RAW.search(t)})
check("every message was written for you", not raw, raw[:8])
print("messages seen:", flush=True)
for t in sorted(set(said)):
    print("  · " + t[:160], flush=True)
print(f"qt warnings: {warnings()[:5]}", flush=True)
print(f"=== {DISTRO}: {len(failures)} failures", flush=True)
for f in failures:
    print("  - " + f, flush=True)
