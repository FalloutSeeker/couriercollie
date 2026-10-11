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
    def test_a_clone_you_cant_write_says_how_to_do_it_yourself(self):
        os.chmod(self.clone / ".git", 0o555)
        with self.assertRaisesRegex(updater.UpdateError, "sudo git pull --ff-only"):
            updater.pull(str(self.clone), "main", [])

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

    def test_a_refused_update_says_why_and_changes_nothing(self):
        (self.clone / "a.txt").write_text("edited by you\n")
        self.backend.updateRepo(self.id)
        d = self.backend.details(self.id)
        self.assertEqual(d["updateNoteKind"], "error")
        self.assertIn("Commit or stash", d["updateNote"])
        self.assertEqual(self.config.load(self.path).repos[0].installed, self.start)
        self.assertTrue(self.backend.repo(self.id)["updateAvailable"])

    def test_only_scanned_clones_following_a_branch(self):
        repo = self.backend._config.find(self.id)
        repo.source = "manual"
        self.assertFalse(self.backend.repo(self.id)["canUpdate"])
        self.backend.updateRepo(self.id)
        self.assertEqual(git(self.clone, "rev-parse", "HEAD"), self.start)
