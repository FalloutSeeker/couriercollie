import tempfile
import unittest
from pathlib import Path

from repoproject import config, scan
from repoproject.config import Config, TrackedRepo
from repoproject.scan import Found

AERO_NEW = "gitgud.io/aeroshell/atp/aerothemeplasma"
AERO_OLD = "gitgud.io/wackyideas/aerothemeplasma"


def aero_clone(repo_id=AERO_OLD, version="e4cca91b12dd9419485c19bece76534972324f6a"):
    return Found(id=repo_id, name="aerothemeplasma", url=f"https://{repo_id}", host="gitlab",
                 path="/home/me/aero/aerothemeplasma", kind="git", version=version, branch="Plasma/6.7")


class MergeTest(unittest.TestCase):
    """A scan must turn manual entries into scanned ones, never add them twice (DECISIONS.md, D12)."""

    def manual_aero(self, **kw):
        return TrackedRepo(id=AERO_NEW, name="Aero", url=f"https://{AERO_NEW}", host="gitlab", follow="branch",
                           branch="Plasma/6.7", kind="git", installed="f9eb10a" + "0" * 33, **kw)

    def test_new_find_is_added_as_scanned(self):
        cfg = Config()
        result = scan.merge(cfg, [aero_clone(AERO_NEW)])
        self.assertEqual(len(cfg.repos), 1)
        self.assertEqual(result.added, cfg.repos)
        repo = cfg.repos[0]
        self.assertEqual((repo.source, repo.local_path, repo.follow, repo.branch),
                         ("scanned", "/home/me/aero/aerothemeplasma", "branch", "Plasma/6.7"))
        self.assertTrue(repo.installed.startswith("e4cca91"))

    def test_manual_entry_becomes_scanned_not_duplicated(self):
        cfg = Config(repos=[self.manual_aero()])
        result = scan.merge(cfg, [aero_clone(AERO_NEW)])
        self.assertEqual(len(cfg.repos), 1)
        self.assertEqual(result.added, [])
        repo = cfg.repos[0]
        self.assertEqual(repo.source, "scanned")
        self.assertEqual(repo.name, "Aero")  # the name you gave it stays
        self.assertTrue(repo.installed.startswith("e4cca91"))  # the version on disk wins

    def test_clone_under_an_old_address_matches_a_remembered_alias(self):
        # Added by hand as the old address; the site redirected, so the old one was kept as an alias.
        cfg = Config(repos=[self.manual_aero(aliases=[AERO_OLD])])
        scan.merge(cfg, [aero_clone(AERO_OLD)], resolve=lambda _id: self.fail("shouldn't need to ask the site"))
        self.assertEqual(len(cfg.repos), 1)
        self.assertEqual(cfg.repos[0].source, "scanned")

    def test_clone_under_an_old_address_asks_the_site_once(self):
        # Added by hand with the new address; the clone on disk still uses the old one.
        cfg = Config(repos=[self.manual_aero()])
        asked = []

        def resolve(repo_id):
            asked.append(repo_id)
            return AERO_NEW if repo_id == AERO_OLD else None

        scan.merge(cfg, [aero_clone(AERO_OLD)], resolve)
        self.assertEqual(len(cfg.repos), 1)
        self.assertEqual(cfg.repos[0].source, "scanned")
        self.assertEqual(cfg.repos[0].aliases, [AERO_OLD])
        # Next scan: matched straight away.
        scan.merge(cfg, [aero_clone(AERO_OLD)], resolve)
        self.assertEqual(asked, [AERO_OLD])
        self.assertEqual(len(cfg.repos), 1)

    def test_upper_and_lower_case_are_the_same_project(self):
        cfg = Config(repos=[TrackedRepo(id="github.com/ImranR98/Obtainium", name="obt", url="", host="github")])
        found = Found(id="github.com/imranr98/obtainium", name="Obtainium", url="", host="github",
                      path="/home/me/Obtainium", kind="git", version="abc")
        scan.merge(cfg, [found])
        self.assertEqual(len(cfg.repos), 1)

    def test_installed_from_the_app_then_scanned(self):
        # Stage 5 will install from the app; the next scan finds it on disk and flags it as scanned, same entry.
        cfg = Config(repos=[TrackedRepo(id="github.com/localsend/localsend", name="LocalSend", url="", host="github",
                                        asset_pattern="LocalSend-*-linux-x86-64.AppImage", kind="AppImage",
                                        installed="v1.18.2")])
        found = Found(id="github.com/localsend/localsend", name="LocalSend", url="", host="github",
                      path="/home/me/Applications/LocalSend-1.18.2-linux-x86-64.AppImage", kind="AppImage",
                      version="v1.18.2")
        scan.merge(cfg, [found])
        repo = cfg.repos[0]
        self.assertEqual((len(cfg.repos), repo.source, repo.follow, repo.asset_pattern),
                         (1, "scanned", "releases", "LocalSend-*-linux-x86-64.AppImage"))

    def test_same_project_found_twice_in_one_scan(self):
        cfg = Config()
        scan.merge(cfg, [aero_clone(AERO_NEW), aero_clone(AERO_NEW)])
        self.assertEqual(len(cfg.repos), 1)

    def test_scanned_entries_survive_saving(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "repos.toml"
            cfg = Config(repos=[self.manual_aero()])
            scan.merge(cfg, [aero_clone(AERO_OLD)], lambda _id: AERO_NEW)
            config.save(cfg, path)
            repo = config.load(path).repos[0]
            self.assertEqual((repo.source, repo.aliases), ("scanned", [AERO_OLD]))


if __name__ == "__main__":
    unittest.main()
