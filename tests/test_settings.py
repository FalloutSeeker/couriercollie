import tempfile
import unittest
from pathlib import Path

from repoproject import config
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
                                     "scanning": True, "deleteOld": True, "deleteOldDays": 90})
        s = config.load(self.path).settings
        self.assertEqual((s.first_launch_done, s.auto_check, s.check_interval_hours, s.scanning, s.delete_old,
                          s.delete_old_days), (True, True, 24, True, True, 90))
        # A fresh start reads them back, so the first-launch screen doesn't come back.
        self.assertTrue(Backend(self.path).settings["firstLaunchDone"])

    def test_numbers_from_the_window_may_be_floats(self):
        self.backend.updateSettings({"checkIntervalHours": 168.0, "deleteOldDays": 7.0})
        self.assertEqual(self.backend.settings["checkIntervalHours"], 168)
        self.assertEqual(self.backend.settings["deleteOldDays"], 7)

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
        self.backend.updateSettings({"checkIntervalHours": 5, "deleteOldDays": 1, "autoCheck": "yes", "bogus": 1})
        self.assertEqual(self.backend.settings["checkIntervalHours"], 24)
        self.assertEqual(self.backend.settings["deleteOldDays"], 30)
        self.assertFalse(self.backend.settings["autoCheck"])

    def test_one_change_leaves_the_rest(self):
        self.backend.updateSettings({"toasts": False})
        self.assertFalse(self.backend.settings["toasts"])
        self.assertFalse(self.backend.settings["scanning"])


if __name__ == "__main__":
    unittest.main()
