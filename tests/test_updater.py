import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from repoproject import updater

ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
       "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_GLOBAL": "/dev/null"}


def git(folder, *args):
    return subprocess.run(["git", "-C", str(folder), *args], check=True, capture_output=True, text=True,
                          env=ENV).stdout.strip()


class UpstreamCase(unittest.TestCase):
    """A real project repo ("upstream"), your clone of it, and new commits pushed upstream."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        root = Path(self.dir.name)
        self.upstream, self.clone, self.other = root / "upstream.git", root / "clone", root / "other"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.upstream)], check=True, env=ENV)
        subprocess.run(["git", "clone", "-q", str(self.upstream), str(self.other)], check=True, env=ENV,
                       capture_output=True)
        (self.other / "a.txt").write_text("one\n")
        git(self.other, "add", ".")
        git(self.other, "commit", "-q", "-m", "first")
        git(self.other, "push", "-q", "origin", "HEAD:main")
        subprocess.run(["git", "clone", "-q", str(self.upstream), str(self.clone)], check=True, env=ENV,
                       capture_output=True)
        self.start = git(self.clone, "rev-parse", "HEAD")

    def tearDown(self):
        os.chmod(self.clone / ".git", 0o755)
        self.dir.cleanup()

    def push_upstream(self, n=1, text="two\n"):
        for i in range(n):
            (self.other / "a.txt").write_text(f"{text}{i}\n")
            git(self.other, "commit", "-q", "-am", f"new {i}")
        git(self.other, "push", "-q", "origin", "HEAD:main")
        return git(self.other, "rev-parse", "HEAD")


class PullTest(UpstreamCase):
    def test_pulls_new_commits(self):
        newest = self.push_upstream(2)
        before, after, count = updater.pull(str(self.clone), "main", ["github.com/a/b"])
        self.assertEqual((before, after, count), (self.start, newest, 2))
        self.assertEqual(git(self.clone, "rev-parse", "HEAD"), newest)

    def test_nothing_new(self):
        self.assertEqual(updater.pull(str(self.clone), "main", []), (self.start, self.start, 0))

    def test_your_own_commits_are_never_combined(self):
        self.push_upstream()
        (self.clone / "b.txt").write_text("mine\n")
        git(self.clone, "add", ".")
        git(self.clone, "commit", "-q", "-m", "mine")
        mine = git(self.clone, "rev-parse", "HEAD")
        with self.assertRaisesRegex(updater.UpdateError, "commits of its own"):
            updater.pull(str(self.clone), "main", [])
        self.assertEqual(git(self.clone, "rev-parse", "HEAD"), mine)  # untouched

    def test_your_changed_files_are_never_overwritten(self):
        self.push_upstream()
        (self.clone / "a.txt").write_text("edited by you\n")
        with self.assertRaisesRegex(updater.UpdateError, "Commit or stash"):
            updater.pull(str(self.clone), "main", [])
        self.assertEqual((self.clone / "a.txt").read_text(), "edited by you\n")
        self.assertEqual(git(self.clone, "rev-parse", "HEAD"), self.start)

    def test_a_clone_on_another_branch_is_left_alone(self):
        self.push_upstream()
        git(self.clone, "switch", "-q", "-c", "mine")
        with self.assertRaisesRegex(updater.UpdateError, "on mine, not main"):
            updater.pull(str(self.clone), "main", [])
        self.assertEqual(git(self.clone, "rev-parse", "HEAD"), self.start)

    @unittest.skipIf(os.geteuid() == 0, "root can write anywhere")
    def test_a_read_only_clone_of_yours_is_left_alone(self):
        os.chmod(self.clone / ".git", 0o555)
        with self.assertRaisesRegex(updater.UpdateError, "permissions"):
            updater.pull(str(self.clone), "main", [])

    def test_someone_elses_clone_is_left_alone(self):
        self.as_owner(1234)
        with self.assertRaisesRegex(updater.UpdateError, "As that user.*git pull --ff-only"):
            updater.pull(str(self.clone), "main", [])

    def test_the_systems_clone_asks_for_the_password_once(self):
        newest = self.push_upstream()
        asked = self.as_owner(0)
        self.assertEqual(updater.pull(str(self.clone), "main", [])[1:], (newest, 1))
        self.assertEqual(len(asked), 1)  # fetch and fast-forward in one go
        self.assertIn("merge --ff-only", asked[0])

    def test_no_password_no_change(self):
        self.push_upstream()
        self.as_owner(0, root=["sh", "-c", "exit 126", "polkit"])  # the password dialog was cancelled
        with self.assertRaisesRegex(updater.UpdateError, "password wasn\u2019t given"):
            updater.pull(str(self.clone), "main", [])
        self.assertEqual(git(self.clone, "rev-parse", "HEAD"), self.start)

    def as_owner(self, uid, root=None):
        """Pretend the clone belongs to `uid` and can't be written as you. Returns the requests that would ask for the
        password, one per update."""
        asked = []
        saved = updater._writable, updater._owner, updater.ROOT
        updater._writable, updater._owner = (lambda path: False), (lambda path: uid)
        updater.ROOT = root or ["env"]  # runs the commands as you, where pkexec would ask for the password
        self.addCleanup(lambda: (setattr(updater, "_writable", saved[0]), setattr(updater, "_owner", saved[1]),
                                 setattr(updater, "ROOT", saved[2])))
        real_run = updater._run_steps

        def run(path, steps, as_root):
            if as_root:
                asked.append(" ".join(" ".join(step) for step in steps))
            return real_run(path, steps, as_root)

        updater._run_steps = run
        self.addCleanup(setattr, updater, "_run_steps", real_run)
        return asked

    def test_follows_releases(self):
        # The project's releases are tags; your clone is on main, at v1.
        git(self.other, "tag", "v1")
        newest = self.push_upstream()
        git(self.other, "tag", "v2")
        git(self.other, "push", "-q", "origin", "v1", "v2")
        git(self.clone, "fetch", "-q", "--tags")
        from repoproject import scan

        self.assertEqual(scan.version_on_disk(str(self.clone), releases=True), ("v1", True))
        self.assertEqual(updater.checkout_release(str(self.clone), "v2", []), (self.start, "main"))
        self.assertEqual(git(self.clone, "rev-parse", "HEAD"), newest)
        self.assertEqual(scan.version_on_disk(str(self.clone), releases=True), ("v2", True))
        self.assertEqual(git(self.clone, "rev-parse", "main"), self.start)  # your branch is as it was

    def test_moving_to_a_release_never_strands_your_commits(self):
        git(self.other, "tag", "v2")
        git(self.other, "push", "-q", "origin", "v2")
        git(self.clone, "switch", "-q", "--detach")
        (self.clone / "b.txt").write_text("mine\n")
        git(self.clone, "add", ".")
        git(self.clone, "commit", "-q", "-m", "mine, on no branch")
        mine = git(self.clone, "rev-parse", "HEAD")
        with self.assertRaisesRegex(updater.UpdateError, "aren\u2019t on any branch"):
            updater.checkout_release(str(self.clone), "v2", [])
        self.assertEqual(git(self.clone, "rev-parse", "HEAD"), mine)

    def test_the_remote_matching_the_project_is_used(self):
        # The clone's "origin" is someone's fork; the tracked project is another remote.
        newest = self.push_upstream()
        git(self.clone, "remote", "rename", "origin", "project")
        git(self.clone, "remote", "add", "origin", "https://github.com/someone/fork.git")
        git(self.clone, "remote", "set-url", "project", str(self.upstream))
        self.assertEqual(updater._remote_for(str(self.clone), ["github.com/x/y"]), "origin")
        git(self.clone, "remote", "add", "named", "https://github.com/X/Y.git")
        self.assertEqual(updater._remote_for(str(self.clone), ["github.com/x/y"]), "named")
        git(self.clone, "remote", "remove", "named")
        # (Pulling through "project" by hand-picked name, as a scan would have matched it by its address.)
        git(self.clone, "remote", "rename", "origin", "fork")
        git(self.clone, "remote", "rename", "project", "origin")
        self.assertEqual(updater.pull(str(self.clone), "main", ["github.com/x/y"])[1], newest)


class InstallScriptTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = self.dir.name

    def tearDown(self):
        self.dir.cleanup()

    def test_found_by_name_and_uninstall_isnt_offered(self):
        for name in ("install.sh", "uninstall.sh", "setup.sh", "README.md"):
            Path(self.path, name).write_text("#!/bin/bash\necho hi\n")
        self.assertEqual(updater.install_scripts(self.path), ["install.sh", "setup.sh"])
        self.assertEqual(updater.script_text(self.path, "install.sh"), "#!/bin/bash\necho hi\n")
        with self.assertRaises(updater.UpdateError):
            updater.script_text(self.path, "uninstall.sh")
        with self.assertRaises(updater.UpdateError):
            updater.script_text(self.path, "../../etc/passwd")

    def test_huge_files_arent_offered(self):
        Path(self.path, "install.sh").write_text("x" * (updater.SCRIPT_MAX_BYTES + 1))
        self.assertEqual(updater.install_scripts(self.path), [])

    def test_runs_as_its_first_line_says_from_its_folder_and_stays_open(self):
        script = Path(self.path, "install.sh")
        script.write_text("#!/usr/bin/env bash\necho hi\n")
        program, args = updater.terminal_command(self.path, "install.sh")
        if Path(program).name == "konsole":
            self.assertEqual(args, ["--workdir", self.path, "--hold", "-e", "/usr/bin/env", "bash", "./install.sh"])
        script.chmod(0o755)
        self.assertEqual(updater._interpreter(script), ["./install.sh"])
        script.chmod(0o644)
        script.write_text("echo no first line\n")
        self.assertEqual(updater._interpreter(script), ["sh", "./install.sh"])


if __name__ == "__main__":
    unittest.main()


class UpdateClickedTest(UpstreamCase):
    """Update clicked in the window, for a scanned clone that's behind."""

    def setUp(self):
        super().setUp()
        from repoproject import checker, config, sources
        from repoproject.backend import Backend, Details

        self.checker, self.config = checker, config
        self.path = Path(self.dir.name) / "repos.toml"
        self.id = "github.com/a/project"
        config.save(config.Config(repos=[config.TrackedRepo(
            id=self.id, name="Project", url="", host="github", follow="branch", branch="main", kind="git",
            source="scanned", local_path=str(self.clone), installed=self.start)]), self.path)
        self.backend = Backend(self.path)
        self.backend._run = lambda work, done: done(*self._attempt(work))
        self.newest = self.push_upstream()
        self.backend._details[self.id] = Details(state="ready", default_branch="main",
                                                 branches=[sources.Branch("main", self.newest)],
                                                 comparison=sources.Comparison(sources.BEHIND, 1, []),
                                                 commits_base=self.start, commits_head=self.newest)
        self.backend._checks.results[self.id] = checker.Result(checker.UPDATE, "Update available", self.newest)
        # Nothing here may ask the site.
        self.saved = sources.http_get_json
        sources.http_get_json = lambda *a, **k: self.fail("asked the site")

    def tearDown(self):
        from repoproject import sources

        sources.http_get_json = self.saved
        self.backend.shutdown()
        super().tearDown()

    @staticmethod
    def _attempt(work):
        try:
            return work(), None
        except Exception as e:  # noqa: BLE001
            return None, e

    def test_update_pulls_and_everything_follows(self):
        self.assertTrue(self.backend.details(self.id)["canUpdate"])
        self.backend.updateRepo(self.id)
        d = self.backend.details(self.id)
        self.assertEqual(self.config.load(self.path).repos[0].installed, self.newest)
        self.assertEqual((d["statusKind"], d["updateNote"]), ("current", "Pulled 1 new commit."))
        self.assertEqual(self.backend._checks.results[self.id].status, self.checker.UP_TO_DATE)
        self.assertFalse(self.backend.repo(self.id)["updateAvailable"])

    def test_refresh_or_a_check_clears_the_note(self):
        from repoproject import sources

        self.backend.updateRepo(self.id)
        self.assertEqual(self.backend.details(self.id)["updateNote"], "Pulled 1 new commit.")
        saved = sources.releases, sources.branches
        sources.releases, sources.branches = (lambda ref, host: []), (lambda ref: ("main", []))
        self.addCleanup(lambda: (setattr(sources, "releases", saved[0]), setattr(sources, "branches", saved[1])))
        self.backend.loadDetails(self.id, True)  # Refresh on the repo page
        self.assertEqual(self.backend.details(self.id)["updateNote"], "")
        self.backend._update_notes[self.id] = ("done", "Pulled 1 new commit.")
        saved_check = self.checker.check_all
        self.checker.check_all = lambda repos, previous: (self.checker.State(), [])
        self.addCleanup(setattr, self.checker, "check_all", saved_check)
        self.backend.checkNow()  # Check Now, in the list
        self.assertEqual(self.backend.details(self.id)["updateNote"], "")

    def test_a_refused_update_says_why_and_changes_nothing(self):
        (self.clone / "a.txt").write_text("edited by you\n")
        self.backend.updateRepo(self.id)
        d = self.backend.details(self.id)
        self.assertEqual(d["updateNoteKind"], "error")
        self.assertIn("Commit or stash", d["updateNote"])
        self.assertEqual(self.config.load(self.path).repos[0].installed, self.start)
        self.assertTrue(self.backend.repo(self.id)["updateAvailable"])

    def test_a_clone_following_releases_moves_to_the_newest(self):
        from repoproject import sources

        git(self.other, "tag", "v2")
        git(self.other, "push", "-q", "origin", "v2")
        repo = self.backend._config.find(self.id)
        repo.follow, repo.installed = "releases", self.start
        d = self.backend._details[self.id]
        d.releases = [sources.Release("v2", "v2", None, False, "", "", [])]
        self.backend.updateRepo(self.id)
        d = self.backend.details(self.id)
        self.assertEqual(git(self.clone, "rev-parse", "HEAD"), self.newest)
        self.assertEqual(self.config.load(self.path).repos[0].installed, "v2")
        self.assertEqual(d["statusKind"], "current")
        self.assertEqual(d["updateNote"], "Now at v2. Your branch main is unchanged; git switch main goes back to it.")

    def test_only_clones_found_by_a_scan(self):
        repo = self.backend._config.find(self.id)
        repo.source = "manual"
        self.assertFalse(self.backend.repo(self.id)["canUpdate"])
        self.backend.updateRepo(self.id)
        self.assertEqual(git(self.clone, "rev-parse", "HEAD"), self.start)


