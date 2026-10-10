import json
import tempfile
import unittest
from pathlib import Path

from repoproject import config, sources
from repoproject.backend import Backend, Details
from repoproject.config import TrackedRepo

FIXTURES = Path(__file__).parent / "fixtures"
LOCALSEND = "github.com/localsend/localsend"
AERO = "gitgud.io/aeroshell/atp/aerothemeplasma"


class BackendTest(unittest.TestCase):
    """The window's actions, using saved GitHub answers instead of the network."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "repos.toml"
        cfg = config.Config(repos=[
            TrackedRepo(id=LOCALSEND, name="LocalSend", url="https://github.com/localsend/localsend", host="github",
                        branch="main"),
            TrackedRepo(id=AERO, name="AeroThemePlasma", url="https://gitgud.io/aeroshell/atp/aerothemeplasma",
                        host="gitlab", follow="branch", branch="Plasma/6.7", kind="git"),
        ])
        config.save(cfg, self.path)
        self.backend = Backend(self.path)
        releases = sources.parse_github_releases(json.loads((FIXTURES / "github_releases.json").read_text()))
        self.backend._details[LOCALSEND] = Details(
            state="ready", releases=releases, default_branch="main",
            branches=[sources.Branch("main", "a" * 40), sources.Branch("dev", "b" * 40)],
        )

    def tearDown(self):
        self.backend.shutdown()
        self.dir.cleanup()

    def saved(self, repo_id):
        return config.load(self.path).find(repo_id)

    def test_picking_a_file_is_saved_and_shown_as_selected(self):
        self.backend.pickAsset(LOCALSEND, "v1.18.2", "LocalSend-1.18.2-linux-x86-64.AppImage")
        repo = self.saved(LOCALSEND)
        self.assertEqual(repo.asset_pattern, "LocalSend-*-linux-x86-64.AppImage")
        self.assertEqual(repo.kind, "AppImage")
        latest = self.backend.details(LOCALSEND)["releases"][0]
        self.assertEqual([a["name"] for a in latest["assets"] if a["selected"]],
                         ["LocalSend-1.18.2-linux-x86-64.AppImage"])
        self.assertTrue(latest["hasSelected"])

    def test_files_for_this_pc_are_marked(self):
        latest = self.backend.details(LOCALSEND)["releases"][0]
        suits = {a["name"] for a in latest["assets"] if a["suits"]}
        self.assertEqual(suits, {"LocalSend-1.18.2-linux-x86-64.AppImage", "LocalSend-1.18.2-linux-x86-64.tar.gz",
                                 "LocalSend-CLI-1.18.2-linux-x86-64.tar.gz"})

    def test_switching_to_a_branch_and_back(self):
        self.backend.pickAsset(LOCALSEND, "v1.18.2", "LocalSend-1.18.2-linux-x86-64.AppImage")
        self.backend.setFollow(LOCALSEND, "branch")
        self.assertEqual(self.saved(LOCALSEND).kind, "git")
        self.backend.setBranch(LOCALSEND, "dev")
        branches = self.backend.details(LOCALSEND)["branches"]
        self.assertEqual([b["name"] for b in branches if b["selected"]], ["dev"])
        self.backend.setFollow(LOCALSEND, "releases")
        # The picked file is remembered, and its kind restored.
        self.assertEqual(self.saved(LOCALSEND).kind, "AppImage")
        self.assertEqual(self.saved(LOCALSEND).asset_pattern, "LocalSend-*-linux-x86-64.AppImage")

    def test_unknown_file_is_ignored(self):
        self.backend.pickAsset(LOCALSEND, "v1.18.1", "LocalSend-1.18.1-linux-x86-64.AppImage")
        self.assertEqual(self.saved(LOCALSEND).asset_pattern, "")

    def test_prereleases_hidden_until_turned_on(self):
        self.backend._details[LOCALSEND].releases[0].prerelease = True
        self.assertEqual([r["tag"] for r in self.backend.details(LOCALSEND)["releases"]], ["v1.18.1"])
        self.backend.setPrereleases(LOCALSEND, True)
        self.assertEqual([r["tag"] for r in self.backend.details(LOCALSEND)["releases"]], ["v1.18.2", "v1.18.1"])

    def test_filter_and_counts(self):
        self.assertEqual(self.backend.counts, {"all": 2, "github": 1, "gitlab": 1})
        self.assertEqual([r["name"] for r in self.backend.repos], ["AeroThemePlasma", "LocalSend"])
        self.backend.filter = "gitlab"
        self.assertEqual([r["name"] for r in self.backend.repos], ["AeroThemePlasma"])
        self.backend.filter = "nonsense"
        self.assertEqual(self.backend.filter, "gitlab")

    def test_remove(self):
        self.backend.removeRepo(AERO)
        self.assertIsNone(self.saved(AERO))
        self.assertEqual(self.backend.counts["all"], 1)

    def test_bad_address_fails_without_network(self):
        failures = []
        self.backend.addFailed.connect(failures.append)
        self.backend.addRepo("", "github.com/onlyowner")
        self.backend.addRepo("", "https://gitgud.io/aeroshell/atp/aerothemeplasma.git")
        self.assertIn("owner and the project", failures[0])
        self.assertIn("Already tracking", failures[1])
        self.assertFalse(self.backend.adding)

    def test_broken_settings_file_is_never_overwritten(self):
        self.path.write_text("not [valid")
        backend = Backend(self.path)
        self.assertNotEqual(backend.configError, "")
        backend._config.repos.append(TrackedRepo(id="github.com/a/b", name="B", url="", host="github"))
        backend.removeRepo("github.com/a/b")
        self.assertEqual(self.path.read_text(), "not [valid")
        backend.shutdown()


if __name__ == "__main__":
    unittest.main()
