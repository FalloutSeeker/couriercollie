import os
import tempfile
import unittest
from pathlib import Path

from couriercollie import applying


class ReadmeStepsTest(unittest.TestCase):
    """The README's update steps, quoted on a clone's page: shown, never followed."""

    def steps(self, readme, name="README.md"):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / name).write_text(readme)
            return applying.readme_steps(folder)

    def test_a_section_about_updating(self):
        readme = ("# App\n\nIntro.\n\n## Install\n\nmake install\n\n## Updating\n\nPull, then:\n\n```sh\n"
                  "# not a heading\nmake install\n```\n\n### Notes\n\nKeep your config.\n\n## License\n\nMIT\n")
        self.assertEqual(self.steps(readme), "Pull, then:\n\n```sh\n# not a heading\nmake install\n```\n\n### Notes\n\n"
                                             "Keep your config.")

    def test_a_paragraph_that_starts_to_update(self):
        readme = "# App\n\nRun it with `npm start`.\n\nTo update: the update button in the header.\nOr git pull.\n\nMore.\n"
        self.assertEqual(self.steps(readme), "To update: the update button in the header.\nOr git pull.")
        self.assertEqual(self.steps("**To upgrade**, run ./upgrade.sh.\n"), "**To upgrade**, run ./upgrade.sh.")

    def test_none(self):
        self.assertEqual(self.steps("# App\n\nIt updates your files automatically.\n"), "")  # a mention isn't steps
        self.assertEqual(self.steps("# App\n\n## Updating\n\n## License\n"), "")  # an empty section
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(applying.readme_steps(folder), "")  # no README

    def test_long_steps_are_shortened_without_leaving_code_open(self):
        steps = self.steps("## Upgrade\n\n```\n" + "step\n" * 600 + "```\n")
        self.assertLessEqual(len(steps), applying.STEPS_MAX_CHARS + 10)
        self.assertEqual(steps.count("```") % 2, 0)
        self.assertTrue(steps.endswith("…"))


