"""Signing in to GitHub, for the Settings page (DESIGN.md §8). Part of the Backend (backend.py), like updating.py;
the signing in itself is in github_login.py.
"""

import json
import shutil
import threading
import urllib.error
import urllib.request
from pathlib import Path

from PySide6.QtCore import Slot
from PySide6.QtDBus import QDBusConnection, QDBusMessage
from PySide6.QtGui import QGuiApplication

from . import github_login, sources

# Password stores (programs providing the desktop's Secret Service), by process name, as they're called to users.
_STORES = {"ksecretd": "KDE Wallet", "kwalletd6": "KDE Wallet", "kwalletd5": "KDE Wallet",
           "gnome-keyring-d": "GNOME Keyring", "keepassxc": "KeePassXC"}
_SECRET_SERVICE = "org.freedesktop.secrets"


def password_store() -> str:
    """The desktop's password store, by the name its users know (KDE Wallet on Plasma, GNOME Keyring on GNOME, …), or
    "your desktop's password store" for another. "" if there's none (e.g. a window manager without one), or no
    secret-tool to reach it: then a login made here can't be kept safely."""
    if not shutil.which("secret-tool"):
        return ""
    bus = QDBusConnection.sessionBus()
    if not bus.isConnected():
        return ""

    def ask(method: str, *args):
        message = QDBusMessage.createMethodCall("org.freedesktop.DBus", "/org/freedesktop/DBus",
                                                "org.freedesktop.DBus", method)
        message.setArguments(list(args))
        reply = bus.call(message)
        return reply.arguments()[0] if reply.type() == QDBusMessage.MessageType.ReplyMessage else None

    pid = ask("GetConnectionUnixProcessID", _SECRET_SERVICE)
    if pid is None:
        # Not running, but started when first asked (as GNOME Keyring can be)?
        return "your desktop\u2019s password store" if _SECRET_SERVICE in (ask("ListActivatableNames") or []) else ""
    try:
        name = Path(f"/proc/{pid}/comm").read_text().strip()
    except OSError:
        name = ""
    return _STORES.get(name, "your desktop\u2019s password store")


def use_login(way: str) -> None:
    """Send GitHub requests with the login kept when signing in (or none). Read lazily, when the first is made."""
    sources.use_github_login(github_login.kept if way == github_login.WITH_CODE else None)


def user_name(token: str) -> str:
    """The GitHub account a login belongs to (one request, counted against that login's 5,000)."""
    if not sources._TOKEN_FORM.fullmatch(token):
        raise github_login.LoginError("That doesn\u2019t look like a GitHub login, so it wasn\u2019t used.")
    req = urllib.request.Request(f"https://{sources.GITHUB_API}/user",
                                 headers={"User-Agent": sources.USER_AGENT, "Accept": "application/vnd.github+json"})
    req.add_unredirected_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=sources.TIMEOUT) as resp:
            return str(json.load(resp).get("login") or "")
    except urllib.error.HTTPError as e:
        raise github_login.LoginError("GitHub didn’t accept the login." if e.code == 401 else
                                      f"GitHub answered with an error ({e.code}).") from e
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise github_login.LoginError("Couldn’t reach github.com. Check your internet connection.") from e


class Account:
    """The Backend's GitHub sign-in slots (a mixin, like updating.Updating)."""

    def _init_account(self):
        self._signin_state = ""  # "", "starting" (asking for a code) or "waiting" (for you to enter it)
        self._signin_code: github_login.DeviceCode | None = None
        self._signin_error = ""
        self._signin_cancel = threading.Event()
        self._store = ""  # the desktop's password store, by name ("" if none); looked up when Settings opens
        s = self._config.settings
        if s.github_login != github_login.WITH_CODE:
            s.github_login = s.github_user = ""  # signed out (or a way of signing in that no longer exists)
        use_login(s.github_login)

    def _github_dict(self) -> dict:
        s = self._config.settings
        code = self._signin_code
        return {
            "way": s.github_login,
            "user": s.github_user,
            "signIn": self._signin_state,
            "code": code.user_code if code and self._signin_state == "waiting" else "",
            "verifyUrl": code.verification_uri if code else "",
            "error": self._signin_error,
            "rejected": bool(s.github_login) and sources.login_rejected,
            "store": self._store,
        }

    def _signed_in(self, way: str, user: str, token: str):
        s = self._config.settings
        s.github_login, s.github_user = way, user
        self._save()
        # The new login straight away (no need to read it back from where it's kept).
        sources.use_github_login(lambda: token)
        self._signin_state, self._signin_code, self._signin_error = "", None, ""
        self.githubChanged.emit()
        self.refreshGitHub()

    @Slot()
    def startSignIn(self):
        """Sign In: ask GitHub for a code, show it, and wait for it to be entered at github.com/login/device."""
        if self._signin_state:
            return
        self._signin_state, self._signin_error = "starting", ""
        self._signin_cancel = cancel = threading.Event()
        self.githubChanged.emit()

        def got_code(code, error):
            if cancel.is_set():
                return
            if error:
                self._signin_state, self._signin_error = "", self._error_text(error)
                self.githubChanged.emit()
                return
            self._signin_state, self._signin_code = "waiting", code
            self.githubChanged.emit()

            def approved():
                token = github_login.wait(code, cancel)
                user = user_name(token)
                github_login.keep(token)
                return token, user

            def done(result, error):
                if cancel.is_set():
                    return
                if error:
                    self._signin_state, self._signin_code, self._signin_error = "", None, self._error_text(error)
                    self.githubChanged.emit()
                    return
                token, user = result
                self._signed_in(github_login.WITH_CODE, user, token)

            self._run(approved, done)

        self._run(github_login.start, got_code)

    @Slot()
    def cancelSignIn(self):
        self._signin_cancel.set()
        self._signin_state, self._signin_code, self._signin_error = "", None, ""
        self.githubChanged.emit()

    @Slot()
    def signOut(self):
        """Stop using the login, and remove it from the password store."""
        github_login.forget()
        s = self._config.settings
        s.github_login, s.github_user = "", ""
        self._save()
        use_login("")
        self.githubChanged.emit()
        self.refreshGitHub()

    @Slot()
    def refreshGitHub(self):
        """When Settings or the welcome screen opens: which password store the desktop has (none: no signing in)."""
        self._store = password_store()
        self.githubChanged.emit()

    @Slot(str)
    def copyText(self, text):
        QGuiApplication.clipboard().setText(text)
