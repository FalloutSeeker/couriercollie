"""Edge cases, for real, in a container (devtools/check_edges.sh): the network dropping partway through a download, a
full disk, the app killed partway through an update, two copies started, a broken settings file. Real projects and
real downloads (GitHub through devtools/github_relay.py). Needs NET_ADMIN in the container, to cut its network.
Prints PASS/FAIL lines.
"""

import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/devtools")
import relay_client  # noqa: E402,F401

print("GitHub through the relay:", relay_client.RELAY or "no", flush=True)

os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
from couriercollie import config, updater  # noqa: E402
from couriercollie.backend import Backend  # noqa: E402

HOME = Path(os.environ["HOME"])
APPS = HOME / "Applications"
SETTINGS = HOME / ".config/couriercollie/repos.toml"
NVIM = "https://github.com/neovim/neovim"
failures = []


def check(label, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + label + (f"  ({detail})" if detail and not ok else ""), flush=True)
    if not ok:
        failures.append(label)


def sh(command):
    return subprocess.run(command, shell=True, capture_output=True, text=True)


IFACE = sh("ip -o link | awk -F': ' '$2 != \"lo\" {print $2; exit}'").stdout.strip().split("@")[0]


def network(up: bool):
    sh(f"ip link set dev {IFACE} {'up' if up else 'down'}")
    if up:  # the route goes with the link: put it back
        sh(f"ip route replace default dev {IFACE}")


def slow_network(on: bool):
    # So a download takes long enough to be cut partway (a real download, just slower).
    sh(f"tc qdisc {'replace' if on else 'del'} dev {IFACE} root" + (" tbf rate 8mbit burst 32kbit latency 400ms"
                                                                      if on else ""))


def backend():
    SETTINGS.unlink(missing_ok=True)
    b = Backend(SETTINGS)

    def at_once(work, done):
        try:
            result, error = work(), None
        except Exception as e:  # noqa: BLE001
            result, error = None, e
        done(result, error)
    b._run = at_once
    return b


def add_nvim(b):
    b.addRepo("", NVIM)
    rid = "github.com/neovim/neovim"
    d = b.details(rid)
    name = next(f["name"] for f in d["fileChoices"] if f["name"].endswith("x86_64.appimage"))
    b.pickAsset(rid, b._details[rid].releases[0].tag, name)
    return rid


def parts():
    return sorted(p.name for p in APPS.glob(".*.part")) if APPS.exists() else []


if sys.argv[1:] == ["download-only"]:  # for 3.: an install, to be killed partway
    b = backend()
    b.updateRepo(add_nvim(b))
    sys.exit(0)

print(f"network interface: {IFACE}", flush=True)

# ---- 1. The network drops partway through a download ----------------------------------------------------------------
print("=== the network drops partway through a download", flush=True)
b = backend()
rid = add_nvim(b)
slow_network(True)


def cut_when_started():
    end = time.monotonic() + 60
    while time.monotonic() < end:
        if any(p.stat().st_size > 1_000_000 for p in APPS.glob(".*.part")) if APPS.exists() else False:
            network(False)
            print("  (network cut partway)", flush=True)
            return
        time.sleep(0.02)


cutter = threading.Thread(target=cut_when_started)
cutter.start()
started = time.monotonic()
b.updateRepo(rid)
cutter.join()
info = b.details(rid)
check("the install stops with a message saying the download didn't finish",
      info["updateNoteKind"] == "error" and "didn’t finish" in info["updateNote"], info["updateNote"])
print(f"  after {time.monotonic() - started:.0f} s: {info['updateNote']}", flush=True)
check("…nothing half-downloaded is left behind", parts() == [], parts())
check("…and it's still not installed", b._config.find(rid).installed in ("", "-"), b._config.find(rid).installed)
network(True)
slow_network(False)
time.sleep(2)
b.updateRepo(rid)
info = b.details(rid)
check("once the network is back, Install works", info["updateNoteKind"] != "error", info["updateNote"])
installed = b._config.find(rid).local_path
b.shutdown()

