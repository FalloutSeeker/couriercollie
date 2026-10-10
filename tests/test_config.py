import tempfile
import tomllib
import unittest
from pathlib import Path

from repoproject import config, tomlwrite
from repoproject.config import Config, ConfigError, Settings, TrackedRepo


class TomlWriteTest(unittest.TestCase):
    def test_round_trips_through_pythons_reader(self):
        data = {
            "settings": {"auto_check": True, "check_interval_hours": 6, "ratio": 0.5},
            "repos": [
                {"id": "github.com/a/b", "name": 'Quote " and \\ backslash', "tags": ["x", "y"]},
                {"id": "gitgud.io/g/s/p", "name": "Tab\tnew\nline \x01 ünïcode", "on": False},
            ],
            "odd key": "needs quotes",
        }
        self.assertEqual(tomllib.loads(tomlwrite.dumps(data)), data)

    def test_empty_list_is_written_as_an_empty_array(self):
        self.assertEqual(tomllib.loads(tomlwrite.dumps({"repos": []})), {"repos": []})

    def test_refuses_unknown_types(self):
        with self.assertRaises(TypeError):
            tomlwrite.dumps({"x": None})


class ConfigTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "sub" / "repos.toml"

    def tearDown(self):
        self.dir.cleanup()

    def test_missing_file_gives_defaults(self):
        cfg = config.load(self.path)
        self.assertEqual(cfg.settings, Settings())
        self.assertEqual(cfg.repos, [])

    def test_defaults_match_the_design(self):
        s = Settings()
        # DECISIONS.md D5, D11, D12: automatic checks, scanning and cleanup are all off until the user turns them on.
        self.assertFalse(s.auto_check)
        self.assertFalse(s.scanning)
        self.assertFalse(s.delete_old)
        self.assertTrue(s.toasts)
        self.assertFalse(s.first_launch_done)

    def test_save_then_load(self):
        cfg = Config(
            settings=Settings(auto_check=True, check_interval_hours=12),
            repos=[
                TrackedRepo(id="github.com/a/b", name="B", url="https://github.com/a/b", host="github",
                            asset_pattern="B-*-x86_64.AppImage", kind="AppImage"),
                TrackedRepo(id="gitgud.io/x/y", name="Y", url="https://gitgud.io/x/y", host="gitlab",
                            follow=config.FOLLOW_BRANCH, branch="Plasma/6.7", kind="git"),
            ],
        )
        config.save(cfg, self.path)
        self.assertEqual(config.load(self.path), cfg)
        self.assertFalse(self.path.with_suffix(".toml.tmp").exists())

    def test_unknown_keys_are_ignored_and_missing_keys_defaulted(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text(
            '[settings]\nauto_check = true\nfrom_the_future = 1\n\n'
            '[[repos]]\nid = "github.com/a/b"\nname = "B"\nurl = "https://github.com/a/b"\nhost = "github"\n'
        )
        cfg = config.load(self.path)
        self.assertTrue(cfg.settings.auto_check)
        self.assertEqual(cfg.repos[0].follow, config.FOLLOW_RELEASES)

    def test_broken_file_raises_instead_of_being_replaced(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("this is [not toml")
        with self.assertRaises(ConfigError):
            config.load(self.path)
        self.assertEqual(self.path.read_text(), "this is [not toml")

    def test_find(self):
        cfg = Config(repos=[TrackedRepo(id="a/b/c", name="C", url="", host="github")])
        self.assertEqual(cfg.find("a/b/c").name, "C")
        self.assertIsNone(cfg.find("nope"))


if __name__ == "__main__":
    unittest.main()