class CloneTest(UpstreamCase):
    """Install for a project you don't have, added by hand and followed by branch or version: it's cloned."""

    def setUp(self):
        super().setUp()
        root = Path(self.dir.name)
        os.environ["REPOPROJECT_CLONES"] = str(root / "src")
        self.addCleanup(os.environ.pop, "REPOPROJECT_CLONES", None)
        # The project's address leads to the local upstream, as if it were on GitHub.
        for key, value in (("GIT_CONFIG_COUNT", "1"), ("GIT_CONFIG_KEY_0", f"url.{self.upstream}.insteadOf"),
                           ("GIT_CONFIG_VALUE_0", "https://github.com/a/project.git")):
            self.addCleanup(lambda k=key, v=os.environ.get(key): os.environ.pop(k) if v is None
                            else os.environ.__setitem__(k, v))
            os.environ[key] = value

    def backend(self, follow="branch", kind=""):
        from repoproject import config, sources
        from repoproject.backend import Backend, Details

        path = Path(self.dir.name) / "repos.toml"
        self.id = "github.com/a/project"
        config.save(config.Config(repos=[config.TrackedRepo(
            id=self.id, name="Project", url="", host="github", follow=follow, kind=kind, installed="-")]), path)
        backend = Backend(path)
        self.addCleanup(backend.shutdown)
        backend._run = lambda work, done: done(*UpdateClickedTest._attempt(work))
        head = git(self.other, "rev-parse", "HEAD")
        backend._details[self.id] = Details(state="ready", default_branch="main",
                                            branches=[sources.Branch("main", head)],
                                            releases=[sources.Release("v1", "v1", None, False, "", "", [])])
        return backend, path

    def test_clones_into_a_free_folder_and_a_failed_one_leaves_nothing(self):
        url = "https://github.com/a/project.git"
        first = updater.clone(url, "main", "project")
        self.assertEqual(first, Path(os.environ["REPOPROJECT_CLONES"]) / "project")
        self.assertEqual(git(first, "symbolic-ref", "--short", "HEAD"), "main")
        self.assertEqual(updater.clone(url, "main", "project").name, "project-2")
        with self.assertRaisesRegex(updater.UpdateError, "Couldn’t clone the project"):
            updater.clone(url, "no-such-branch", "project")
        self.assertEqual(sorted(p.name for p in first.parent.iterdir()), ["project", "project-2"])

    def test_install_clones_the_branch_and_it_becomes_a_clone(self):
        (self.other / "install.sh").write_text("echo hi\n")
        git(self.other, "add", ".")
        git(self.other, "commit", "-q", "-m", "installer")
        git(self.other, "push", "-q", "origin", "HEAD:main")
        backend, path = self.backend()
        d = backend.details(self.id)
        self.assertTrue(d["canUpdate"] and d["installClones"])
        self.assertEqual(d["statusKind"], "notInstalled")
        backend.updateRepo(self.id)
        d = backend.details(self.id)
        folder = Path(os.environ["REPOPROJECT_CLONES"]) / "project"
        self.assertEqual(d["updateNote"], f"Cloned main into {folder}. To install it, run its install script (under "
                                          "Tracking).")
        self.assertEqual(d["statusKind"], "current")
        self.assertEqual(d["installScripts"], ["install.sh"])
        self.assertFalse(d["installClones"])
        self.assertTrue(d["isClone"])
        from repoproject import config

        saved = config.load(path).repos[0]
        self.assertEqual((saved.source, saved.local_path, saved.kind, saved.installed),
                         ("scanned", str(folder), "git", git(folder, "rev-parse", "HEAD")))

    def test_install_clones_the_newest_release(self):
        git(self.other, "tag", "v1")
        git(self.other, "push", "-q", "origin", "v1")
        self.push_upstream()  # newer than the release
        backend, path = self.backend(follow="releases", kind="versions")
        backend.updateRepo(self.id)
        d = backend.details(self.id)
        self.assertEqual(d["updateNoteKind"], "done", d["updateNote"])
        self.assertEqual(d["statusKind"], "current")
        folder = Path(os.environ["REPOPROJECT_CLONES"]) / "project"
        self.assertEqual(git(folder, "rev-parse", "HEAD"), self.start)
        from repoproject import scan

        self.assertEqual(scan.version_on_disk(str(folder), releases=True), ("v1", True))

    def test_only_when_you_dont_have_it(self):
        backend, _ = self.backend()
        backend._config.find(self.id).installed = "abc"
        self.assertFalse(backend.details(self.id)["canUpdate"])
        backend, _ = self.backend(follow="releases", kind="appimage")
        self.assertFalse(backend.details(self.id)["installClones"])
