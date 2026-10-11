"""Signing in to GitHub, for the Settings page (DESIGN.md §8). Part of the Backend (backend.py), like updating.py;
the signing in itself is in github_login.py.
"""

import json
import threading
import urllib.error
import urllib.request

from PySide6.QtCore import Slot
from PySide6.QtGui import QGuiApplication

from . import github_login, sources

def use_login(way: str) -> None:
    """Send GitHub requests with the login chosen in Settings (or none). Read lazily, when the first is made."""
    sources.use_github_login((lambda: github_login.token_for(way)) if way else None)


def user_name(token: str) -> str:
    """The GitHub account a login belongs to (one request, counted against that login's 5,000)."""
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
        self._gh_user = ""  # the GitHub CLI's account, when it's signed in (looked up when Settings opens)
        self._rate: dict = {}  # GitHub's hourly limit as it stands: limit, remaining, reset (local time)
        use_login(self._config.settings.github_login)

    def _github_dict(self) -> dict:
        s = self._config.settings
        code = self._signin_code
        return {
            "way": s.github_login,
            "user": s.github_user,
            "ghUser": self._gh_user,
            "signIn": self._signin_state,
            "code": code.user_code if code and self._signin_state == "waiting" else "",
            "verifyUrl": code.verification_uri if code else "",
            "error": self._signin_error,
            "rejected": bool(s.github_login) and sources.login_rejected,
            "limit": self._rate.get("limit", 0),
            "remaining": self._rate.get("remaining", -1),
            "resetAt": self._rate.get("reset", ""),
        }

    def _signed_in(self, way: str, user: str, token: str = ""):
        s = self._config.settings
        s.github_login, s.github_user = way, user
        self._save()
        # The new login straight away (no need to read it back from where it's kept).
        sources.use_github_login((lambda: token) if token else (lambda: github_login.token_for(way)))
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
    def useGhLogin(self):
        """Use the GitHub CLI's login: read from gh whenever it's needed, never copied."""
        def work():
            token = github_login.gh_token()
            if not token:
                raise github_login.LoginError("The GitHub CLI isn’t signed in any more (gh auth login).")
            return user_name(token)

        def done(user, error):
            if error:
                self._signin_error = self._error_text(error)
                self.githubChanged.emit()
            else:
                self._signed_in(github_login.WITH_GH, user)

        self._run(work, done)

    @Slot()
    def signOut(self):
        """Stop using the login. One made here is removed from the password store; the GitHub CLI's is left alone."""
        if self._config.settings.github_login == github_login.WITH_CODE:
            github_login.forget()
        s = self._config.settings
        s.github_login, s.github_user = "", ""
        self._save()
        use_login("")
        self.githubChanged.emit()
        self.refreshGitHub()

    @Slot()
    def refreshGitHub(self):
        """When Settings opens: GitHub's limit as it stands (asking costs nothing), and whether the GitHub CLI is
        signed in, to offer its login."""
        signed_in = bool(self._config.settings.github_login)

        def work():
            rate = sources.github_rate()
            gh_user = ""
            if not signed_in and (token := github_login.gh_token()):
                try:
                    gh_user = user_name(token)
                except github_login.LoginError:
                    pass
            return rate, gh_user

        def done(result, error):
            if not error:
                self._rate, self._gh_user = result
            self.githubChanged.emit()

        self._run(work, done)

    @Slot(str)
    def copyText(self, text):
        QGuiApplication.clipboard().setText(text)
