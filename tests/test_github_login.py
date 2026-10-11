import io
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from email.message import Message
from pathlib import Path

from couriercollie import github_login, sources

# Logins as GitHub makes them (the length matters: anything else isn't sent).
APPROVED = "gho_x_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
SECRET = "gho_secret_aaaaaaaaaaaaaaaaaaaaaaaaaa"
TOKEN = "gho_token_aaaaaaaaaaaaaaaaaaaaaaaaaaa"
NEW = "gho_new_aaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


class DeviceFlowTest(unittest.TestCase):
    """Signing in with a code entered at github.com/login/device. GitHub's answers are stand-ins."""

    def setUp(self):
        self.code = github_login.DeviceCode("dev123", "WDJB-MJHT", "https://github.com/login/device", 5, 900)
        self.asked = []

    def post(self, answers):
        answers = list(answers)

        def post(url, fields):
            self.asked.append((url, fields))
            return answers.pop(0)
        return post

    def test_asks_for_no_access(self):
        code = github_login.start(self.post([{"device_code": "d", "user_code": "ABCD-1234",
                                              "verification_uri": "https://github.com/login/device", "interval": 5,
                                              "expires_in": 900}]))
        self.assertEqual(code.user_code, "ABCD-1234")
        url, fields = self.asked[0]
        self.assertEqual((url, fields), (github_login.DEVICE_CODE_URL, {"client_id": github_login.CLIENT_ID,
                                                                         "scope": ""}))

    def test_the_button_only_ever_opens_github(self):
        code = github_login.start(self.post([{"device_code": "d", "user_code": "ABCD-1234",
                                              "verification_uri": "https://example.com/phish"}]))
        self.assertEqual(code.verification_uri, "https://github.com/login/device")

    def test_waits_until_approved_slowing_down_when_told(self):
        pauses = []
        token = github_login.wait(self.code, threading.Event(), self.post([
            {"error": "authorization_pending"}, {"error": "slow_down", "interval": 10}, {"access_token": APPROVED}]),
            pause=pauses.append)
        self.assertEqual(token, APPROVED)
        self.assertEqual(pauses, [5, 5, 10])
        self.assertNotIn("client_secret", self.asked[-1][1])  # none is needed, and none is kept

    def test_declined_expired_or_cancelled(self):
        with self.assertRaisesRegex(github_login.LoginError, "declined"):
            github_login.wait(self.code, threading.Event(), self.post([{"error": "access_denied"}]), pause=bool)
        with self.assertRaisesRegex(github_login.LoginError, "expired"):
            github_login.wait(self.code, threading.Event(), self.post([{"error": "expired_token"}]), pause=bool)
        cancelled = threading.Event()
        cancelled.set()
        with self.assertRaisesRegex(github_login.LoginError, "cancelled"):
            github_login.wait(self.code, cancelled, self.post([]), pause=bool)

    def test_odd_answers(self):
        import io
        import urllib.request

        # Not an object (a proxy's page, say): said plainly.
        saved = urllib.request.urlopen
        urllib.request.urlopen = lambda req, timeout=None: io.BytesIO(b"[1, 2]")
        self.addCleanup(setattr, urllib.request, "urlopen", saved)
        with self.assertRaisesRegex(github_login.LoginError, "couldn’t be read"):
            github_login.start()
        # "Slow down" without a usable interval: waits 5 seconds longer.
        waits = []
        github_login.wait(self.code, threading.Event(),
                          self.post([{"error": "slow_down", "interval": "soon"}, {"access_token": "t"}]),
                          pause=waits.append)
        self.assertEqual(waits, [5, 10])


class KeepingTest(unittest.TestCase):
    """The password store, through a stand-in secret-tool (yours isn't touched)."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        bin_dir, self.store = Path(self.dir.name), Path(self.dir.name) / "store"
        tool = bin_dir / "secret-tool"
        # Keeps one secret in a file; logs its arguments, so we can see the token never goes on a command line.
        tool.write_text(f"""#!/bin/sh
echo "$@" >> {bin_dir}/args
case "$1" in
  store) cat > {self.store} ;;
  lookup) [ -f {self.store} ] && cat {self.store} || exit 1 ;;
  clear) rm -f {self.store} ;;
