import os
import socket
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from repoproject import app, checker, config, integration, sources
from repoproject.backend import Backend
from repoproject.config import TrackedRepo


class TempHome(unittest.TestCase):
    """Points the XDG folders (and the app's socket) at a temporary folder."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        self.saved_env = dict(os.environ)
        os.environ.update(XDG_DATA_HOME=str(self.root / "data"), XDG_CONFIG_HOME=str(self.root / "config"),
                          XDG_STATE_HOME=str(self.root / "state"), XDG_RUNTIME_DIR=str(self.root / "run"),
                          XDG_CACHE_HOME=str(self.root / "cache"))
        (self.root / "run").mkdir()
        os.environ.pop("REPOPROJECT_CONFIG", None)
        os.environ.pop("REPOPROJECT_STATE", None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.saved_env)
        self.dir.cleanup()


class MenuEntryTest(TempHome):
    def test_written_once_and_kept_current(self):
        self.assertTrue(integration.install_menu_entry())
        path = integration.menu_entry_path()
        self.assertEqual(path, self.root / "data/applications/repoproject.desktop")
        text = path.read_text()
        self.assertIn(f"Exec={integration.LAUNCHER}\n", text)
        self.assertIn("Icon=system-software-update\n", text)
        self.assertFalse(integration.install_menu_entry())  # already right
        path.write_text(text.replace(str(integration.LAUNCHER), "/old/place/run.sh"))  # the project moved
        self.assertTrue(integration.install_menu_entry())


class TimerTest(TempHome):
    def test_on_and_off(self):
        calls = []
        ok = lambda *args: calls.append(args) or True  # noqa: E731
        self.assertTrue(integration.set_background_checks(True, systemctl=ok))
        folder = self.root / "config/systemd/user"
        timer = (folder / "repoproject-check.timer").read_text()
        service = (folder / "repoproject-check.service").read_text()
        self.assertIn("Persistent=true", timer)
        self.assertIn("OnCalendar=hourly", timer)
        self.assertIn(f"ExecStart={integration.LAUNCHER} --check --if-due", service)
        self.assertIn("KillMode=process", service)  # the notification's click helper outlives the check
        self.assertIn(("enable", "--now", "repoproject-check.timer"), calls)
        calls.clear()
        integration.set_background_checks(False, systemctl=ok)
        self.assertFalse((folder / "repoproject-check.timer").exists())
        self.assertIn(("disable", "--now", "repoproject-check.timer"), calls)


class MessageTest(unittest.TestCase):
    def test_updates_message(self):
        self.assertEqual(integration.updates_message(["SMOD"]), ("1 update available", "SMOD"))
        self.assertEqual(integration.updates_message(["A", "B"]), ("2 updates available", "A and B"))
        self.assertEqual(integration.updates_message(["A", "B", "C"])[1], "A, B, and C")
        self.assertEqual(integration.updates_message(list("ABCDEF"))[1], "A, B, C, and 3 more")

    def test_notify_command_has_an_open_action(self):
        command = integration.notify_command("1 update available", "SMOD")
        if command is None:
            self.skipTest("notify-send isn't installed")
        self.assertIn("--action=default=Open", command)
        self.assertEqual(command[-2:], ["1 update available", "SMOD"])


class Listener:
    """Stands in for the running app: accepts one connection and records what it was told."""

    def __init__(self, path: Path):
        self.received = []
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(str(path))
        self.server.listen(1)
        self.thread = threading.Thread(target=self._accept, daemon=True)
        self.thread.start()

    def _accept(self):
        conn, _ = self.server.accept()
        with conn:
            self.received.append(conn.recv(100).decode().strip())

    def close(self):
        self.thread.join(2)
        self.server.close()


class RunningAppTest(TempHome):
    def test_nobody_listening(self):
        self.assertFalse(integration.tell_running_app("show"))

    def test_running_app_is_told(self):
        listener = Listener(integration.socket_path())
        self.assertTrue(integration.tell_running_app("check"))
        listener.close()
        self.assertEqual(listener.received, ["check"])


class CheckCommandTest(TempHome):
    """`run.sh --check [--if-due]`, what the background timer runs."""

    def setUp(self):
        super().setUp()
        cfg = config.Config(settings=config.Settings(auto_check=True, check_interval_hours=24, toasts=False), repos=[
            TrackedRepo(id="github.com/a/app", name="App", url="", host="github", installed="v1")])
        config.save(cfg)
        self.asked = []
        saved = sources.releases
        self.addCleanup(setattr, sources, "releases", saved)
        sources.releases = lambda ref, host: self.asked.append(ref.id) or [sources.Release("v2", "v2", None, False,
                                                                                            "", "")]

    def test_checks_and_saves_when_the_app_isnt_open(self):
        self.assertEqual(app.check(if_due=True), 0)
        self.assertEqual(self.asked, ["github.com/a/app"])
        self.assertEqual(checker.load_state().results["github.com/a/app"].status, checker.UPDATE)

    def test_not_due_yet(self):
        recent = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        checker.save_state(checker.State(last_run=recent))
        self.assertEqual(app.check(if_due=True), 0)
        self.assertEqual(self.asked, [])
        app.check(if_due=False)  # asked directly: checks anyway
        self.assertEqual(self.asked, ["github.com/a/app"])

    def test_handed_to_the_open_app(self):
        listener = Listener(integration.socket_path())
        self.assertEqual(app.check(if_due=True), 0)
        listener.close()
        self.assertEqual(listener.received, ["check"])
        self.assertEqual(self.asked, [])  # the app does the checking


class CheckNowTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "repos.toml"
        config.save(config.Config(repos=[
            TrackedRepo(id="github.com/a/app", name="App", url="", host="github", installed="v1"),
            TrackedRepo(id="github.com/a/other", name="Other", url="", host="github", installed="v2"),
        ]), self.path)
        self.backend = Backend(self.path)
        self.backend._run = lambda work, done: done(work(), None)
        saved = sources.releases
        self.addCleanup(setattr, sources, "releases", saved)
        sources.releases = lambda ref, host: [sources.Release("v2", "v2", None, False, "", "")]

    def tearDown(self):
        self.backend.shutdown()
        self.dir.cleanup()

    def test_check_now(self):
        self.backend.checkNow()
        self.assertEqual(self.backend.checks["updates"], 1)
        self.assertTrue(self.backend.checks["lastChecked"])
        app_row = self.backend.repo("github.com/a/app")
        self.assertEqual((app_row["checkStatus"], app_row["checkText"], app_row["updateAvailable"]),
                         (checker.UPDATE, "Update available: v2", True))
        self.assertFalse(self.backend.repo("github.com/a/other")["updateAvailable"])
        # Kept for next time, next to the settings file.
        self.assertEqual(Backend(self.path).checks["updates"], 1)

    def test_choosing_the_newest_clears_the_update_at_once(self):
        self.backend.checkNow()
        self.assertTrue(self.backend.repo("github.com/a/app")["updateAvailable"])
        self.backend.setInstalled("github.com/a/app", "v2")  # "Set as My Version" on the newest release
        row = self.backend.repo("github.com/a/app")
        self.assertEqual((row["updateAvailable"], row["checkText"]), (False, "Up to date"))
        self.assertEqual(self.backend.checks["updates"], 0)
        self.assertEqual(Backend(self.path).checks["updates"], 0)  # saved, so the timer's next notification agrees
        self.backend.setInstalled("github.com/a/app", "v1")  # back to an older one
        self.assertEqual(self.backend.repo("github.com/a/app")["checkText"], "Update available: v2")
        self.backend.setInstalled("github.com/a/app", "-")  # "Mark as Not Installed"
        self.assertEqual(self.backend.repo("github.com/a/app")["checkText"], "Not installed \u00b7 newest v2")
        self.assertEqual(self.backend.checks["updates"], 0)

    def test_requests_from_outside(self):
        shown = []
        self.backend.activateRequested.connect(lambda: shown.append(True))
        self.backend.handleRequest("show")
        self.assertEqual(shown, [True])
        self.backend.handleRequest("check")
        self.assertEqual(self.backend.checks["updates"], 1)

    def test_next_check_only_with_automatic_checks(self):
        self.backend.checkNow()
        self.assertEqual(self.backend.checks["nextCheck"], "")
        self.backend.updateSettings({"autoCheck": True})
        self.assertTrue(self.backend.checks["nextCheck"])


if __name__ == "__main__":
    unittest.main()
