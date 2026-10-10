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
        self.backend.updateSettings({"checkIntervalHours": 12.0, "deleteOldDays": 7.0})
        self.assertEqual(self.backend.settings["checkIntervalHours"], 12)
        self.assertEqual(self.backend.settings["deleteOldDays"], 7)

    def test_values_outside_the_choices_are_ignored(self):
        self.backend.updateSettings({"checkIntervalHours": 5, "deleteOldDays": 1, "autoCheck": "yes", "bogus": 1})
        self.assertEqual(self.backend.settings["checkIntervalHours"], 6)
        self.assertEqual(self.backend.settings["deleteOldDays"], 30)
        self.assertFalse(self.backend.settings["autoCheck"])

    def test_one_change_leaves_the_rest(self):
        self.backend.updateSettings({"toasts": False})
        self.assertFalse(self.backend.settings["toasts"])
        self.assertFalse(self.backend.settings["scanning"])


if __name__ == "__main__":
    unittest.main()