esac
""")
        tool.chmod(0o755)
        saved = os.environ["PATH"]
        os.environ["PATH"] = f"{bin_dir}:{saved}"
        self.addCleanup(os.environ.__setitem__, "PATH", saved)
        self.args = bin_dir / "args"

    def test_keep_find_and_forget(self):
        self.assertEqual(github_login.kept(), "")
        github_login.keep(SECRET)
        self.assertEqual(github_login.kept(), SECRET)
        self.assertNotIn(SECRET, self.args.read_text())  # on stdin, not on a command line
        self.assertIn("service couriercollie account github", self.args.read_text())
        github_login.forget()
        self.assertEqual(github_login.kept(), "")


class SentOnlyToGitHubTest(unittest.TestCase):
    """The login goes with requests to api.github.com, never to other sites, and never along a redirect."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        saved_cache = os.environ.get("XDG_CACHE_HOME")
        os.environ["XDG_CACHE_HOME"] = self.dir.name
        self.addCleanup(lambda: os.environ.__setitem__("XDG_CACHE_HOME", saved_cache) if saved_cache
                        else os.environ.pop("XDG_CACHE_HOME", None))
        sources.use_github_login(lambda: TOKEN)
        self.addCleanup(sources.use_github_login, None)
        self.sent = []
        self.answers = []
        saved = urllib.request.urlopen
        urllib.request.urlopen = self.urlopen
        self.addCleanup(setattr, urllib.request, "urlopen", saved)

    def urlopen(self, req, timeout=None):
        self.sent.append(req)
        code, body, headers = self.answers.pop(0)
        msg = Message()
        for k, v in headers.items():
            msg[k] = v
        if code != 200:
            raise urllib.error.HTTPError(req.full_url, code, "x", msg, io.BytesIO(body))
        resp = io.BytesIO(body)
        resp.headers = msg
        return resp

    def test_only_to_githubs_api_and_not_redirected(self):
        self.answers = [(200, b"{}", {}), (200, b"{}", {})]
        sources.http_get_json("https://api.github.com/repos/a/b")
        sources.http_get_json("https://gitlab.com/api/v4/projects/a%2Fb")
        github, gitlab = self.sent
        self.assertEqual(github.unredirected_hdrs.get("Authorization"), f"Bearer {TOKEN}")
        self.assertNotIn("Authorization", github.headers)  # headers that would follow a redirect
        self.assertIsNone(gitlab.get_header("Authorization"))

    def test_not_over_plain_http_and_not_a_malformed_login(self):
        self.answers = [(200, b"{}", {}), (200, b"{}", {})]
        sources.http_get_json("http://api.github.com/repos/a/b")
        self.assertIsNone(self.sent[0].get_header("Authorization"))
        sources.use_github_login(lambda: TOKEN + "\nX-Injected: 1")  # e.g. a damaged password store entry
        sources.http_get_json("https://api.github.com/repos/a/b")
        self.assertIsNone(self.sent[1].get_header("Authorization"))
        self.assertTrue(sources.login_rejected)  # and Settings says so

    def test_errors_never_quote_the_login(self):
        self.answers = [(500, b"{}", {}), (403, b"{}", {"x-ratelimit-remaining": "0"})]
        for _ in range(2):
            with self.assertRaises(sources.SourceError) as caught:
                sources.http_get_json("https://api.github.com/repos/a/b")
            self.assertNotIn(TOKEN, str(caught.exception))

    def test_turned_down_twice_is_asked_again_only_once(self):
        self.answers = [(401, b"{}", {}), (401, b"{}", {})]
        with self.assertRaisesRegex(sources.BadAnswer, r"\(401\)"):
            sources.http_get_json("https://api.github.com/repos/a/b")
        self.assertEqual(len(self.sent), 2)

    def test_unchanged_release_lists_come_from_the_cache(self):
        url = "https://api.github.com/repos/a/b/releases?per_page=5"
        self.answers = [(200, json.dumps([{"tag_name": "v1"}]).encode(), {"ETag": '"abc"'}), (304, b"", {})]
        first = sources.http_get_json(url)
        second = sources.http_get_json(url)
        self.assertEqual(first, second)
        self.assertEqual(self.sent[1].unredirected_hdrs.get("If-none-match"), '"abc"')

    def test_a_turned_down_login_is_dropped_and_said(self):
        self.answers = [(401, b"{}", {}), (200, b'{"ok": true}', {}), (200, b"{}", {})]
        self.assertEqual(sources.http_get_json("https://api.github.com/repos/a/b"), {"ok": True})
        self.assertTrue(sources.login_rejected)
        self.assertIsNone(self.sent[1].get_header("Authorization"))  # asked again without it
        sources.http_get_json("https://api.github.com/repos/a/c")
        self.assertIsNone(self.sent[2].get_header("Authorization"))  # and not tried again this run


