"""Installing a real RPM release file (bottom, ~1.6 MB from GitHub), with a simulated mouse: the Install… button and
its password note, the download and its checksum, reading the package from the file, then dnf. Only the last step is
a stand-in: "dnf" here notes what it was asked to install (and checks the file is a real RPM), so nothing is
installed and no password is asked for. Downloads go to a temporary folder.

    python3 -I devtools/check_rpm.py
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402

work = Path(tempfile.mkdtemp())
ID = "github.com/clementtsang/bottom"
settings = work / "repos.toml"
settings.write_text(f'[[repos]]\nid = "{ID}"\nname = "bottom"\nurl = "https://{ID}"\nhost = "github"\n'
                    'follow = "releases"\nasset_pattern = "bottom-*-1.x86_64.rpm"\nkind = "RPM"\ninstalled = "-"\n')
asked = work / "dnf-asked"
fake_dnf = work / "dnf"
fake_dnf.write_text(f'#!/bin/sh\necho "$@" > {asked}\nrpm -qp --qf "%{{NAME}} %{{VERSION}}" "$3" >> {asked}\n')
fake_dnf.chmod(0o755)

h = harness.start(copy_settings_from=settings)  # its downloads go to the run's own temporary cache folder
b = h.backend
from couriercollie import packages, updater  # noqa: E402

updater.ROOT = ["env"]  # instead of pkexec
packages.INSTALL["dnf"] = [str(fake_dnf), "install", "-y"]  # instead of dnf


def details():
    return b.details(ID)


def installed():
    said = asked.read_text() if asked.exists() else ""
    h.check("dnf was asked to install the downloaded file", said.startswith("install -y ") and ".rpm" in said, said)
    h.check("…a real RPM of bottom", f"bottom {details()['newestText']}" in said, said)
    h.check("…checked against GitHub's checksum", details()["updateNoteKind"] == "done", details()["updateNote"])
    h.check("the download was deleted", not any(updater.downloads_dir().glob("*.rpm")))
    h.check("its version is read from the installed package from now on",
            b._config.find(ID).local_path == "RPM package “bottom”")


h.run([
    (0, lambda: h.win.openRepo(ID)),
    h.until(lambda: details()["state"] == "ready", 60000),
    (500, lambda: h.check("Install… offered, saying it asks for the password",
                          h.find("text:Install…") is not None and details()["updateNeedsPassword"])),
    (0, lambda: h.shot("rpm-0-install")),
    (0, lambda: h.click("updateNow")),
    h.until(lambda: not details()["updating"], 300000),
    (500, installed),
    (0, lambda: h.shot("rpm-1-installed")),
])
