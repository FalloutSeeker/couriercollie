"""Flatpak bundles with the real flatpak: two versions of a small test app are made (on the freedesktop runtime
already installed system-wide), then the app installs the first from a "release", reads its version, finds it with a
scan, updates it to the second, and refuses a bundle holding another app. Installed into a temporary Flatpak
folder (FLATPAK_USER_DIR), so your own Flatpaks aren't touched.

    python3 -I devtools/check_flatpak.py
"""

import hashlib
import http.server
import os
import subprocess
import sys
import tempfile
import threading
from functools import partial
from pathlib import Path

RUNTIME = "org.freedesktop.Platform/x86_64/26.08"
APP = "org.example.CcTool"
work = Path(tempfile.mkdtemp())
os.environ["FLATPAK_USER_DIR"] = str(work / "flatpak")
os.environ["XDG_CACHE_HOME"] = str(work / "cache")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from colliecourier import assets, flatpaks, scan, sources, updater  # noqa: E402

failures = []


def check(label, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + label + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(label)


def bundle(app_id, version):
    """A bundle of a tiny app (a script that prints its version), with a GitHub homepage."""
    build, repo = work / f"build-{app_id}-{version}", work / "repo"
    (build / "files/bin").mkdir(parents=True)
    (build / "files/share/metainfo").mkdir(parents=True)
    (build / "metadata").write_text(f"[Application]\nname={app_id}\nruntime={RUNTIME}\n"
                                    f"sdk=org.freedesktop.Sdk/x86_64/26.08\ncommand=cc-tool\n")
    (build / "files/bin/cc-tool").write_text(f"#!/bin/sh\necho {version}\n")
    (build / "files/bin/cc-tool").chmod(0o755)
    (build / f"files/share/metainfo/{app_id}.metainfo.xml").write_text(
        f'<?xml version="1.0"?>\n<component type="console-application"><id>{app_id}</id><name>CC Tool</name>'
        f'<summary>test</summary><url type="homepage">https://github.com/example/tool</url>'
        f'<releases><release version="{version}" date="2026-10-01"/></releases></component>\n')
    out = work / "release" / f"cc-tool-{app_id.rsplit('.', 1)[-1]}-{version}.flatpak"
    out.parent.mkdir(exist_ok=True)
    for args in (["build-finish", str(build)], ["build-export", str(repo), str(build)],
                 ["build-bundle", str(repo), str(out), app_id]):
        subprocess.run(["flatpak", *args], check=True, capture_output=True)
    return out


if subprocess.run(["flatpak", "info", "--system", RUNTIME.replace("/x86_64/", "//")], capture_output=True).returncode:
    sys.exit(f"Needs the {RUNTIME} runtime installed system-wide (it isn't), to make the test app.")
files = [bundle(APP, "1.0"), bundle(APP, "2.0"), bundle("org.example.Other", "2.0")]


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), partial(Quiet, directory=str(work / "release")))
threading.Thread(target=server.serve_forever, daemon=True).start()


def asset(path):
    return sources.Asset(path.name, f"http://127.0.0.1:{server.server_port}/{path.name}", path.stat().st_size,
                         f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}")


v1, v2, other = (asset(f) for f in files)
info = assets.classify(v1.name, v1.url)
check("a release's .flatpak suits this computer", (info.kind, info.suits) == (assets.KIND_FLATPAK, True), str(info))
check("the bundle says which app it holds", flatpaks.bundle_app(files[0])[0] == APP)
found, verified = updater.install_flatpak(v1, [])
check("installs it, for you", (found, verified, flatpaks.installation(APP)) == (APP, True, "user"))
check("its version is read back", flatpaks.installed_version(APP) == ("1.0", True), str(flatpaks.installed_version(APP)))
check("…as a scanned repo's place would read it", scan.version_on_disk(flatpaks.place(APP)) == ("1.0", True))
mine = [f for f in scan.find_flatpak_bundles() if f.path == flatpaks.place(APP)]
check("a scan finds it, as installed from a bundle", len(mine) == 1 and mine[0].id == "github.com/example/tool",
      str(mine))
updater.install_flatpak(v2, [], APP)
check("updates it", flatpaks.installed_version(APP) == ("2.0", True), str(flatpaks.installed_version(APP)))
ran = subprocess.run(["flatpak", "run", "--user", APP], capture_output=True, text=True).stdout.strip()
check("…and the new version runs", ran == "2.0", ran)
try:
    updater.install_flatpak(other, [], APP)
    check("refuses a bundle holding another app", False)
except updater.UpdateError as e:
    check("refuses a bundle holding another app", "not “org.example.CcTool”" in str(e), str(e))
server.shutdown()
subprocess.run(["rm", "-rf", str(work)])
print("FAILURES:", failures or "none")
sys.exit(1 if failures else 0)
