import json
import tempfile
import unittest
from pathlib import Path

from couriercollie import config, scan, sources
from couriercollie.backend import Backend, Details, _fit_files, _match_tag, _set_baseline
from couriercollie.config import TrackedRepo

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
        # No threads or network: comparisons with a branch are faked (BEHIND for "dev" in tests that set it up).
        self.backend._run = lambda work, done: done(work(), None)
        self.backend.compare_delay_ms = 0
        self.relations = {}
        saved = sources.compare
        sources.compare = lambda ref, host, yours, head: sources.Comparison(
            sources.SAME if yours == head else self.relations.get(head, sources.BEHIND))
        self.addCleanup(setattr, sources, "compare", saved)
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
        self.assertFalse(d["versionOnly"])
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
        self.assertTrue(self.backend.details(LOCALSEND)["versionOnly"])

    def test_hand_added_repos_start_not_installed(self):
        # Adding a repo doesn't mean you have it (e.g. "aerial", added by hand to watch it).
        repo = self.backend._config.find(LOCALSEND)
        self.assertTrue(_set_baseline(repo, self.backend._details[LOCALSEND]))
        d = self.backend.details(LOCALSEND)
        self.assertEqual((repo.installed, d["versionText"], d["status"]), ("-", "Not installed", "The newest is v1.18.2."))
        self.assertFalse(d["updateAvailable"])
        self.assertFalse(any(r["isInstalled"] for r in d["releases"]))
        # Once you have it, "Mark as Up to Date" (or "Set as My Version") records it.
        self.backend.markUpToDate(LOCALSEND)
        self.assertEqual(self.backend.details(LOCALSEND)["status"], "Up to date")

    def test_scanned_repos_get_no_assumed_version(self):
        repo = self.backend._config.find(LOCALSEND)
        repo.source = "scanned"
        self.assertFalse(_set_baseline(repo, self.backend._details[LOCALSEND]))
        self.assertEqual(repo.installed, "")

    def test_older_version_shows_an_update(self):
        self.backend.setInstalled(LOCALSEND, "v1.18.1")
        d = self.backend.details(LOCALSEND)
        self.assertEqual(d["status"], "Newer version available: v1.18.2 (you have v1.18.1)")
        self.assertTrue(d["updateAvailable"])
        self.assertEqual(d["versionText"], "v1.18.1")
        # The repo page's status box: your version and the newest side by side, under a short headline.
        self.assertEqual((d["statusKind"], d["headline"], d["newestText"]), ("update", "Update available", "v1.18.2"))
        self.assertEqual(self.saved(LOCALSEND).installed, "v1.18.1")

    def test_mark_up_to_date(self):
        self.backend.setInstalled(LOCALSEND, "v1.18.1")
        self.backend.markUpToDate(LOCALSEND)
        self.assertEqual(self.saved(LOCALSEND).installed, "v1.18.2")
        d = self.backend.details(LOCALSEND)
        self.assertEqual((d["status"], d["statusKind"], d["newestText"]), ("Up to date", "current", "v1.18.2"))
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
        self.assertEqual((d["statusKind"], d["headline"]), ("notInstalled", "Not installed"))

    def test_version_older_than_the_list_is_kept_as_a_choice(self):
        self.backend.setInstalled(LOCALSEND, "v1.0.0")
        d = self.backend.details(LOCALSEND)
        self.assertEqual(d["versionText"], "v1.0.0")
        self.assertTrue(d["updateAvailable"])

    def test_quick_branch_clicks_answered_out_of_order(self):
        # Click "old", then "dev" before the first answer is back; the first answer then arrives late.
        pending = []
        self.backend._run = lambda work, done: pending.append((work, done))
        self.relations["b" * 40] = sources.BEHIND
        d = self.backend._details[LOCALSEND]
        d.branches.append(sources.Branch("old", "c" * 40))
        repo = self.backend._config.find(LOCALSEND)
        repo.follow, repo.installed = "branch", "a" * 40
        self.backend.setBranch(LOCALSEND, "old")
        self.backend.setBranch(LOCALSEND, "dev")
        (work_old, done_old), (work_dev, done_dev) = pending
        done_old(work_old(), None)
        self.assertEqual(self.backend.details(LOCALSEND)["status"], "Checking\u2026")
        done_dev(work_dev(), None)
        self.assertEqual(self.backend.details(LOCALSEND)["status"], "Newer commits on dev (you have commit aaaaaaa)")

    def test_clicking_quickly_through_branches_asks_about_the_last_only(self):
        from couriercollie import backend as backend_module

        waiting = []
        saved = backend_module.QTimer.singleShot
        backend_module.QTimer.singleShot = lambda ms, fn: waiting.append(fn)
        self.addCleanup(setattr, backend_module.QTimer, "singleShot", saved)
        asked = []
        compare = sources.compare
        sources.compare = lambda *a: (asked.append(a[3]), compare(*a))[1]
        self.backend.compare_delay_ms = 400
        d = self.backend._details[LOCALSEND]
        d.branches.append(sources.Branch("old", "c" * 40))
        repo = self.backend._config.find(LOCALSEND)
        repo.follow, repo.installed = "branch", "a" * 40
        for branch in ("old", "dev", "old", "dev"):
            self.backend.setBranch(LOCALSEND, branch)
        for fn in waiting:  # the waits run out
            fn()
        self.assertEqual(asked, ["b" * 40])  # dev's newest commit, once
        self.assertEqual(self.backend.details(LOCALSEND)["status"], "Newer commits on dev (you have commit aaaaaaa)")

    def test_own_saves_to_the_results_file_dont_reload_the_list(self):
        from couriercollie import checker

        changed = []
        self.backend.checksChanged.connect(lambda: changed.append(1))
        checker.save_state(self.backend._checks, self.backend._state_path)
        self.backend._reload_checks()
        self.assertEqual(changed, [])
        # Written by the background checker: reloaded.
        state = checker.State(results={LOCALSEND: checker.Result(checker.UPDATE, "Update available: v9", "v9")})
        checker.save_state(state, self.backend._state_path)
        self.backend._reload_checks()
        self.assertEqual((changed, self.backend._checks), ([1], state))

    def test_a_check_keeps_repo_pages_that_are_still_current(self):
        from couriercollie import checker

        repo = self.backend._config.find(LOCALSEND)
        repo.installed = "v1.18.1"
        found = {"newest": "v1.18.2"}
        saved = checker.check_all
        checker.check_all = lambda repos, previous: (checker.State(results={LOCALSEND: checker.Result(
            checker.UPDATE, "Update available", found["newest"])}), [])
        self.addCleanup(setattr, checker, "check_all", saved)
        self.backend.checkNow()
        self.assertIn(LOCALSEND, self.backend._details)  # same newest as the page: no need to ask again
        found["newest"] = "v1.19.0"
        self.backend.checkNow()
        self.assertNotIn(LOCALSEND, self.backend._details)  # something newer: reloaded when next opened

    def test_a_check_learns_what_the_package_manager_installed(self):
        # Even for a repo whose page was never opened: no Update, here or in the list.
        from couriercollie import checker

        managed = {LOCALSEND: "dnf"}

        def check_all(repos, previous):  # what the real one does with what find_managed found
            for r in repos:
                r.managed_by = managed.get(r.id, "")
            return checker.State(results={LOCALSEND: checker.releases_result(
                [sources.Release("v2", "v2", None, False, "", "")], "v1.0", managed.get(LOCALSEND, ""))}), []

        saved = checker.check_all
        checker.check_all = check_all
        self.addCleanup(setattr, checker, "check_all", saved)
        self.backend._config.find(LOCALSEND).installed = "v1.0"
        self.backend.checkNow()
        row = self.backend.repo(LOCALSEND)
        self.assertEqual((row["checkText"], row["updateAvailable"], row["canUpdate"]),
                         ("Installed with dnf", False, False))
        self.assertEqual(self.backend._config.find(LOCALSEND).managed_by, "dnf")
        managed.clear()  # removed with dnf: couriercollie's to update again
        self.backend.checkNow()
        self.assertEqual(self.backend._config.find(LOCALSEND).managed_by, "")

    def test_branch_with_no_shared_history(self):
        # Added by hand on "main"; "dev" was started from scratch.
        self.relations["b" * 40] = sources.DIVERGED
        self.backend.setFollow(LOCALSEND, "branch")
        self.backend.markUpToDate(LOCALSEND)  # you have main's newest commit
        self.backend.setBranch(LOCALSEND, "dev")
        d = self.backend.details(LOCALSEND)
        self.assertEqual(d["status"], "Not comparable with dev: your version (commit aaaaaaa) isn\u2019t part of it.")
        self.assertFalse(d["updateAvailable"])

    def test_branch_versions_are_commits(self):
        self.backend.setFollow(LOCALSEND, "branch")
        self.assertEqual(self.saved(LOCALSEND).installed, "-")  # not installed until you say so
        self.backend.markUpToDate(LOCALSEND)
        repo = self.saved(LOCALSEND)
        self.assertEqual(repo.installed, "a" * 40)  # newest commit on "main"
        self.assertEqual(self.backend.details(LOCALSEND)["status"], "Up to date")
        # Switching branch keeps your version; it's compared with the new branch's newest commit.
        self.backend.setBranch(LOCALSEND, "dev")
        self.assertEqual(self.saved(LOCALSEND).installed, "a" * 40)
        d = self.backend.details(LOCALSEND)
        self.assertEqual(d["status"], "Newer commits on dev (you have commit aaaaaaa)")
        self.assertEqual((d["statusKind"], d["headline"], d["versionText"], d["newestText"]),
                         ("update", "New commits on dev", "commit aaaaaaa", "commit bbbbbbb"))
        self.backend.setBranch(LOCALSEND, "main")
        self.assertEqual(self.backend.details(LOCALSEND)["status"], "Up to date")
        self.backend.setBranch(LOCALSEND, "dev")
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
        # In the settings file's order, which dragging changes.
        self.assertEqual([r["name"] for r in self.backend.rows if r["kind"] == "repo"], ["LocalSend", "AeroThemePlasma"])
        self.backend.filter = "gitlab"
        self.assertEqual([r["name"] for r in self.backend.rows if r["kind"] == "repo"], ["AeroThemePlasma"])
        self.backend.filter = "nonsense"
        self.assertEqual(self.backend.filter, "gitlab")

    def rows(self):
        return [(r["kind"], r.get("label") or r["name"]) for r in self.backend.rows]

    def test_no_headings_until_there_are_categories(self):
        self.assertEqual(self.rows(), [("repo", "LocalSend"), ("repo", "AeroThemePlasma")])

    def test_adding_categories(self):
        self.assertEqual(self.backend.addCategory("  Themes "), "")
        self.assertEqual(self.backend.addCategory("Tools"), "")
        self.assertIn("already", self.backend.addCategory("themes"))
        self.assertIn("Uncategorized", self.backend.addCategory("uncategorized"))
        self.assertIn("name", self.backend.addCategory("  "))
        self.assertEqual(config.load(self.path).categories, ["Themes", "Tools"])
        self.assertEqual(self.rows(), [("category", "Uncategorized"), ("repo", "LocalSend"), ("repo", "AeroThemePlasma"),
                                       ("category", "Themes"), ("category", "Tools")])

    def test_dragging_repos_between_categories(self):
        self.backend.addCategory("Themes")
        self.backend.moveRepo(AERO, "Themes", "")
        self.assertEqual(self.saved(AERO).category, "Themes")
        self.backend.moveRepo(LOCALSEND, "Themes", AERO)  # dropped above AeroThemePlasma
        self.assertEqual(self.rows(), [("category", "Uncategorized"),
                                       ("category", "Themes"), ("repo", "LocalSend"), ("repo", "AeroThemePlasma")])
        self.assertEqual([r.id for r in config.load(self.path).repos], [LOCALSEND, AERO])
        self.backend.moveRepo(LOCALSEND, "Themes", "")  # dropped at the end
        self.assertEqual(self.rows()[2:], [("repo", "AeroThemePlasma"), ("repo", "LocalSend")])
        self.backend.moveRepo(LOCALSEND, "", "")  # back out
        self.assertEqual(self.saved(LOCALSEND).category, "")
        self.backend.moveRepo(LOCALSEND, "No such category", "")
        self.assertEqual(self.saved(LOCALSEND).category, "")

    def test_counts_follow_the_filter(self):
        self.backend.addCategory("Themes")
        self.backend.moveRepo(AERO, "Themes", "")
        self.backend.filter = "github"
        heads = [(r["label"], r["count"]) for r in self.backend.rows if r["kind"] == "category"]
        self.assertEqual(heads, [("Uncategorized", 1), ("Themes", 0)])

    def test_dragging_categories(self):
        for name in ("A", "B", "C"):
            self.backend.addCategory(name)
        self.backend.moveCategory("C", "A")
        self.assertEqual(self.backend.categories, ["C", "A", "B"])
        self.backend.moveCategory("C", "")
        self.assertEqual(config.load(self.path).categories, ["A", "B", "C"])

    def test_renaming_a_category(self):
        self.backend.addCategory("Themes")
        self.backend.addCategory("Tools")
        self.backend.moveRepo(AERO, "Themes", "")
        self.assertEqual(self.backend.renameCategory("Themes", " Desktop "), "")
        self.assertEqual(config.load(self.path).categories, ["Desktop", "Tools"])  # same place
        self.assertEqual(self.saved(AERO).category, "Desktop")  # repos go with it
        self.assertIn("already", self.backend.renameCategory("Desktop", "tools"))
        self.assertIn("Uncategorized", self.backend.renameCategory("Desktop", "Uncategorized"))
        self.assertIn("name", self.backend.renameCategory("Desktop", ""))
        self.assertEqual(self.backend.renameCategory("Desktop", "DESKTOP"), "")  # only the case changes
        self.assertEqual(self.backend.categories, ["DESKTOP", "Tools"])
        self.assertEqual(self.saved(AERO).category, "DESKTOP")

    def test_deleting_a_category_keeps_its_repos(self):
        self.backend.addCategory("Themes")
        self.backend.addCategory("Tools")
        self.backend.moveRepo(LOCALSEND, "Themes", "")
        self.backend.deleteCategory("Themes")
        self.assertEqual(config.load(self.path).categories, ["Tools"])
        self.assertEqual(self.saved(LOCALSEND).category, "")
        # It goes to the end of Uncategorized.
        self.assertEqual(self.rows(), [("category", "Uncategorized"), ("repo", "AeroThemePlasma"), ("repo", "LocalSend"),
                                       ("category", "Tools")])
        self.backend.deleteCategory("Tools")
        self.assertEqual(self.rows(), [("repo", "AeroThemePlasma"), ("repo", "LocalSend")])

    def test_release_notes_pictures_become_links(self):
        from couriercollie.backend import _without_images

        notes = ('New look ![screenshot](https://x.org/a.png "title")\n'
                 '<img width="300" src="https://x.org/b.png" alt="b">\n![](https://x.org/c.gif)')
        self.assertEqual(_without_images(notes), "New look [picture: screenshot](https://x.org/a.png)\n"
                                                 "[picture](https://x.org/b.png)\n[picture: image](https://x.org/c.gif)")

    def test_remove(self):
        from couriercollie import checker

        self.backend._checks.results[AERO] = checker.Result(checker.UPDATE, "Update available", "x")
        self.backend.removeRepo(AERO)
        self.assertIsNone(self.saved(AERO))
        self.assertNotIn(AERO, checker.load_state(self.backend._state_path).results)  # its last result goes too
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



