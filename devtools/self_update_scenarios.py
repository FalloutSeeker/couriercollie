"""What can happen when couriercollie (or another project's package) updates, on one distro, in a container, after
devtools/self_update_inner.py (devtools/check_self_update.sh). Each situation starts afresh: the version it needs
installed with the package manager, the stand-in for GitHub (devtools/github_standin.py) serving the releases it
needs, new settings. The packages are real: couriercollie's, built three times (OLD, MID, NEW), and skate's from its
GitHub releases (a project none of the distros offers, so the package manager doesn't update it). Prints
PASS/FAIL lines.

    python3 self_update_scenarios.py DISTRO OLD MID NEW
"""

import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

DISTRO, OLD, MID, NEW = sys.argv[1:5]
sys.path[:] = [p for p in sys.path if not p.startswith("/app") and p not in ("", ".")]  # the installed copy only
sys.path.insert(0, "/app/devtools")
import relay_client  # noqa: E402,F401  (GitHub's API: the stand-in)

os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtCore import QCoreApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
from couriercollie import assets, packages, updater  # noqa: E402
from couriercollie.backend import Backend  # noqa: E402
from couriercollie.config import TrackedRepo  # noqa: E402

ALL = Path("/work/releases")  # every release, as built or downloaded
SERVED = Path("/tmp/releases")  # what the stand-in serves now: set up for each situation
ME, OTHER = "FalloutSeeker__couriercollie", "charmbracelet__skate"
SETTINGS = Path.home() / ".config/couriercollie/repos.toml"
KIND = {"fedora": assets.KIND_RPM, "opensuse": assets.KIND_RPM, "ubuntu": assets.KIND_DEB,
        "debian": assets.KIND_DEB, "arch": assets.KIND_ARCH}[DISTRO]
updater.ROOT = []  # root in the container
failures = []


def check(label, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + label + (f"  ({detail})" if detail and not ok else ""), flush=True)
    if not ok:
        failures.append(label)
    return ok


def mine(name: str) -> bool:
    """Whether a couriercollie release file is the one for this distro (as its pattern would pick)."""
    return {"fedora": ".fc" in name and name.endswith(".rpm"),
            "opensuse": name.endswith("-1.noarch.rpm"),
            "ubuntu": name.endswith(".deb"), "debian": name.endswith(".deb"),
            "arch": name.endswith(".pkg.tar.zst")}[DISTRO]


def file_of(version: str) -> Path:
    return next(p for p in (ALL / ME / f"v{version}").iterdir() if mine(p.name))


def install(path: Path):
    """Install exactly this package file, older or not (a downgrade for a fresh start)."""
    command = {assets.KIND_RPM: ["rpm", "-U", "--oldpackage", "--replacepkgs", "--nodeps", str(path)],
               assets.KIND_DEB: ["dpkg", "-i", str(path)],
               assets.KIND_ARCH: ["pacman", "-U", "--noconfirm", "--nodeps", str(path)]}[KIND]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"couldn't install {path.name}: {result.stderr[-400:]}")


def serve(project: str, *tags: str, markers: dict | None = None, drop: tuple = ()):
    """The stand-in now serves these releases of the project (and others' as they were); `markers`: {tag: [".nodigest",
    …]}; `drop`: file names left out."""
    shutil.rmtree(SERVED / project, ignore_errors=True)
    for tag in tags:
        (SERVED / project / tag).mkdir(parents=True)
        for f in (ALL / project / tag).iterdir():
            if f.name not in drop:
                shutil.copy(f, SERVED / project / tag / f.name)
        for marker in (markers or {}).get(tag, []):
            (SERVED / project / tag / marker).touch()


def installed() -> str:
    return packages.installed_version(KIND, "couriercollie")[0]


def fresh(version: str, prereleases: bool = False) -> Backend:
    """couriercollie at this version, as just started for the first time (tracking itself), with a check done."""
    install(file_of(version))
    SETTINGS.unlink(missing_ok=True)
    b = Backend(SETTINGS)
    b._run = lambda work, done: done(*_attempt(work))
    b._track_myself()
    b._config.find(Backend.MYSELF).installed = version  # this process is OLD's code, whatever is on disk now
    b._config.find(Backend.MYSELF).prereleases = prereleases
    b.loadDetails(Backend.MYSELF, True)
    b.checkNow()
    return b


def _attempt(work):
    try:
        return work(), None
    except Exception as e:  # noqa: BLE001
        return None, e


def update(b: Backend, repo_id: str = Backend.MYSELF) -> dict:
    b.updateRepo(repo_id)
    return b.details(repo_id)


