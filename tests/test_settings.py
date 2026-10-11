import os
import tempfile
import unittest
from pathlib import Path

from repoproject import config, scan
from repoproject.backend import Backend


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