class ScannedClonePageTest(unittest.TestCase):
    """Opening a scanned clone's page: its version comes from disk, and what's new is listed."""

    def setUp(self):
        from tests.test_scan import make_clone

        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "repos.toml"
        clone = Path(self.dir.name) / "smod"
        self.on_disk = make_clone(clone, "https://gitgud.io/aeroshell/smod.git", "Plasma/6.7")
        self.head = "b" * 40
        config.save(config.Config(repos=[TrackedRepo(
            id="gitgud.io/aeroshell/smod", name="SMOD", url="", host="gitlab", follow="branch", branch="Plasma/6.7",
            kind="git", source="scanned", local_path=str(clone),
            installed=self.head)]), self.path)  # e.g. marked up to date earlier, while the clone stayed behind
        self.backend = Backend(self.path)
        self.backend._run = lambda work, done: done(work(), None)
        self.backend.compare_delay_ms = 0  # no threads in tests
        self.master = "c" * 40
        self.hidpi = "d" * 40
        branches = [sources.Branch("Plasma/6.7", None), sources.Branch("master", self.master),
                    sources.Branch("hidpi-functionality", self.hidpi)]

        def fake_branches(ref):
            branches[0].sha = self.head
            return "Plasma/6.7", branches

        def fake_compare(ref, host, yours, head):
            if yours == head:
                return sources.Comparison(sources.SAME)
            if head == self.master:
                return sources.Comparison(sources.AHEAD)
            if head == self.hidpi:
                return sources.Comparison(sources.DIVERGED, 2, [])
            return sources.Comparison(sources.BEHIND, 1, [sources.Commit(head, "Button: fallback textures")])

        self.saved = (sources.releases, sources.branches, sources.compare)
        sources.releases, sources.branches, sources.compare = (lambda ref, host, **_: []), fake_branches, fake_compare

    def tearDown(self):
        sources.releases, sources.branches, sources.compare = self.saved
        self.backend.shutdown()
        self.dir.cleanup()

    def test_version_comes_from_disk_and_whats_new_is_listed(self):
        self.backend.loadDetails("gitgud.io/aeroshell/smod", True)
        d = self.backend.details("gitgud.io/aeroshell/smod")
        self.assertEqual(config.load(self.path).repos[0].installed, self.on_disk)
        self.assertTrue(d["updateAvailable"])
        self.assertTrue(d["versionFromDisk"])
        self.assertEqual((d["newCommitsTotal"], d["newCommits"][0]["title"]), (1, "Button: fallback textures"))

    def test_what_the_page_learned_shows_in_the_list(self):
        # The last check found it up to date; since then, a commit was pushed. Opening the page sees it.
        from couriercollie import checker

        smod = "gitgud.io/aeroshell/smod"
        self.backend._checks.results[smod] = checker.Result(checker.UP_TO_DATE, "Up to date", self.on_disk)
        self.backend.loadDetails(smod, True)
        row = self.backend.repo(smod)
        self.assertEqual((row["checkText"], row["updateAvailable"]), ("1 new commit on Plasma/6.7", True))
        self.assertEqual(self.backend._checks.notified[smod], self.head)  # seen: not announced again later

    def test_the_page_says_when_something_else_updates_it(self):
        import couriercollie.backend as backend_module

        saved = backend_module._managed_elsewhere
        backend_module._managed_elsewhere = lambda ids: ("Your package manager also keeps this up to date.", "dnf", "1.0")
        self.addCleanup(setattr, backend_module, "_managed_elsewhere", saved)
        smod = "gitgud.io/aeroshell/smod"
        self.backend.loadDetails(smod, True)
        d = self.backend.details(smod)
        self.assertEqual(d["managedElsewhere"], "Your package manager also keeps this up to date.")
        # Even with a version of its own read from disk and new commits upstream: shown only, never updated here.
        self.assertEqual((d["managedBy"], d["statusKind"], d["headline"], d["versionText"]),
                         ("dnf", "managed", "Installed with dnf", "1.0"))
        self.assertEqual((d["canUpdate"], d["updateAvailable"], d["installClones"]), (False, False, False))
        row = self.backend.repo(smod)
        self.assertEqual((row["canUpdate"], row["updateAvailable"], row["checkText"]),
                         (False, False, "Installed with dnf"))

    def test_reopening_the_page_asks_nothing(self):
        # Loaded the first time it's opened; after that only Refresh (or a check that found something newer) reloads.
        smod = "gitgud.io/aeroshell/smod"
        asked = []
        for name in ("releases", "branches", "compare"):
            fake = getattr(sources, name)
            setattr(sources, name, lambda *a, _f=fake, _n=name, **k: (asked.append(_n), _f(*a, **k))[1])
        self.backend.loadDetails(smod, False)
        self.assertEqual(sorted(asked), ["branches", "compare", "releases"])
        asked.clear()
        self.backend.loadDetails(smod, False)
        self.assertEqual(asked, [])
        self.backend.loadDetails(smod, True)  # Refresh
        self.assertEqual(sorted(asked), ["branches", "compare", "releases"])

    def test_up_to_date_clone(self):
        self.head = self.on_disk
        self.backend.loadDetails("gitgud.io/aeroshell/smod", True)
        d = self.backend.details("gitgud.io/aeroshell/smod")
        self.assertEqual((d["status"], d["newCommitsTotal"]), ("Up to date", 0))

    def test_other_branches_arent_updates(self):
        smod = "gitgud.io/aeroshell/smod"
        self.backend.loadDetails(smod, True)
        self.backend.setBranch(smod, "master")
        d = self.backend.details(smod)
        # The clone is on Plasma/6.7, which has everything on master: nothing new there, and following its own
        # branch is offered (Update isn't: it can't pull a branch the clone isn't on).
        self.assertEqual((d["headline"], d["updateAvailable"]), ("Nothing new on master", False))
        self.assertIn("already in your clone, which is on Plasma/6.7", d["status"])
        self.assertEqual(d["statusKind"], "ahead")
        self.assertEqual((d["followDiskBranch"], d["canUpdate"]), ("Plasma/6.7", False))
        self.backend.setBranch(smod, d["followDiskBranch"])  # Follow Plasma/6.7
        self.assertEqual(self.backend.details(smod)["followDiskBranch"], "")
        self.backend.setBranch(smod, "hidpi-functionality")
        d = self.backend.details(smod)
        self.assertEqual(d["status"], "Not comparable with hidpi-functionality: your clone is on Plasma/6.7.")
        self.assertFalse(d["updateAvailable"])
        self.assertEqual(d["newCommits"], [])

    def test_cant_compare(self):
        sources.compare = lambda *a: (_ for _ in ()).throw(sources.SourceError("404"))
        self.backend.loadDetails("gitgud.io/aeroshell/smod", True)
        d = self.backend.details("gitgud.io/aeroshell/smod")
        self.assertTrue(d["status"].startswith("Couldn\u2019t compare your version"), d["status"])
        self.assertFalse(d["updateAvailable"])
        self.assertEqual((d["statusKind"], d["headline"]), ("problem", "Couldn\u2019t compare"))

    def test_switching_branch_and_back_keeps_the_version_on_disk(self):
        smod = "gitgud.io/aeroshell/smod"
        self.backend.loadDetails(smod, True)
        self.backend.setBranch(smod, "master")
        self.backend.setBranch(smod, "Plasma/6.7")
        d = self.backend.details(smod)
        self.assertEqual(config.load(self.path).repos[0].installed, self.on_disk)
        self.assertTrue(d["updateAvailable"], d["status"])
        self.assertEqual(d["newCommitsTotal"], 1)  # the list is back for this branch

    def test_disk_wins_over_a_version_set_by_hand(self):
        # The page hides "Mark as…" for scanned repos; even if the version is set another way, disk wins on the
        # next read, and the list of new commits follows.
        smod = "gitgud.io/aeroshell/smod"
        self.backend.loadDetails(smod, True)
        self.backend.setInstalled(smod, self.head)
        self.assertEqual(config.load(self.path).repos[0].installed, self.on_disk)
        self.assertEqual(self.backend.details(smod)["newCommitsTotal"], 1)