def update_button(d: dict) -> bool:
    """Whether the page shows Update (as RepoDetailPage.qml decides: it can be updated here, and there's one)."""
    return d["canUpdate"] and d["updateAvailable"] and not d["updating"]


def offered(b: Backend) -> str:
    d = b.details(Backend.MYSELF)
    return d["headline"] + (" (Update offered)" if update_button(d) else "")


# ---------------------------------------------------------------------------------------------------------------------

print(f"=== {DISTRO}: situations", flush=True)

print("- two versions behind: straight to the newest", flush=True)
serve(ME, f"v{OLD}", f"v{MID}", f"v{NEW}")
b = fresh(OLD)
d = update(b)
check(f"{OLD} -> {NEW}, skipping {MID}", installed().startswith(NEW), (installed(), d["updateNote"]))
b.shutdown()

print("- the newest release has no file for this distro", flush=True)
serve(ME, f"v{OLD}", f"v{MID}", drop=(file_of(MID).name,))
b = fresh(OLD)
d = b.details(Backend.MYSELF)
print(f"  page: {d['headline']} / list: {b.repo(Backend.MYSELF)['checkText']}", flush=True)
check("…it says your file isn't in it, and offers no Update", d["yourFileMissing"] and not update_button(d)
      and not b.repo(Backend.MYSELF)["updateAvailable"], offered(b))
d = update(b)  # (as the list's button would, were it shown)
check("…and nothing else is installed instead", installed().startswith(OLD), (installed(), d["updateNote"]))
b.shutdown()

print("- the file doesn't match its published checksum", flush=True)
serve(ME, f"v{OLD}", f"v{MID}", markers={f"v{MID}": [".baddigest"]})
b = fresh(OLD)
d = update(b)
check("…refused, with a reason", d["updateNoteKind"] == "error" and "checksum" in d["updateNote"].lower(),
      d["updateNote"])
check(f"…and {OLD} is still installed", installed().startswith(OLD), installed())
b.shutdown()

print("- the download stops halfway", flush=True)
serve(ME, f"v{OLD}", f"v{MID}", markers={f"v{MID}": [".truncate"]})
b = fresh(OLD)
d = update(b)
check("…refused: it didn't finish", d["updateNoteKind"] == "error" and "didn’t finish" in d["updateNote"],
      d["updateNote"])
check(f"…and {OLD} is still installed", installed().startswith(OLD), installed())
check("…with nothing half-downloaded left", not any(updater.downloads_dir().glob("*")) if updater.downloads_dir()
      .exists() else True, list(updater.downloads_dir().glob("*")))
b.shutdown()

print("- GitHub gives no checksum, but the release has SHA256SUMS", flush=True)
serve(ME, f"v{OLD}", f"v{MID}", markers={f"v{MID}": [".nodigest"]})
b = fresh(OLD)
d = update(b)
check("…checked against SHA256SUMS, and installed", installed().startswith(MID)
      and "published checksum" in d["updateNote"], d["updateNote"])
b.shutdown()

print("- no checksum anywhere", flush=True)
serve(ME, f"v{OLD}", f"v{MID}", markers={f"v{MID}": [".nodigest"]}, drop=("SHA256SUMS",))
b = fresh(OLD)
d = update(b)
check("…installed, with a warning saying so", installed().startswith(MID) and d["updateNoteKind"] == "warning",
      (d["updateNoteKind"], d["updateNote"]))
print(f"  {d['updateNote']}", flush=True)
b.shutdown()

print("- the only newer release is a test version", flush=True)
serve(ME, f"v{OLD}", f"v{MID}", markers={f"v{MID}": [".prerelease"]})
b = fresh(OLD)
check("…not offered", not b.repo(Backend.MYSELF)["updateAvailable"], offered(b))
b.shutdown()
b = fresh(OLD, prereleases=True)
check("…offered with Show test versions on", b.repo(Backend.MYSELF)["updateAvailable"], offered(b))
b.shutdown()

print("- yours is newer than every release (installed by hand from a newer build)", flush=True)
serve(ME, f"v{OLD}", f"v{MID}")
b = fresh(NEW)
check("…no older version offered", not update_button(b.details(Backend.MYSELF))
      and not b.repo(Backend.MYSELF)["updateAvailable"], offered(b))
print(f"  list: {b.repo(Backend.MYSELF)['checkText']}", flush=True)
check(f"…and {NEW} stays", installed().startswith(NEW), installed())
b.shutdown()

