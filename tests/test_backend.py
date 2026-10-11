import json
import tempfile
import unittest
from pathlib import Path

from repoproject import config, sources
from repoproject.backend import Backend, Details, _fit_files, _set_baseline
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

    def test_one_picker_from_the_newest_release(self):
        d = self.backend.details(LOCALSEND)
        self.assertEqual(d["latestTag"], "v1.18.2")
        # Only files that run on this computer can be chosen.
        self.assertEqual([f["name"] for f in d["fileChoices"]],
                         ["LocalSend-1.18.2-linux-x86-64.AppImage", "LocalSend-1.18.2-linux-x86-64.tar.gz",
                          "LocalSend-CLI-1.18.2-linux-x86-64.tar.gz"])
        self.assertTrue(d["anyFileSuits"])
        self.assertFalse(d["versionOnly"])
        self.assertFalse(d["yourFileMissing"])

    def test_files_for_other_systems_cant_be_chosen(self):
        self.backend.pickAsset(LOCALSEND, "v1.18.2", "LocalSend-1.18.2-windows-x86-64.exe")
        self.assertEqual(self.saved(LOCALSEND).asset_pattern, "")

    def test_nothing_for_this_pc_means_versions_only(self):
        # Like Obtainium: Android files only. An earlier pick of one is dropped, and only versions are tracked.
        rel = self.backend._details[LOCALSEND].releases[0]
        rel.assets = [sources.Asset("app-x86_64-release.apk", "u"), sources.Asset("app-x86_64-release.apk.idsig", "u")]
        self.backend._details[LOCALSEND].releases = [rel]
        repo = self.backend._config.find(LOCALSEND)
        repo.asset_pattern, repo.kind = "app-x86_64-release.apk.idsig", "File"
        self.assertTrue(_fit_files(repo, self.backend._details[LOCALSEND]))
        self.assertEqual((repo.asset_pattern, repo.kind), ("", "versions"))
        d = self.backend.details(LOCALSEND)
        self.assertTrue(d["versionOnly"])
        self.assertEqual(d["fileChoices"], [])
        self.assertEqual(self.backend.repo(LOCALSEND)["followText"], "Versions only (nothing for this computer)")
        # Version tracking still works.
        self.backend.setInstalled(LOCALSEND, "v1.18.2")
        self.assertEqual(self.backend.details(LOCALSEND)["status"], "Up to date")

    def test_versions_only_ends_when_a_release_adds_something_for_this_pc(self):
        repo = self.backend._config.find(LOCALSEND)
        repo.kind = "versions"
        self.assertTrue(_fit_files(repo, self.backend._details[LOCALSEND]))
        self.assertEqual(repo.kind, "")

    def test_file_missing_from_the_newest_release(self):
        repo = self.backend._config.find(LOCALSEND)
        repo.asset_pattern = "LocalSend-*-linux-x86-64.flatpak"
        self.assertTrue(self.backend.details(LOCALSEND)["yourFileMissing"])

    def test_project_with_nothing_for_this_pc(self):
        self.backend._details[LOCALSEND].releases[0].assets = [
            sources.Asset("app-x86_64-release.apk", "u"), sources.Asset("app-x86_64-release.apk.idsig", "u")]
        self.assertFalse(self.backend.details(LOCALSEND)["anyFileSuits"])

    def test_your_version_starts_at_the_newest(self):
        repo = self.backend._config.find(LOCALSEND)
        self.assertTrue(_set_baseline(repo, self.backend._details[LOCALSEND]))
        d = self.backend.details(LOCALSEND)
        self.assertEqual(repo.installed, "v1.18.2")
        self.assertEqual(d["status"], "Up to date")
        self.assertFalse(d["updateAvailable"])
        self.assertTrue(d["releases"][0]["isInstalled"])

    def test_older_version_shows_an_update(self):
        self.backend.setInstalled(LOCALSEND, "v1.18.1")
        d = self.backend.details(LOCALSEND)
        self.assertEqual(d["status"], "Newer version available: v1.18.2 (you have v1.18.1)")
        self.assertTrue(d["updateAvailable"])
        self.assertEqual(d["versionText"], "v1.18.1")
        self.assertEqual(self.saved(LOCALSEND).installed, "v1.18.1")

    def test_mark_up_to_date(self):
        self.backend.setInstalled(LOCALSEND, "v1.18.1")
        self.backend.markUpToDate(LOCALSEND)
        self.assertEqual(self.saved(LOCALSEND).installed, "v1.18.2")
        self.assertEqual(self.backend.details(LOCALSEND)["status"], "Up to date")
        # Following a branch: the newest commit on it.
        self.backend.setFollow(LOCALSEND, "branch")
        self.backend.setInstalled(LOCALSEND, "c" * 40)
        self.backend.markUpToDate(LOCALSEND)
        self.assertEqual(self.saved(LOCALSEND).installed, "a" * 40)

    def test_not_installed(self):
        self.backend.setInstalled(LOCALSEND, "-")
        d = self.backend.details(LOCALSEND)
        self.assertEqual(d["versionText"], "Not installed")
        self.assertEqual(d["status"], "The newest is v1.18.2.")

    def test_version_older_than_the_list_is_kept_as_a_choice(self):
        self.backend.setInstalled(LOCALSEND, "v1.0.0")
        d = self.backend.details(LOCALSEND)
        self.assertEqual(d["versionText"], "v1.0.0")
        self.assertTrue(d["updateAvailable"])

    def test_branch_versions_are_commits(self):
        self.backend.setFollow(LOCALSEND, "branch")
        repo = self.saved(LOCALSEND)
        self.assertEqual(repo.installed, "a" * 40)  # newest commit on "main"
        self.assertEqual(self.backend.details(LOCALSEND)["status"], "Up to date")
        self.backend.setBranch(LOCALSEND, "dev")
        self.assertEqual(self.saved(LOCALSEND).installed, "b" * 40)
        self.backend.setInstalled(LOCALSEND, "c" * 40)
        d = self.backend.details(LOCALSEND)
        self.assertEqual(d["status"], "Newer commits on dev (you have commit ccccccc)")
        self.assertEqual(d["versionText"], "commit ccccccc")

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