class OfflineTest(unittest.TestCase):
    """No internet: every action says so plainly, nothing is lost, and trying again works."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "repos.toml"
        config.save(config.Config(settings=config.Settings(scanning=True), repos=[
            TrackedRepo(id=LOCALSEND, name="LocalSend", url="", host="github", installed="v1.18.0")]), self.path)
        self.backend = Backend(self.path)
        self.backend._run = lambda work, done: self._finish(work, done)
        self.saved = (sources.project_info, sources.releases, sources.branches, sources.compare)
        self.offline = True

        def unreachable(*_args, **_kw):
            raise sources.SourceError("Couldn\u2019t reach github.com. Check your internet connection.")

        def releases(*a, **_):
            if self.offline:
                unreachable()
            return sources.parse_github_releases(json.loads((FIXTURES / "github_releases.json").read_text()))

        sources.project_info = unreachable
        sources.releases = releases
        sources.branches = lambda ref: unreachable() if self.offline else ("main", [sources.Branch("main", "a" * 40)])

    def _finish(self, work, done):
        try:
            result, error = work(), None
        except Exception as e:  # noqa: BLE001
            result, error = None, e
        done(result, error)

    def tearDown(self):
        sources.project_info, sources.releases, sources.branches, sources.compare = self.saved
        self.backend.shutdown()
        self.dir.cleanup()

    def test_adding(self):
        failures = []
        self.backend.addFailed.connect(failures.append)
        self.backend.addRepo("", "https://github.com/someone/thing")
        self.assertEqual(failures, ["Couldn\u2019t reach github.com. Check your internet connection."])
        self.assertFalse(self.backend.adding)
        self.assertEqual(len(config.load(self.path).repos), 1)

    def test_repo_page_then_try_again(self):
        self.backend.loadDetails(LOCALSEND, False)
        d = self.backend.details(LOCALSEND)
        self.assertEqual(d["state"], "error")
        self.assertIn("Couldn\u2019t reach", d["error"])
        self.assertEqual(config.load(self.path).repos[0].installed, "v1.18.0")  # nothing lost
        self.offline = False
        self.backend.loadDetails(LOCALSEND, True)  # "Try Again"
        self.assertEqual(self.backend.details(LOCALSEND)["state"], "ready")

    def test_scan(self):
        # A tracked repo is still updated from disk; a new find explains why it couldn't be checked.
        finds = [scan.Found(id=LOCALSEND, name="localsend", url="", host="", path="/x/LocalSend-1.18.2.AppImage",
                            kind="AppImage", version="1.18.2"),
                 scan.Found(id="github.com/new/thing", name="thing", url="", host="", path="/x/thing", kind="git",
                            version="abc")]
        saved_find_all = scan.find_all
        scan.find_all = lambda folders: finds
        try:
            self.backend.startScan()
        finally:
            scan.find_all = saved_find_all
        self.assertEqual(self.backend.scanState, "done")
        self.assertEqual(self.backend.scanUpdated, ["LocalSend"])
        [item] = self.backend.scanItems
        self.assertEqual(item["status"], "problem")
        self.assertIn("Couldn\u2019t reach", item["note"])

    def test_a_site_found_unsupported_isnt_asked_again(self):
        finds = [scan.Found(id=f"git.sr.ht/~me/{n}", name=n, url="", host="", path=f"/x/{n}", kind="git", version="a")
                 for n in ("one", "two")]
        asked = []

        def project_info(ref, get=None):
            asked.append(ref.id)
            raise sources.Unsupported(sources.unsupported_text(ref.domain))

        saved = scan.find_all, sources.project_info
        scan.find_all, sources.project_info = (lambda folders: finds), project_info
        try:
            self.backend.startScan()
            first = len(asked)
            self.backend.startScan()
        finally:
            scan.find_all, sources.project_info = saved
        self.assertGreaterEqual(first, 1)
        self.assertEqual(len(asked), first)  # the second scan asked nothing
        self.assertTrue(all("git.sr.ht isn\u2019t supported yet" in i["note"] for i in self.backend.scanItems))


class ScanFlowTest(unittest.TestCase):
    """What the Scan button does with results, using prepared finds instead of the disk and network."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "repos.toml"
        cfg = config.Config(settings=config.Settings(scanning=True), repos=[
            TrackedRepo(id="github.com/aeroshell-desktop/aerothemeplasma", name="Aero", url="https://github.com/x",
                        host="github", follow="branch", branch="Plasma/6.7",
                        description="An alternative shell for KDE Plasma."),
            TrackedRepo(id=LOCALSEND, name="LocalSend", url="", host="github", installed="v1.18.0"),
        ])
        config.save(cfg, self.path)
        self.backend = Backend(self.path)

    def tearDown(self):
        self.backend.shutdown()
        self.dir.cleanup()

    def found(self, repo_id, kind="git", version="abc", description="", path=None):
        return scan.Found(id=repo_id, name=repo_id.rsplit("/", 1)[-1], url=f"https://{repo_id}", host="gitlab",
                          path=path or f"/home/me/{repo_id.rsplit('/', 1)[-1]}", kind=kind, version=version,
                          branch="main", description=description)

    def run_scan(self):
        self.backend._scan_done([
            scan.Checked(self.found(LOCALSEND, kind="RPM", version="1.18.2")),  # already tracked
            scan.Checked(self.found("gitgud.io/aeroshell/smod")),  # new
            scan.Checked(self.found("gitgud.io/aeroshell/atp/aerothemeplasma",
                                    description="An alternative shell for KDE Plasma. ")),  # a mirror of Aero
            scan.Checked(self.found("github.com/me/private"), "Not found on its site. It may be private."),
        ], None)
        return {i["address"]: i for i in self.backend.scanItems}

    def test_tracked_repos_are_updated_without_asking(self):
        items = self.run_scan()
        self.assertNotIn(LOCALSEND, items)
        self.assertEqual(self.backend.scanUpdated, ["LocalSend"])
        repo = config.load(self.path).find(LOCALSEND)
        self.assertEqual((repo.source, repo.installed), ("scanned", "1.18.2"))

    def test_results_list_new_similar_and_problems(self):
        items = self.run_scan()
        self.assertEqual(items["gitgud.io/aeroshell/smod"]["status"], "new")
        mirror = items["gitgud.io/aeroshell/atp/aerothemeplasma"]
        self.assertEqual(mirror["status"], "similar")
        self.assertIn("Aero", mirror["note"])
        self.assertEqual(items["github.com/me/private"]["status"], "problem")

    def test_tracking_ticked_finds(self):
        items = self.run_scan()
        keys = [items[a]["key"] for a in ("gitgud.io/aeroshell/smod", "gitgud.io/aeroshell/atp/aerothemeplasma",
                                          "github.com/me/private")]
        self.backend.trackFound(keys)
        cfg = config.load(self.path)
        self.assertEqual(len(cfg.repos), 3)  # Aero, LocalSend, smod: the mirror was linked, the problem skipped
        aero = cfg.find("github.com/aeroshell-desktop/aerothemeplasma")
        self.assertEqual((aero.source, aero.aliases), ("scanned", ["gitgud.io/aeroshell/atp/aerothemeplasma"]))
        self.assertEqual(cfg.find("gitgud.io/aeroshell/smod").source, "scanned")
        # Tracked finds leave the results; problems stay so the user can read why.
        self.assertEqual([i["address"] for i in self.backend.scanItems], ["github.com/me/private"])

    def test_scan_needs_scanning_turned_on(self):
        self.backend.updateSettings({"scanning": False})
        self.backend.startScan()
        self.assertEqual(self.backend.scanState, "idle")

    def test_found_version_matches_the_release_tag(self):
        self.run_scan()
        releases = sources.parse_github_releases(json.loads((FIXTURES / "github_releases.json").read_text()))
        repo = self.backend._config.find(LOCALSEND)
        self.assertTrue(_match_tag(repo, Details(state="ready", releases=releases)))
        self.assertEqual(repo.installed, "v1.18.2")


