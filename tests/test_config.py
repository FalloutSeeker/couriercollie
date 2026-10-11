import tempfile
import tomllib
import unittest
from pathlib import Path

from couriercollie import config, tomlwrite
from couriercollie.config import Config, ConfigError, Settings, TrackedRepo


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
        self.assertTrue(s.toasts)
        self.assertFalse(s.first_launch_done)

    def test_save_then_load(self):
        cfg = Config(
            settings=Settings(auto_check=True, check_interval_hours=336),
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

    def test_values_of_the_wrong_kind_get_defaults(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text('[settings]\nscanning = "yes"\nscan_folders = "/opt"\ncheck_interval_hours = true\n\n'
                             '[[repos]]\nid = "github.com/a/b"\nname = "B"\nurl = ""\nhost = "github"\n'
                             'installed = 5\naliases = ["ok", 3]\nprereleases = "no"\n')
        cfg = config.load(self.path)
        self.assertEqual((cfg.settings.scanning, cfg.settings.scan_folders, cfg.settings.check_interval_hours),
                         (False, ["~", "/opt", "/usr/local", "/srv"], 24))
        repo = cfg.repos[0]
        self.assertEqual((repo.installed, repo.aliases, repo.prereleases), ("", [], False))

    def test_unusable_required_field_makes_the_file_unreadable(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text('[[repos]]\nid = 5\nname = "B"\nurl = ""\nhost = "github"\n')
        with self.assertRaises(ConfigError):
            config.load(self.path)
        self.path.write_text('settings = "not a table"\n')
        with self.assertRaises(ConfigError):
            config.load(self.path)

    def test_broken_file_raises_instead_of_being_replaced(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("this is [not toml")
        with self.assertRaises(ConfigError):
            config.load(self.path)
        self.assertEqual(self.path.read_text(), "this is [not toml")

    def test_find_any_matches_aliases_and_ignores_case(self):
        cfg = Config(repos=[TrackedRepo(id="gitgud.io/aeroshell/atp/aerothemeplasma", name="A", url="", host="gitlab",
                                        aliases=["gitgud.io/wackyideas/aerothemeplasma"])])
        self.assertIsNotNone(cfg.find_any("gitgud.io/WackyIdeas/AeroThemePlasma"))
        self.assertIsNotNone(cfg.find_any("GITGUD.IO/aeroshell/atp/aerothemeplasma"))
        self.assertIsNone(cfg.find_any("gitgud.io/someone/else"))

    def test_categories_and_repo_order_are_kept(self):
        cfg = Config(categories=["Themes", "Tools"], repos=[
            TrackedRepo(id="a/b/z", name="Zed", url="", host="github", category="Tools"),
            TrackedRepo(id="a/b/a", name="Aero", url="", host="github"),
        ])
        config.save(cfg, self.path)
        self.assertEqual(config.load(self.path), cfg)

    def test_file_from_before_categories_keeps_its_order_by_name(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text('[[repos]]\nid = "a/b/z"\nname = "zed"\nurl = ""\nhost = "github"\n\n'
                             '[[repos]]\nid = "a/b/a"\nname = "Aero"\nurl = ""\nhost = "github"\n')
        cfg = config.load(self.path)
        self.assertEqual([r.name for r in cfg.repos], ["Aero", "zed"])
        self.assertEqual(cfg.categories, [])

    def test_hand_edited_categories_are_tidied(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text('categories = ["Tools", " ", "tools", 3]\n\n'
                             '[[repos]]\nid = "a/b/c"\nname = "C"\nurl = ""\nhost = "github"\ncategory = "TOOLS"\n\n'
                             '[[repos]]\nid = "a/b/d"\nname = "D"\nurl = ""\nhost = "github"\ncategory = "Games"\n')
        cfg = config.load(self.path)
        # Blanks and repeats dropped; a category only a repo mentions is added, so the repo doesn't lose it.
        self.assertEqual(cfg.categories, ["Tools", "Games"])
        self.assertEqual([r.category for r in cfg.repos], ["Tools", "Games"])

    def test_a_repo_listed_twice_by_hand_is_kept_once(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text('categories = []\n\n'
                             '[[repos]]\nid = "github.com/a/b"\nname = "First"\nurl = ""\nhost = "github"\n\n'
                             '[[repos]]\nid = "github.com/A/B"\nname = "Again"\nurl = ""\nhost = "github"\n')
        self.assertEqual([r.name for r in config.load(self.path).repos], ["First"])

    def test_find(self):
        cfg = Config(repos=[TrackedRepo(id="a/b/c", name="C", url="", host="github")])
        self.assertEqual(cfg.find("a/b/c").name, "C")
        self.assertIsNone(cfg.find("nope"))


if __name__ == "__main__":
    unittest.main()