class SettingsSignInTest(unittest.TestCase):
    """Settings' sign-in, with GitHub, gh and the password store as stand-ins."""

    def setUp(self):
        from couriercollie import account, config
        from couriercollie.backend import Backend

        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = Path(self.dir.name) / "repos.toml"
        self.config = config
        self.kept, self.forgotten = [], []
        fakes = {
            (github_login, "start"): lambda: github_login.DeviceCode("d", "ABCD-1234", "https://github.com/login/device",
                                                                      5, 900),
            (github_login, "wait"): lambda code, cancelled: NEW,
            (github_login, "keep"): self.kept.append,
            (github_login, "forget"): lambda: self.forgotten.append(True),
            (account, "user_name"): lambda token: {NEW: "octocat"}[token],
            (account, "password_store"): lambda: "KDE Wallet",
        }
        for (module, name), fake in fakes.items():
            self.addCleanup(setattr, module, name, getattr(module, name))
            setattr(module, name, fake)
        self.backend = Backend(self.path)
        self.addCleanup(self.backend.shutdown)
        self.addCleanup(sources.use_github_login, None)
        self.backend._run = lambda work, done: self._finish(work, done)

    @staticmethod
    def _finish(work, done):
        try:
            result, error = work(), None
        except Exception as e:  # noqa: BLE001
            result, error = None, e
        done(result, error)

    def test_sign_in_with_a_code_then_out(self):
        self.backend.startSignIn()
        gh = self.backend.github
        self.assertEqual((gh["way"], gh["user"]), ("app", "octocat"))
        self.assertEqual(self.kept, [NEW])  # kept in the password store
        saved = self.config.load(self.path).settings
        self.assertEqual((saved.github_login, saved.github_user), ("app", "octocat"))
        self.assertNotIn(NEW, self.path.read_text())  # never in the settings file
        self.assertEqual(sources._github_token(), NEW)  # used straight away
        self.backend.signOut()
        self.assertEqual((self.backend.github["way"], self.forgotten), ("", [True]))
        self.assertEqual(sources._github_token(), "")

    def test_a_saved_github_cli_login_counts_as_signed_out(self):
        from couriercollie import config
        from couriercollie.backend import Backend

        config.save(config.Config(settings=config.Settings(github_login="gh", github_user="someone")), self.path)
        backend = Backend(self.path)
        self.addCleanup(backend.shutdown)
        self.assertEqual((backend.github["way"], backend.github["user"]), ("", ""))
        self.assertEqual(sources._github_token(), "")  # and gh is never asked

    def test_cancelled_while_waiting(self):
        self.backend._run = lambda work, done: None if work is not github_login.start else done(work(), None)
        self.backend.startSignIn()
        self.assertEqual((self.backend.github["signIn"], self.backend.github["code"]), ("waiting", "ABCD-1234"))
        self.backend.cancelSignIn()
        self.assertEqual((self.backend.github["signIn"], self.backend.github["way"]), ("", ""))


class PasswordStoreTest(unittest.TestCase):
    """Which password store the desktop has, by name: shown to you, and none means a code sign-in can't be kept."""

    def test_none_without_secret_tool(self):
        from couriercollie import account

        saved = os.environ["PATH"]
        os.environ["PATH"] = "/nonexistent"
        self.addCleanup(os.environ.__setitem__, "PATH", saved)
        self.assertEqual(account.password_store(), "")

    def test_named_as_its_users_know_it(self):
        from couriercollie import account

        names = set(account._STORES.values()) | {"your desktop’s password store", ""}
        self.assertIn(account.password_store(), names)  # whatever this desktop has (KDE Wallet here)


class SignInErrorsTest(unittest.TestCase):
    def test_shown_as_written(self):
        from couriercollie.backend import Backend

        self.assertEqual(Backend._error_text(github_login.LoginError("Signing in was declined on GitHub.")),
                         "Signing in was declined on GitHub.")