if __name__ == "__main__":
    unittest.main()


class OlderReleasesTest(unittest.TestCase):
    """A repo's page loads the newest few releases; Show Older Releases loads a full page."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        path = Path(self.dir.name) / "repos.toml"
        self.id = "github.com/a/app"
        config.save(config.Config(repos=[TrackedRepo(id=self.id, name="App", url="", host="github",
                                                     installed="v25")]), path)
        self.backend = Backend(path)
        self.backend._run = lambda work, done: done(work(), None)
        self.asked = []
        all_releases = [sources.Release(f"v{n}", f"v{n}", None, False, "", "", []) for n in range(40, 0, -1)]

        def releases(ref, host, count=sources.RELEASES_PER_PAGE):
            self.asked.append(count)
            return all_releases[:count]

        self.saved = sources.releases, sources.branches
        sources.releases, sources.branches = releases, lambda ref: ("main", [])

    def tearDown(self):
        sources.releases, sources.branches = self.saved
        self.backend.shutdown()
        self.dir.cleanup()

    def test_newest_few_then_older_on_request(self):
        self.backend.loadDetails(self.id, False)
        d = self.backend.details(self.id)
        self.assertEqual((len(d["releases"]), d["moreReleases"], self.asked), (10, True, [10]))
        # Your version (v25) isn't among them yet: still an update.
        self.assertEqual(d["statusKind"], "update")
        self.backend.loadOlderReleases(self.id)
        d = self.backend.details(self.id)
        self.assertEqual((len(d["releases"]), d["moreReleases"], self.asked[-1]), (30, False, 30))
        self.assertTrue(next(r for r in d["releases"] if r["tag"] == "v25")["isInstalled"])
        self.backend.loadOlderReleases(self.id)  # nothing more to ask for
        self.assertEqual(len(self.asked), 2)
