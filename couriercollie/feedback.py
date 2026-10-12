"""Send Feedback (Settings): a new GitHub issue, opened in the browser with the details that help filled in. Nothing is
sent from here: the person reads it, writes, and submits it on GitHub. The list of tracked repos only if they ask.
"""

import os
import platform
from pathlib import Path
from urllib.parse import urlencode

from . import __version__, integration

ISSUES = "https://github.com/FalloutSeeker/couriercollie/issues/new"
# GitHub refuses longer addresses; the rest of the list is left out.
_MAX_URL = 7000


def distro(os_release: Path = Path("/etc/os-release")) -> str:
    try:
        lines = os_release.read_text(errors="replace").splitlines()
    except OSError:
        return platform.system()
    fields = dict(line.split("=", 1) for line in lines if "=" in line)
    return fields.get("PRETTY_NAME", fields.get("NAME", "Linux")).strip().strip('"')


def about(qt_version: str = "") -> list[str]:
    how = "installed package" if integration.INSTALLED else "run from source"
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "unknown").replace(":", ", ")
    return [f"couriercollie {__version__} ({how})", f"{distro()}, {desktop} desktop",
            f"Python {platform.python_version()}" + (f", Qt {qt_version}" if qt_version else "")]


def issue_url(repos: list[str] | None = None, qt_version: str = "") -> str:
    """The new-issue address. `repos`: the tracked repos' addresses, if the person chose to include them."""
    def url(listed: list[str], left_out: int) -> str:
        body = ["<!-- What happened, or what would you like? -->", "", "", "---", *about(qt_version)]
        if repos:
            body += ["", "Tracked repos:", *(f"- {r}" for r in listed)]
            if left_out:
                body.append(f"- …and {left_out} more")
        return f"{ISSUES}?{urlencode({'body': chr(10).join(body)})}"

    listed = list(repos or [])
    while len(address := url(listed, len(repos or []) - len(listed))) > _MAX_URL and listed:
        listed.pop()
    return address