# ---- 2. A full disk -------------------------------------------------------------------------------------------------
print("=== a full disk", flush=True)
# ~/Applications is a 40 MB disk here (check_edges.sh): fill it so the next download can't fit.
filler = APPS / "filler"
sh(f"head -c 20M /dev/zero > {filler}")
b = backend()
rid = add_nvim(b)
b._config.find(rid).installed = "v0.1.0"  # an old version, so Update is offered
b._config.find(rid).local_path = installed
b._config.find(rid).source = config.SOURCE_SCANNED
before = Path(installed).stat().st_size if installed and Path(installed).exists() else 0
b.updateRepo(rid)
info = b.details(rid)
check("Update says there isn't enough free space", info["updateNoteKind"] == "error"
      and "enough free space" in info["updateNote"], info["updateNote"])
check("…and the AppImage you have is untouched", before and Path(installed).stat().st_size == before, installed)
check("…with nothing half-downloaded left", parts() == [], parts())
filler.unlink()
b.shutdown()

# ---- 3. The app killed partway through an update ---------------------------------------------------------------------
print("=== the app killed partway through an update", flush=True)
Path(installed).unlink(missing_ok=True)
slow_network(True)
child = subprocess.Popen([sys.executable, __file__, "download-only"], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
end = time.monotonic() + 90
while time.monotonic() < end and not any(p.stat().st_size > 1_000_000 for p in APPS.glob(".*.part")):
    time.sleep(0.05)
child.send_signal(signal.SIGKILL)
child.wait()
slow_network(False)
left = parts()
check("killed partway, a half-downloaded file is left", bool(left), left)
# As if an hour went by (cleaning only takes what's old enough not to be another copy's download in progress).
old = time.time() - updater.LEFTOVER_AGE - 60
for p in APPS.glob(".*.part"):
    os.utime(p, (old, old))
opened = subprocess.Popen(["couriercollie"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(8)
check("the next start removes it", parts() == [], parts())

# ---- 4. Two copies --------------------------------------------------------------------------------------------------
print("=== two copies started", flush=True)
started = time.monotonic()
second = subprocess.run(["couriercollie"], capture_output=True, text=True, timeout=30)
check("a second start hands over to the open one and ends", second.returncode == 0 and time.monotonic() - started < 10,
      (second.returncode, second.stdout + second.stderr))
check("…which is still running", opened.poll() is None)
reset = subprocess.run(["couriercollie", "--reset"], capture_output=True, text=True, timeout=30)
check("--reset while it's open is refused, with a reason", reset.returncode != 0 and "Close it" in reset.stdout,
      reset.stdout + reset.stderr)
opened.terminate()
opened.wait(timeout=20)

# ---- 5. A broken settings file ---------------------------------------------------------------------------------------
print("=== a broken settings file", flush=True)
SETTINGS.parent.mkdir(parents=True, exist_ok=True)
broken = '[[repos]]\nid = "github.com/a/b"\nname = "unfinished\n'
SETTINGS.write_text(broken)
opened = subprocess.Popen(["couriercollie"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
time.sleep(8)
check("the app still opens", opened.poll() is None, opened.poll())
opened.terminate()
out = opened.communicate(timeout=20)[0]
check("…and the broken file is left as it was (nothing is lost)", SETTINGS.read_text() == broken)
check("…with no crash", "Traceback" not in out, out[-500:])
checked = subprocess.run(["couriercollie", "--check"], capture_output=True, text=True, timeout=60)
check("a background check says what's wrong instead of crashing", checked.returncode == 1 and checked.stderr.strip()
      and "Traceback" not in checked.stderr, checked.stderr[-300:])
print(f"  --check says: {checked.stderr.strip()}", flush=True)

print(f"=== {len(failures)} failures", flush=True)
for f in failures:
    print("  - " + f, flush=True)
sys.exit(1 if failures else 0)
