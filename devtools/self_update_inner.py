"""couriercollie updating itself, in a container (devtools/check_self_update.sh): the installed v0.6.0 package (not the
project folder: what users have) tracks itself, finds the newer release on the stand-in for GitHub
(devtools/github_standin.py), and installs it with this distro's package manager. Then the new version is checked:
what the package manager says, what a fresh start of the app is, and that it now says it's up to date.

    python3 self_update_inner.py DISTRO OLD NEW
"""

import os
import subprocess
import sys
from pathlib import Path

DISTRO, OLD, NEW = sys.argv[1:4]
sys.path[:] = [p for p in sys.path if not p.startswith("/app") and p not in ("", ".")]  # the installed copy only
sys.path.insert(0, "/app/devtools")
import relay_client  # noqa: E402,F401  (GitHub's API: the stand-in)

os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
import couriercollie  # noqa: E402
from couriercollie import assets, packages, updater  # noqa: E402
from couriercollie.backend import Backend  # noqa: E402

SETTINGS = Path.home() / ".config/couriercollie/repos.toml"
failures = []


def check(label, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + label + (f"  ({detail})" if detail and not ok else ""), flush=True)
    if not ok:
        failures.append(label)


def fresh(code):
    """A new Python process (the files on disk, not this one's memory), with the same settings."""
    return subprocess.run([sys.executable, "-c", "import sys; sys.path[:] = [p for p in sys.path if not "
                           "p.startswith('/app') and p not in ('', '.')]; sys.path.insert(0, '/app/devtools'); "
                           "import relay_client; " + code], capture_output=True, text=True, timeout=120)


check(f"the installed package is running (from {couriercollie.__file__})",
      not couriercollie.__file__.startswith("/app") and couriercollie.__version__ == OLD, couriercollie.__version__)
b = Backend(SETTINGS)


def at_once(work, done):  # one step after another
    try:
        result, error = work(), None
    except Exception as e:  # noqa: BLE001
        result, error = None, e
    done(result, error)


b._run = at_once
updater.ROOT = []  # root in the container: the package manager runs without a password prompt
b._track_myself()  # as the first start does
me = b._config.find(Backend.MYSELF)
check("it tracks itself, as its own package", me and me.installed == OLD and me.kind in (assets.KIND_RPM, assets.KIND_DEB, assets.KIND_ARCH)
      and me.asset_pattern, me and (me.installed, me.kind, me.asset_pattern, me.local_path))
print(f"  follows {me.asset_pattern} ({me.local_path})", flush=True)

b.checkNow()
row = b.repo(Backend.MYSELF)
check(f"Check Now finds v{NEW}", row["updateAvailable"] and NEW in row["checkText"], row["checkText"])
b.loadDetails(Backend.MYSELF, True)
d = b.details(Backend.MYSELF)
check("its page offers the update", d["canUpdate"] and d["statusKind"] == "update", (d["headline"], d["status"]))
release = next(r for r in d["releases"] if r["tag"] == f"v{NEW}")
picked = [f["name"] for f in release["assets"] if f["selected"]]
print(f"  its file in v{NEW}: {picked}", flush=True)
check("…exactly one file, the one for this distro", len(picked) == 1, picked)

b.updateRepo(Backend.MYSELF)
d = b.details(Backend.MYSELF)
print(f"  {d['updateNote']}", flush=True)
check(f"Update installs v{NEW}", d["updateNoteKind"] != "error" and b._config.find(Backend.MYSELF).installed
      in (NEW, f"v{NEW}"), d["updateNote"])
check("…checked against the published checksum", "published checksum" in d["updateNote"], d["updateNote"])
b.shutdown()

have = packages.installed_version(me.kind, "couriercollie")[0]
check(f"the package manager has couriercollie {NEW}", have.startswith(NEW), have)
started = fresh("import couriercollie; print(couriercollie.__version__)")
check(f"a fresh start is couriercollie {NEW}", started.stdout.strip() == NEW, started.stdout + started.stderr[-300:])
after = fresh("import os; os.environ['QT_QPA_PLATFORM'] = 'offscreen'\n"
              "from PySide6.QtWidgets import QApplication; app = QApplication([])\n"
              "from pathlib import Path; from couriercollie.backend import Backend\n"
              f"b = Backend(Path('{SETTINGS}')); b._run = lambda w, d: d(w(), None); b.checkNow()\n"
              "print(b.repo(Backend.MYSELF)['checkText']); b.shutdown()")
check("…and it says it's up to date", after.stdout.strip().endswith("Up to date"), after.stdout + after.stderr[-300:])
window = subprocess.run(["timeout", "8", "couriercollie"], capture_output=True, text=True,
                        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})
check("the new version's window starts", window.returncode == 124, window.stderr[-300:])
check("its menu entry is still there", Path("/usr/share/applications/couriercollie.desktop").exists())

print(f"=== {DISTRO}: {len(failures)} failures", flush=True)
sys.exit(1 if failures else 0)