class ComposeTest(unittest.TestCase):
    """Containers running from a clone's compose files, told by the labels Compose puts on them."""

    def labels(self, working_dir, service, files="/c/docker-compose.yml,/c/deploy/compose.gpu.yml"):
        return {"com.docker.compose.project": "board", "com.docker.compose.project.working_dir": working_dir,
                "com.docker.compose.project.config_files": files, "com.docker.compose.service": service}

    def test_found_with_its_files_and_running_services(self):
        with tempfile.TemporaryDirectory() as folder:
            running = {"podman": [self.labels(folder, "nginx"), self.labels(folder, "app"),
                                  self.labels("/elsewhere", "db")], "docker": []}
            c = applying.running_compose(folder, containers=lambda engine: running[engine])
            self.assertEqual((c.project, c.files, c.services),
                             ("board", ["/c/docker-compose.yml", "/c/deploy/compose.gpu.yml"], ["app", "nginx"]))
            command = applying.compose_command(c)
            # Only the running services are rebuilt, with the same files: a profile that's off stays off.
            self.assertIn("/c/deploy/compose.gpu.yml", command)
            self.assertEqual(command[command.index("up"):], ["up", "-d", "--build", "--force-recreate", "app", "nginx"])
            self.assertEqual(command[command.index("-p"):command.index("-p") + 2], ["-p", "board"])

    def test_docker_when_podman_has_none(self):
        with tempfile.TemporaryDirectory() as folder:
            running = {"podman": [], "docker": [self.labels(folder, "web")]}
            c = applying.running_compose(folder, containers=lambda engine: running[engine])
            self.assertEqual((c.tool, c.services), (["docker", "compose"], ["web"]))

    def test_labels_from_any_docker_or_podman(self):
        # podman: an object; docker (any version): "a=1,b=2", as a string; anything else is skipped.
        output = ('{"com.docker.compose.service":"app"}\n"com.docker.compose.service=web,x=1"\n'
                  'json\n\n')
        self.assertEqual(applying.parse_labels(output),
                         [{"com.docker.compose.service": "app"}, {"com.docker.compose.service": "web", "x": "1"}])

    def test_the_older_standalone_docker_compose(self):
        import os

        with tempfile.TemporaryDirectory() as bin_dir:
            # A docker without the compose plugin, and the standalone docker-compose.
            (Path(bin_dir) / "docker").write_text("#!/bin/sh\nexit 1\n")
            (Path(bin_dir) / "docker-compose").write_text("#!/bin/sh\n")
            for name in ("docker", "docker-compose"):
                (Path(bin_dir) / name).chmod(0o755)
            saved = os.environ["PATH"]
            os.environ["PATH"] = bin_dir
            try:
                self.assertEqual(applying._docker_compose(), ["docker-compose"])
            finally:
                os.environ["PATH"] = saved

    def test_nothing_running_from_here(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertIsNone(applying.running_compose(folder, containers=lambda engine: [self.labels("/x", "a")]))


class RunTest(unittest.TestCase):
    def run_step(self, command, folder="."):
        output = []
        code = applying.run(folder, command, output.append, lambda process: None)
        return code, output

    def test_english_messages_so_a_password_prompt_is_told_on_any_system(self):
        import os

        saved = {k: os.environ.get(k) for k in ("LANG", "LANGUAGE", "LC_ALL")}
        os.environ.update(LANG="de_DE.UTF-8", LANGUAGE="de", LC_ALL="de_DE.UTF-8")
        try:
            self.assertEqual(self.run_step('echo "$LC_ALL [$LANGUAGE]"'), (0, ["C.UTF-8 []"]))
        finally:
            for k, v in saved.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        for said in ("sudo: a terminal is required to read the password; either use the -S option",
                     "doas: a tty is required", "sudo: a password is required",
                     "Error executing command as another user: No authentication agent found.",
                     "sudo: Authentication required but not attempted",  # sudo-rs, the password window closed
                     "sudo: A terminal is required to authenticate"):  # sudo-rs
            self.assertTrue(applying.asked_for_password(["building…", said]), said)
        self.assertFalse(applying.asked_for_password(["error: disk full"]))

    def test_to_paste_into_a_terminal(self):
        self.assertEqual(applying.terminal_line("/home/u/my apps/board", "make install"),
                         "cd '/home/u/my apps/board' && make install")


if __name__ == "__main__":
    unittest.main()


class PasswordWindowTest(unittest.TestCase):
    """sudo in a step asks for the password in couriercollie's own window (there's no terminal to type it in)."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        # A stand-in for the system's sudo: says how it was run, and whether a password helper was given.
        system = self.root / "system"
        system.mkdir()
        (system / "sudo").write_text('#!/bin/sh\necho "sudo $* | askpass: $SUDO_ASKPASS | for: $COURIERCOLLIE_STEP"\n')
        (system / "sudo").chmod(0o755)
        self.saved = os.environ["PATH"]
        os.environ["PATH"] = f"{system}{os.pathsep}{self.saved}"

    def tearDown(self):
        os.environ["PATH"] = self.saved
        self.dir.cleanup()

    def test_sudo_in_a_step_asks_through_the_window(self):
        asking = applying.password_window("/usr/bin/couriercollie", self.root / "askpass")
        folder = self.root / "askpass"
        self.assertEqual(oct(folder.stat().st_mode & 0o777), "0o700")  # only you can read it
        self.assertIn("/usr/bin/couriercollie --askpass", (folder / "askpass").read_text())
        out = []
        code = applying.run(self.dir.name, "sudo make install", out.append, lambda p: None,
                            {**asking, "COURIERCOLLIE_STEP": "SMOD"})
        self.assertEqual(code, 0)
        self.assertEqual(out, [f"sudo -A make install | askpass: {folder / 'askpass'} | for: SMOD"])

    def test_the_window(self):
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication

        from couriercollie import app as app_module

        qt = QApplication.instance() or QApplication([])
        os.environ["COURIERCOLLIE_STEP"] = "SMOD"
        self.addCleanup(os.environ.pop, "COURIERCOLLIE_STEP", None)
        seen = []

        def answer(text):
            dialog = qt.activeModalWidget()
            seen.append(dialog.labelText())
            if text is None:
                dialog.reject()
            else:
                dialog.setTextValue(text)
                dialog.accept()

        import contextlib
        import io

        for text, code, printed in (("pw", 0, "pw\n"), (None, 1, "")):
            QTimer.singleShot(300, lambda t=text: answer(t))
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(app_module.askpass("[sudo] password for you: "), code)
            self.assertEqual(out.getvalue(), printed)
        self.assertIn("The step after updating SMOD asks for your password.", seen[0])
        self.assertIn("[sudo] password for you:", seen[0])
