"""Run inside a distro's container by devtools/check_distros.sh, as root there: the app installs a small test package
(made just before, in the distro's own format, with a GitHub homepage) with the distro's real package manager, finds
it with a scan, reads its version, and updates it to a newer one. Nothing outside the container is touched.

    python3 devtools/distro_inner.py <kind> <folder with the v1.0 and v2.0 packages>
"""

import hashlib
import http.server
import sys
import threading
from functools import partial
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from couriercollie import assets, packages, scan, sources, updater  # noqa: E402

KIND = {"rpm": assets.KIND_RPM, "deb": assets.KIND_DEB, "arch": assets.KIND_ARCH}[sys.argv[1]]
folder = Path(sys.argv[2])
NAME = "cc-test-tool"
failures = []


def check(label, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + label + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(label)


# The release's files, served as a project's would be.
class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), partial(Quiet, directory=str(folder)))
threading.Thread(target=server.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{server.server_port}/"


def asset(version):
    path = next(p for p in folder.iterdir() if p.name.startswith(f"{NAME}") and f"{version}" in p.name)
    return sources.Asset(path.name, base + path.name, path.stat().st_size,
                         f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}")


updater.ROOT = []  # root already, in the container: no password to ask for
tool = packages.tool_for(KIND)
print(f"package manager: {tool}")
v1, v2 = asset("1.0"), asset("2.0")
check("the release's package suits this computer", assets.classify(v1.name, v1.url).suits,
      str(assets.classify(v1.name, v1.url)))
check("…and is this distro's kind", assets.classify(v1.name, v1.url).kind == KIND)
name, version, verified, used = updater.install_package(v1, [], KIND)
check("installs it", (name, version, verified, used) == (NAME, "1.0", True, tool), str((name, version, verified, used)))
check("its installed version is read back", packages.installed_version(KIND, NAME) == ("1.0", True),
      str(packages.installed_version(KIND, NAME)))
check("…as a scanned repo's place would read it", scan.version_on_disk(packages.place(KIND, NAME)) == ("1.0", True))
found = scan.find_packages()
mine = [f for f in found if f.name == NAME]
if KIND == assets.KIND_ARCH:
    check("not listed by a scan (pacman can't tell it from an AUR build)", mine == [], str(found))
else:
    check("a scan finds it, as installed from a downloaded file", len(mine) == 1 and mine[0].id ==
          "github.com/example/tool" and mine[0].version == "1.0", str(found))
name, version, _, _ = updater.install_package(v2, [], KIND, package=NAME)
check("updates it", packages.installed_version(KIND, NAME) == ("2.0", True), str(packages.installed_version(KIND, NAME)))
try:
    updater.install_package(v1, [], KIND, package="something-else")
    check("refuses a package with another name", False)
except updater.UpdateError as e:
    check("refuses a package with another name", "not “something-else”" in str(e), str(e))
print("FAILURES:", failures or "none")
sys.exit(1 if failures else 0)
