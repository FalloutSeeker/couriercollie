import os
import tempfile
import unittest
from pathlib import Path

from couriercollie import applying


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
    """sudo in a step asks for the password in the desktop's own window: couriercollie never sees it."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        # Stand-ins for the system's sudo (says how it was run) and the desktop's password window.
        system = self.root / "system"
        system.mkdir()
        (system / "sudo").write_text('#!/bin/sh\necho "sudo $* | askpass: $SUDO_ASKPASS"\n')
        (system / "sudo").chmod(0o755)
        self.window = self.root / "ksshaskpass"
        self.window.write_text("#!/bin/sh\necho pw\n")
        self.window.chmod(0o755)
        self.saved = {k: os.environ.get(k) for k in ("PATH", "SSH_ASKPASS", "SUDO_ASKPASS")}
        os.environ["PATH"] = f"{system}{os.pathsep}{self.saved['PATH']}"
        os.environ.pop("SUDO_ASKPASS", None)
        os.environ["SSH_ASKPASS"] = str(self.window)  # as Plasma sets it

    def tearDown(self):
        for k, v in self.saved.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        self.dir.cleanup()

    def test_sudo_in_a_step_asks_in_the_desktops_window(self):
        asking = applying.password_window(self.root / "sudo")
        self.assertEqual(asking["SUDO_ASKPASS"], str(self.window))  # the desktop's own: not couriercollie's
        self.assertEqual(oct((self.root / "sudo").stat().st_mode & 0o777), "0o700")  # only you can read it
        out = []
        self.assertEqual(applying.run(self.dir.name, "sudo make install", out.append, lambda p: None, asking), 0)
        self.assertEqual(out, [f"sudo -A make install | askpass: {self.window}"])

    def test_without_one_the_terminal_instead(self):
        os.environ.pop("SSH_ASKPASS")
        saved = applying.ASKPASS
        applying.ASKPASS = ()
        self.addCleanup(setattr, applying, "ASKPASS", saved)
        self.assertEqual(applying.password_window(self.root / "sudo"), {})


class BuildFolderTest(unittest.TestCase):
    """A clone already built with CMake or Meson: "Rebuild and install it", as its build folder was set up."""

    def test_cmake_and_meson_folders(self):
        import json

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "build").mkdir()
            (root / "build/CMakeCache.txt").write_text(f"CMAKE_HOME_DIRECTORY:INTERNAL={root}\n"
                                                       "CMAKE_INSTALL_PREFIX:PATH=/usr\n")
            (root / "other-build").mkdir()  # a build of another project, kept here: not this one's
            (root / "other-build/CMakeCache.txt").write_text("CMAKE_HOME_DIRECTORY:INTERNAL=/elsewhere\n")
            (root / "_build/meson-info").mkdir(parents=True)
            (root / "_build/meson-info/intro-buildoptions.json").write_text(json.dumps(
                [{"name": "prefix", "value": str(root / "local")}]))
            (root / "local").mkdir()
            built = applying.builds(d)
            self.assertEqual([(b.tool, b.folder) for b in built], [("meson", "_build"), ("cmake", "build")])
            # /usr only root can write: sudo (which asks in the password window); your own prefix: no sudo.
            self.assertEqual([applying.build_command(b) for b in built],
                             ["meson compile -C _build && meson install -C _build",
                              "cmake --build build && sudo cmake --install build"])
            [s] = applying.suggestions(d, [], None, built)
            self.assertEqual(s.label, "Rebuild and install it")
            # A project with its own install script: that's its way (it may build more than this folder).
            (root / "install.sh").write_text("#!/bin/sh\n")
            self.assertEqual([x.label for x in applying.suggestions(d, ["install.sh"], None, built)], ["Run install.sh"])
            # Approving it covers what CMake and Meson read without being named.
            self.assertIn("CMakeLists.txt", applying._IMPLIED["cmake"])

    def test_install_scripts_naming_a_project(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "install.sh").write_text("git clone https://gitgud.io/aeroshell/smod.git smod\n")
            self.assertTrue(applying.scripts_name(d, ["gitgud.io/aeroshell/smod"]))
            self.assertFalse(applying.scripts_name(d, ["github.com/someone/else"]))
