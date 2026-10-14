import os
import socket
import subprocess
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from couriercollie import app, checker, config, integration, sources
from couriercollie.backend import Backend
from couriercollie.config import TrackedRepo


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
        os.environ.pop("COURIERCOLLIE_CONFIG", None)
        os.environ.pop("COURIERCOLLIE_STATE", None)
        # Never to the real desktop: the signal that makes it look icons up again is noted instead.
        self.icons_changed = []
        saved = integration._icons_changed
        integration._icons_changed = lambda: self.icons_changed.append(1)
        self.addCleanup(setattr, integration, "_icons_changed", saved)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.saved_env)
        self.dir.cleanup()


class MenuEntryTest(TempHome):
    def test_the_desktop_is_told_when_the_icon_changes(self):
        # The old drawing there (found first), then the logo: the desktop is told, once; after, nothing to tell.
        old = integration._old_icon_path()
        old.parent.mkdir(parents=True)
        old.write_text("<svg/>")
        integration.install_menu_entry()
        self.assertEqual((old.exists(), integration.icon_path().is_file(), self.icons_changed), (False, True, [1]))
        integration.install_menu_entry()
        self.assertEqual(self.icons_changed, [1])

    def test_written_once_and_kept_current(self):
        self.assertTrue(integration.install_menu_entry())
        path = integration.menu_entry_path()
        self.assertEqual(path, self.root / "data/applications/couriercollie.desktop")
        text = path.read_text()
        self.assertIn(f"Exec={integration.LAUNCHER}\n", text)
        self.assertIn("Icon=couriercollie\n", text)
        # Its icon too, as installed copies have it in the system's icon folder.
        self.assertEqual(integration.icon_path().read_bytes(), integration.ICON_FILE.read_bytes())
        self.assertFalse(integration.install_menu_entry())  # already right
        path.write_text(text.replace(str(integration.LAUNCHER), "/old/place/run.sh"))  # the project moved
        self.assertTrue(integration.install_menu_entry())

    def test_installed_copy_leaves_it_to_the_system(self):
        integration.install_menu_entry()  # from the project folder
        saved = integration.INSTALLED
        integration.INSTALLED = True
        self.addCleanup(setattr, integration, "INSTALLED", saved)
        self.assertFalse(integration.install_menu_entry())
        self.assertFalse(integration.menu_entry_path().exists())  # it would hide the system's entry
        other = integration.menu_entry_path()
        other.write_text("[Desktop Entry]\nName=Something you made\nExec=/opt/x/run.sh\n")
        integration.install_menu_entry()
        self.assertTrue(other.exists())  # not one the app wrote: left alone

    def test_the_rpms_entry_matches(self):
        self.assertEqual((integration.PROJECT / "data/couriercollie.desktop").read_text(),
                         integration.menu_entry_text("couriercollie"))


class TimerTest(TempHome):
    def test_on_and_off(self):
        calls = []
        ok = lambda *args: calls.append(args) or True  # noqa: E731
        self.assertTrue(integration.set_background_checks(True, systemctl=ok))
        folder = self.root / "config/systemd/user"
        timer = (folder / "couriercollie-check.timer").read_text()
        service = (folder / "couriercollie-check.service").read_text()
        self.assertIn("Persistent=true", timer)
        self.assertIn("OnCalendar=hourly", timer)
        self.assertIn(f'ExecStart="{integration.LAUNCHER}" --check --if-due', service)
        self.assertIn("KillMode=process", service)  # the notification's click helper outlives the check
        self.assertIn(("enable", "--now", "couriercollie-check.timer"), calls)
        calls.clear()
        stamp = self.root / "data/systemd/timers/stamp-couriercollie-check.timer"
        stamp.parent.mkdir(parents=True)
        stamp.touch()
        integration.set_background_checks(False, systemctl=ok)
        self.assertFalse((folder / "couriercollie-check.timer").exists())
        self.assertFalse(stamp.exists())
        self.assertIn(("disable", "--now", "couriercollie-check.timer"), calls)


class StartAtLoginTest(TempHome):
    def test_on_and_off(self):
        self.assertTrue(integration.set_start_at_login(True))
        entry = integration.autostart_path()
        self.assertEqual(entry, self.root / "config/autostart/couriercollie.desktop")
        text = entry.read_text()
        self.assertIn(f"Exec={integration.LAUNCHER} --at-login\n", text)
        # If couriercollie is uninstalled, the desktop skips the entry rather than failing at every login.
        self.assertIn(f"TryExec={integration.LAUNCHER}\n", text)
        self.assertTrue(integration.set_start_at_login(False))
        self.assertFalse(entry.exists())

    def test_a_folder_name_with_a_space(self):
        self.assertEqual(integration._exec_arg("/usr/bin/couriercollie"), "/usr/bin/couriercollie")
        self.assertEqual(integration._exec_arg("/home/u/my apps/run.sh"), '"/home/u/my apps/run.sh"')
        # Inside quotes " ` $ \ get a backslash, % doubles, and the line doubles every backslash once more.
        self.assertEqual(integration._exec_arg('/a"b$c%d/run.sh'), '"/a\\\\"b\\\\$c%%d/run.sh"')


