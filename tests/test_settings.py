import os
import tempfile
import unittest
from pathlib import Path

from couriercollie import config, scan
from couriercollie.backend import Backend


class SettingsTest(unittest.TestCase):
    """The first-launch screen and the Settings page both go through Backend.updateSettings."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "repos.toml"
        self.backend = Backend(self.path)

    def tearDown(self):
        self.backend.shutdown()
        self.dir.cleanup()

    def test_new_install_needs_first_launch(self):
        self.assertFalse(self.backend.settings["firstLaunchDone"])

    def test_first_launch_answers_are_saved(self):
        self.backend.updateSettings({"firstLaunchDone": True, "autoCheck": True, "checkIntervalHours": 24,
                                     "scanning": True})
        s = config.load(self.path).settings
        self.assertEqual((s.first_launch_done, s.auto_check, s.check_interval_hours, s.scanning), (True, True, 24, True))
        # A fresh start reads them back, so the first-launch screen doesn't come back.
        self.assertTrue(Backend(self.path).settings["firstLaunchDone"])

    def test_restore_to_defaults_keeps_repos_categories_and_sign_in(self):
        from couriercollie.config import TrackedRepo

        b = self.backend
        b._config.repos.append(TrackedRepo(id="github.com/a/b", name="B", url="", host="github", category="Tools"))
        b._config.categories.append("Tools")
        b._config.settings.github_login, b._config.settings.github_user = "app", "someone"
        b.updateSettings({"firstLaunchDone": True, "autoCheck": False, "checkIntervalHours": 672, "toasts": False,
                          "scanning": True, "startAtLogin": True, "keepInTray": True})
        b.removeScanFolder("/srv")
        self.assertFalse(b.settings["areDefault"])
        b.restoreDefaults()
        s = config.load(self.path)
        # As the welcome screen leaves them: checks on, daily; no welcome screen again.
        self.assertEqual((s.settings.first_launch_done, s.settings.auto_check, s.settings.check_interval_hours,
                          s.settings.toasts, s.settings.scanning, s.settings.start_at_login, s.settings.keep_in_tray),
                         (True, True, 24, True, False, False, False))
        self.assertEqual(s.settings.scan_folders, config.DEFAULT_SCAN_FOLDERS)
        self.assertEqual((s.settings.github_login, s.settings.github_user), ("app", "someone"))
        self.assertEqual(([r.id for r in s.repos], s.categories), (["github.com/a/b"], ["Tools"]))
        self.assertTrue(b.settings["areDefault"])

    def test_numbers_from_the_window_may_be_floats(self):
        self.backend.updateSettings({"checkIntervalHours": 168.0})
        self.assertEqual(self.backend.settings["checkIntervalHours"], 168)

    def test_interval_choices(self):
        # Daily, every 7 days, every 14 days, monthly (4 weeks). Daily is the default.
        self.assertEqual(self.backend.settings["checkIntervalHours"], 24)
        for hours in (24, 168, 336, 672):
            self.backend.updateSettings({"checkIntervalHours": hours})
            self.assertEqual(self.backend.settings["checkIntervalHours"], hours)

    def test_old_saved_intervals_move_to_the_next_choice_up(self):
        for saved, expected in [(1, 24), (6, 24), (72, 168), (168, 168), (5000, 672), ("junk", 24)]:
            self.path.write_text(f"[settings]\ncheck_interval_hours = {saved!r}\n".replace("'", '"'))
            self.assertEqual(config.load(self.path).settings.check_interval_hours, expected, saved)

    def test_reset_keeps_a_backup(self):
        self.backend.updateSettings({"firstLaunchDone": True})
        backup = config.reset(self.path)
        self.assertFalse(self.path.exists())
        self.assertIn("first_launch_done = true", backup.read_text())
        self.assertFalse(Backend(self.path).settings["firstLaunchDone"])
        self.assertIsNone(config.reset(self.path))

    def test_values_outside_the_choices_are_ignored(self):
        self.backend.updateSettings({"checkIntervalHours": 5, "autoCheck": "yes", "bogus": 1})
        self.backend.updateSettings({"checkIntervalHours": "abc"})
        self.assertEqual(self.backend.settings["checkIntervalHours"], 24)
        self.assertFalse(self.backend.settings["autoCheck"])

    def test_scan_folders_default(self):
        self.assertEqual([f["path"] for f in self.backend.settings["scanFolders"]], ["~", "/opt", "/usr/local", "/srv"])
        self.assertTrue(all(f["isDefault"] for f in self.backend.settings["scanFolders"]))
        self.assertEqual(self.backend.settings["scanFolders"][0]["label"], "Home folder (~)")
        self.assertEqual(self.backend.settings["scanFoldersText"], "the home folder, /opt, /usr/local, and /srv")
        # The same list the scanner uses on its own.
        self.assertEqual(tuple(config.DEFAULT_SCAN_FOLDERS), scan.DEFAULT_SCAN_FOLDERS)

    def test_add_remove_and_restore_scan_folders(self):
        self.backend.addScanFolder("file:///mnt/data")
        self.backend.addScanFolder(str(Path.home() / "Projects"))  # saved relative to the home folder
        self.backend.addScanFolder("/mnt/data")  # already there
        self.backend.removeScanFolder("/srv")
        folders = config.load(self.path).settings.scan_folders
        self.assertEqual(folders, ["~", "/opt", "/usr/local", "/mnt/data", "~/Projects"])
        self.assertFalse(self.backend.settings["scanFoldersAreDefault"])
        self.assertEqual([f["isDefault"] for f in self.backend.settings["scanFolders"]][-2:], [False, False])
        self.backend.resetScanFolders()
        self.assertTrue(self.backend.settings["scanFoldersAreDefault"])

    @unittest.skipIf(os.geteuid() == 0, "root can open any folder")
    def test_folders_a_scan_would_skip_say_why(self):
        root = Path(self.dir.name)
        locked, afile = root / "locked", root / "a-file"
        locked.mkdir(mode=0o000)
        afile.write_text("")
        for folder in (locked, afile, root / "gone", root):
            self.backend.addScanFolder(str(folder))
        problems = {f["path"]: f["problem"] for f in self.backend.settings["scanFolders"]}
        self.assertEqual(problems[str(locked)], "You can\u2019t open this folder, so scans skip it.")
        self.assertEqual(problems[str(afile)], "Not a folder, so scans skip it.")
        self.assertEqual(problems[str(root / "gone")], "Not found, so scans skip it.")
        self.assertEqual(problems[str(root)], "")

    def test_older_settings_files_get_the_default_folders(self):
        self.path.write_text("[settings]\nscanning = true\n")
        self.assertEqual(config.load(self.path).settings.scan_folders, ["~", "/opt", "/usr/local", "/srv"])

    @unittest.skipIf(os.geteuid() == 0, "root can write to read-only folders")
    def test_a_folder_that_cant_be_written_shows_a_warning_and_recovers(self):
        import os
        self.backend.updateSettings({"toasts": False})  # the file exists
        os.chmod(self.path.parent, 0o555)
        try:
            self.backend.updateSettings({"toasts": True})
            self.assertIn("Couldn\u2019t save", self.backend.saveError)
            self.assertTrue(self.backend.settings["toasts"])  # kept while the app is open
        finally:
            os.chmod(self.path.parent, 0o755)
        self.backend.updateSettings({"scanning": True})
        self.assertEqual(self.backend.saveError, "")
        self.assertTrue(config.load(self.path).settings.toasts)  # saved once it could be

    def test_one_change_leaves_the_rest(self):
        self.backend.updateSettings({"toasts": False})
        self.assertFalse(self.backend.settings["toasts"])
        self.assertFalse(self.backend.settings["scanning"])


if __name__ == "__main__":
    unittest.main()


class FeedbackTest(unittest.TestCase):
    """Send Feedback opens a new GitHub issue with what helps filled in; the tracked repos only if asked."""

    def body(self, url):
        from urllib.parse import parse_qs, urlsplit

        self.assertTrue(url.startswith("https://github.com/FalloutSeeker/couriercollie/issues/new?"))
        return parse_qs(urlsplit(url).query)["body"][0]

    def test_versions_distro_and_desktop_without_repos(self):
        from couriercollie import __version__, feedback

        from unittest import mock

        with mock.patch.dict(os.environ, XDG_CURRENT_DESKTOP="KDE"):
            body = self.body(feedback.issue_url(None, "6.10.0"))
        self.assertIn(f"couriercollie {__version__}", body)
        self.assertIn(f"{feedback.distro()}, KDE desktop", body)
        self.assertIn("Qt 6.10.0", body)
        self.assertNotIn("Tracked repos", body)

    def test_repos_only_when_asked(self):
        with tempfile.TemporaryDirectory() as d:
            b = Backend(Path(d) / "repos.toml")
            try:
                from couriercollie.config import TrackedRepo

                b._config.repos.append(TrackedRepo(id="github.com/a/b", name="B", url="https://github.com/a/b",
                                                   host="github"))
                self.assertNotIn("github.com/a/b", self.body(b.feedbackUrl(False)))
                self.assertIn("- https://github.com/a/b", self.body(b.feedbackUrl(True)))
            finally:
                b.shutdown()

    def test_a_long_list_is_cut_to_fit(self):
        from couriercollie import feedback

        repos = [f"https://github.com/someone/project-number-{n}" for n in range(500)]
        url = feedback.issue_url(repos)
        self.assertLessEqual(len(url), feedback._MAX_URL)
        body = self.body(url)
        self.assertIn(repos[0], body)
        listed = body.count("- https://")
        self.assertIn(f"- …and {500 - listed} more", body)

    def test_distro_from_os_release(self):
        from couriercollie import feedback

        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "os-release"
            path.write_text('NAME="Fedora Linux"\nPRETTY_NAME="Fedora Linux 44 (KDE Plasma Desktop Edition)"\n')
            self.assertEqual(feedback.distro(path), "Fedora Linux 44 (KDE Plasma Desktop Edition)")
            self.assertEqual(feedback.distro(Path(d) / "missing"), "Linux")
