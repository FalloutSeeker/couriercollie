"""Signing in to GitHub (DESIGN.md §8): optional, and read-only. It raises GitHub's limit from 60 requests an hour to
5,000, and makes "nothing changed" answers free.

Signing in is with a code entered at github.com/login/device (GitHub's device flow, through couriercollie's OAuth
App). The login asks for no access to your account, so it can only read public information. It's kept in the
desktop's password store (the Secret Service: KDE Wallet on Plasma, GNOME Keyring on GNOME, …) through secret-tool,
never in the settings file. (Reusing the GitHub CLI's login was left out on purpose: it can usually change your
repositories, which a read-only app has no business holding.)

The login is only ever sent to api.github.com (sources.py).
"""

import http.client
import json
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

# couriercollie's OAuth App on GitHub. Not a secret: the device flow needs no client secret, so none is kept anywhere.
CLIENT_ID = "Ov23liqaEeYC1knX2lX1"
DEVICE_CODE_URL = "https://github.com/login/device/code"
TOKEN_URL = "https://github.com/login/oauth/access_token"
# Where the code is entered. Always this address, whatever GitHub's answer says, so the button can only open GitHub.
VERIFY_URL = "https://github.com/login/device"
# Where the login is kept in the password store.
SECRET = ["service", "couriercollie", "account", "github"]
TIMEOUT = 20

# Signed in (Settings.github_login): with a code, the only way.
WITH_CODE = "app"


class LoginError(Exception):
    """Why signing in didn't work, for the user."""


@dataclass
class DeviceCode:
    device_code: str
    user_code: str  # what you type at verification_uri, e.g. "WDJB-MJHT"
    verification_uri: str
    interval: int  # seconds between asking whether you've approved it
    expires_in: int


def _post(url: str, fields: dict) -> dict:
    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(url, data=data, headers={"Accept": "application/json",
                                                          "User-Agent": "couriercollie"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            answer = json.load(resp)
    except urllib.error.HTTPError as e:
        raise LoginError(f"GitHub answered with an error ({e.code}). Try again later.") from e
    except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as e:
        raise LoginError("Couldn’t reach github.com. Check your internet connection.") from e
    except ValueError as e:
        raise LoginError("GitHub sent an answer that couldn’t be read.") from e
    if not isinstance(answer, dict):
        raise LoginError("GitHub sent an answer that couldn’t be read.")
    return answer


def start(post=_post) -> DeviceCode:
    """Ask GitHub for a code to sign in with. No access is asked for (no scopes): public information only."""
    answer = post(DEVICE_CODE_URL, {"client_id": CLIENT_ID, "scope": ""})
    try:
        return DeviceCode(answer["device_code"], answer["user_code"], VERIFY_URL,
                          int(answer.get("interval", 5)), int(answer.get("expires_in", 900)))
    except (KeyError, TypeError, ValueError) as e:
        raise LoginError(answer.get("error_description") or "GitHub didn’t give a code to sign in with.") from e


def wait(code: DeviceCode, cancelled: threading.Event, post=_post, pause=None) -> str:
    """Wait until you've entered the code and approved it on GitHub. Returns the login (its token). Asks no more
    often than GitHub says to; stops when `cancelled` is set (raising LoginError) or the code expires. `pause(seconds)`
    waits between asks (tests skip it)."""
    pause = pause or cancelled.wait
    interval, deadline = code.interval, time.monotonic() + code.expires_in
    while True:
        pause(interval)
        if cancelled.is_set():
            raise LoginError("Signing in was cancelled.")
        answer = post(TOKEN_URL, {"client_id": CLIENT_ID, "device_code": code.device_code,
                                  "grant_type": "urn:ietf:params:oauth:grant-type:device_code"})
        if token := answer.get("access_token"):
            return token
        error = answer.get("error")
        if error == "slow_down":
            try:
                interval = int(answer.get("interval", interval + 5))
            except (TypeError, ValueError):
                interval += 5
        elif error == "expired_token" or time.monotonic() > deadline:
            raise LoginError("The code expired before it was entered. Sign in again for a new one.")
        elif error == "access_denied":
            raise LoginError("Signing in was declined on GitHub.")
        elif error != "authorization_pending":
            raise LoginError(answer.get("error_description") or f"GitHub said: {error}")


# ---------------------------------------------------------------------------------------------------------------------
# Keeping the login: the desktop's password store, through secret-tool (libsecret)


def _secret_tool(*args: str, text: str | None = None) -> subprocess.CompletedProcess:
    tool = shutil.which("secret-tool")
    if not tool:
        raise LoginError("The login can’t be kept safely: secret-tool (from libsecret) isn’t installed.")
    try:
        return subprocess.run([tool, *args, *SECRET], input=text, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise LoginError(f"Couldn’t reach the password store: {e}") from e


def keep(token: str) -> None:
    """Put the login in the password store (the token goes in on stdin, not on a command line)."""
    if _secret_tool("store", "--label=couriercollie: GitHub sign-in", text=token).returncode != 0:
        raise LoginError("The password store didn’t take the login. It may be locked or closed; open it and "
                         "try again.")


def kept() -> str:
    """The kept login, or "" if there isn't one or the password store can't be reached."""
    try:
        result = _secret_tool("lookup")
    except LoginError:
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def forget() -> None:
    try:
        _secret_tool("clear")
    except LoginError:
        pass