print("- a release file that's another program's package under couriercollie's name", flush=True)
if (ALL / OTHER).exists() and KIND != assets.KIND_ARCH:
    serve(ME, f"v{OLD}", f"v{MID}")
    impostor = next(p for p in (ALL / OTHER).glob("*/*") if p.suffix == (".rpm" if KIND == assets.KIND_RPM else ".deb"))
    target = SERVED / ME / f"v{MID}" / file_of(MID).name
    shutil.copy(impostor, target)
    b = fresh(OLD)
    d = update(b)
    check("…refused: it's not the couriercollie package", d["updateNoteKind"] == "error"
          and "skate" in d["updateNote"], d["updateNote"])
    check(f"…and {OLD} is still installed", installed().startswith(OLD), installed())
    b.shutdown()

print("- the package manager is busy with something else", flush=True)
serve(ME, f"v{OLD}", f"v{MID}")
b = fresh(OLD)
holder = None
if KIND == assets.KIND_DEB:  # apt and dpkg take an fcntl lock on this file
    holder = subprocess.Popen([sys.executable, "-c", "import fcntl, time; f = open('/var/lib/dpkg/lock-frontend', "
                               "'w'); fcntl.lockf(f, fcntl.LOCK_EX); time.sleep(600)"])
elif KIND == assets.KIND_ARCH:  # pacman: its lock file exists
    Path("/var/lib/pacman/db.lck").touch()
elif DISTRO == "opensuse":  # zypper: a running process holds its lock
    holder = subprocess.Popen(["sleep", "600"])
    Path("/run/zypp.pid").write_text(str(holder.pid))
elif DISTRO == "fedora":  # dnf: another dnf at work (it waits for the other to finish, rather than failing)
    holder = subprocess.Popen(["dnf", "install", "-y", "-q", "vim-enhanced"], stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL)
    time.sleep(3)
time.sleep(1)
d = update(b)
print(f"  {d['updateNoteKind']}: {d['updateNote']}", flush=True)
if DISTRO == "fedora":
    check("…dnf waits for the other one, then installs", installed().startswith(MID), (installed(), d["updateNote"]))
else:
    check("…it says the package manager is busy", "busy with something else" in d["updateNote"], d["updateNote"])
    check(f"…and {OLD} is still installed", installed().startswith(OLD), installed())
if holder:
    holder.kill()
    holder.wait()
Path("/var/lib/pacman/db.lck").unlink(missing_ok=True)
Path("/run/zypp.pid").unlink(missing_ok=True)
if DISTRO != "fedora":
    d = update(b)
    check("…and once it's free, Update works", installed().startswith(MID), (installed(), d["updateNote"]))
b.shutdown()

if (ALL / OTHER).exists() and KIND != assets.KIND_ARCH:
    print("- another project's package, and couriercollie, updated at the same time", flush=True)
    tags = sorted((t.name for t in (ALL / OTHER).iterdir()), key=lambda t: [int(n) for n in t.lstrip("v").split(".")])
    other_old, other_new = tags[0], tags[-1]
    serve(OTHER, other_old, other_new)
    serve(ME, f"v{OLD}", f"v{MID}")
    old_other = next(p for p in (ALL / OTHER / other_old).iterdir() if p.suffix == (".rpm" if KIND == assets.KIND_RPM
                                                                                     else ".deb"))
    install(old_other)
    b = fresh(OLD)
    del b._run  # back to the real worker threads: both at once
    other_id = "github.com/charmbracelet/skate"
    b.addRepo("", "https://github.com/charmbracelet/skate")
    end = time.monotonic() + 60
    while time.monotonic() < end and (b.adding or not b._config.find(other_id)):
        QCoreApplication.processEvents()
        time.sleep(0.05)
    repo = b._config.find(other_id)
    if not repo.asset_pattern:
        name = next(f["name"] for f in b.details(other_id)["fileChoices"] if f["name"].endswith(old_other.suffix))
        b.pickAsset(other_id, other_new, name)
    repo.installed = other_old  # as Set as My Version would: the package found here is that version
    b.updateRepo(Backend.MYSELF)
    b.updateRepo(other_id)
    end = time.monotonic() + 300
    while time.monotonic() < end and b._updating:
        QCoreApplication.processEvents()
        time.sleep(0.05)
    for rid in (Backend.MYSELF, other_id):
        print(f"  {rid}: {b.details(rid)['updateNote']}", flush=True)
    other_have = packages.installed_version(KIND, "skate")[0]
    check(f"…couriercollie {MID} and skate {other_new} both installed, one after the other",
          installed().startswith(MID) and other_have.startswith(other_new.lstrip("v")), (installed(), other_have))
    ran = subprocess.run(["skate", "--version"], capture_output=True, text=True).stdout.strip()
    check("…and the new skate runs", other_new.lstrip("v") in ran, ran)
    b.shutdown()

print(f"=== {DISTRO}: {len(failures)} failures", flush=True)
for f in failures:
    print("  - " + f, flush=True)
sys.exit(1 if failures else 0)