class CleanupAfterUninstallTest(TempHome):
    """Before each check, the timer looks for couriercollie. Gone (the package removed, or its project folder
    deleted): the timer turns itself off and removes its files and a project folder's menu entry. Runs the unit's own
    command, with a stand-in systemctl. (devtools/check_uninstall.sh does it for real, with systemd.)"""

    def run_condition(self, launcher: Path) -> int:
        import shlex

        saved = integration.LAUNCHER, integration.INSTALLED
        integration.LAUNCHER, integration.INSTALLED = launcher, False
        self.addCleanup(lambda: (setattr(integration, "LAUNCHER", saved[0]),
                                 setattr(integration, "INSTALLED", saved[1])))
        self.assertTrue(integration.set_background_checks(True, systemctl=lambda *a: True))
        integration.install_menu_entry()
        stamp = self.root / "data/systemd/timers/stamp-couriercollie-check.timer"  # systemd's, after a first run
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.touch()
        integration.set_start_at_login(True)
        service = (self.root / "config/systemd/user/couriercollie-check.service").read_text()
        line = next(l for l in service.splitlines() if l.startswith("ExecCondition="))
        # systemd's quoting, as far as this line uses it: "$$" is "$", "%%" is "%".
        args = shlex.split(line.removeprefix("ExecCondition=").replace("$$", "$").replace("%%", "%"))
        bin_dir = self.root / "bin"
        bin_dir.mkdir(exist_ok=True)
        (bin_dir / "systemctl").write_text(f'#!/bin/sh\necho "$@" >> "{self.root}/systemctl.log"\n')
        (bin_dir / "systemctl").chmod(0o755)
        env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}
        return subprocess.run(args, env=env, capture_output=True).returncode

    def leftovers(self):
        return sorted(str(p.relative_to(self.root)) for p in self.root.rglob("*couriercollie*"))

    def test_still_there_the_check_runs(self):
        folder = self.root / "my project $HOME 100%"  # a folder name systemd and the shell would both misread
        folder.mkdir()
        (folder / "run.sh").write_text("#!/bin/sh\n")
        self.assertEqual(self.run_condition(folder / "run.sh"), 0)
        self.assertIn("config/systemd/user/couriercollie-check.timer", self.leftovers())
        self.assertFalse((self.root / "systemctl.log").exists())

    def test_gone_the_timer_removes_itself(self):
        folder = self.root / "my project $HOME 100%"
        self.assertEqual(self.run_condition(folder / "run.sh"), 1)  # skipped quietly, not failed
        self.assertEqual([l for l in self.leftovers()
                          if "systemd" in l or "applications" in l or "icons" in l or "autostart" in l], [])
        log = (self.root / "systemctl.log").read_text()
        self.assertIn("--user disable --now couriercollie-check.timer", log)
        self.assertIn("--user daemon-reload", log)


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


class ResetCommandTest(TempHome):
    def test_not_while_the_app_is_open(self):
        # The open window would save its settings again, undoing the reset.
        import sys

        from couriercollie import app, config

        path = config.default_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("categories = []\n")
        listener = Listener(integration.socket_path())
        saved = sys.argv
        sys.argv = ["couriercollie", "--reset"]
        self.addCleanup(setattr, sys, "argv", saved)
        self.assertEqual(app.main(), 1)
        listener.close()
        self.assertTrue(path.exists())
        self.assertEqual(listener.received, ["ping"])


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
        sources.releases = lambda ref, host, **_: self.asked.append(ref.id) or [sources.Release("v2", "v2", None, False,
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
        sources.releases = lambda ref, host, **_: [sources.Release("v2", "v2", None, False, "", "")]

    def tearDown(self):
        self.backend.shutdown()
        self.dir.cleanup()

    def test_check_now(self):
        self.backend.checkNow()
        self.assertEqual(self.backend.checks["updates"], 1)
        self.assertTrue(self.backend.checks["lastChecked"])
        app_row = self.backend.repo("github.com/a/app")
        self.assertEqual((app_row["checkText"], app_row["updateAvailable"]), ("Update available: v2", True))
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


class AnnounceTest(TempHome):
    def test_shown_on_its_own_so_quitting_cant_cut_it_short(self):
        # The window isn't in front: the notification is shown as the background checker shows it (started on its
        # own; a click opens couriercollie, which brings an open window forward).
        from PySide6.QtCore import QCoreApplication

        QCoreApplication.instance() or QCoreApplication([])
        shown = []
        saved = integration.notify_and_open_on_click
        integration.notify_and_open_on_click = lambda title, body: shown.append((title, body)) or True
        self.addCleanup(setattr, integration, "notify_and_open_on_click", saved)
        b = Backend(self.root / "repos.toml")
        self.addCleanup(b.shutdown)
        b._config.repos.append(TrackedRepo(id="github.com/a/b", name="B", url="", host="github"))
        b._config.settings.toasts, b._desktop = True, True
        b._announce(["github.com/a/b"])
        self.assertEqual(shown, [("1 update available", "B")])
