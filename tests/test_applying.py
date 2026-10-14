import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from couriercollie import applying


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
            # /usr only root can write: sudo (which asks in the password window); your own prefix: no sudo. (Run as
            # root, as in a container, /usr can be written: no sudo either.)
            sudo = "" if os.access("/usr", os.W_OK) else "sudo "
            self.assertEqual([applying.build_command(b) for b in built],
                             ["meson compile -C _build && meson install -C _build",
                              f"cmake --build build && {sudo}cmake --install build"])
            [s] = applying.suggestions(d, [], built)
            self.assertEqual(s.label, "Rebuild and install it")
            # A project with its own install script: that's its way (it may build more than this folder).
            (root / "install.sh").write_text("#!/bin/sh\n")
            self.assertEqual([x.label for x in applying.suggestions(d, ["install.sh"], built)], ["Run install.sh"])
            # Approving it covers what CMake and Meson read without being named.
            self.assertIn("CMakeLists.txt", applying._IMPLIED["cmake"])

    def test_install_scripts_naming_a_project(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "install.sh").write_text("git clone https://gitgud.io/aeroshell/smod.git smod\n")
            self.assertTrue(applying.scripts_name(d, ["gitgud.io/aeroshell/smod"]))
            self.assertFalse(applying.scripts_name(d, ["github.com/someone/else"]))


class CoveredTest(unittest.TestCase):
    """What approving a step covers: the script, and the scripts it runs or sources (however they're named)."""

    def test_scripts_it_runs_are_covered(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "scripts" / "lib").mkdir(parents=True)
            (root / "install.sh").write_text('#!/bin/sh\nDIR="$(dirname "$0")/scripts"\n. "$DIR/lib/common.sh"\n'
                                             'sh scripts/services.sh\ncat README.md\n')
            (root / "scripts" / "lib" / "common.sh").write_text("echo common\n")
            (root / "scripts" / "services.sh").write_text("#!/bin/sh\n./scripts/helper\n")
            (root / "scripts" / "helper").write_text("#!/bin/sh\necho hi\n")
            (root / "README.md").write_text("# not a script\n")
            subprocess.run(["git", "init", "-q", folder], check=True)
            subprocess.run(["git", "-C", folder, "add", "."], check=True)
            named = {str(f.relative_to(root.resolve())) for f in applying.named_files(folder, "/bin/sh ./install.sh")}
            self.assertEqual(named, {"install.sh", "scripts/lib/common.sh", "scripts/services.sh", "scripts/helper"})
            before = applying.fingerprint(folder, "/bin/sh ./install.sh")
            (root / "scripts" / "helper").write_text("#!/bin/sh\nrm -rf ~\n")  # a pulled change, two scripts down
            self.assertNotEqual(applying.fingerprint(folder, "/bin/sh ./install.sh"), before)

    def test_an_ending_shared_by_many_files_says_nothing(self):
        # "$BASE/common.sh" ends like 60 vendored files: none is taken, and they don't crowd out what's named.
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for i in range(60):
                (root / "vendor" / f"lib{i:02}").mkdir(parents=True)
                (root / "vendor" / f"lib{i:02}" / "common.sh").write_text("echo vendored\n")
            (root / "install.sh").write_text('#!/bin/sh\n. "$BASE/common.sh"\nsh install-services.sh\n')
            (root / "install-services.sh").write_text("#!/bin/sh\necho services\n")
            subprocess.run(["git", "init", "-q", folder], check=True)
            subprocess.run(["git", "-C", folder, "add", "."], check=True)
            named = {str(f.relative_to(root.resolve())) for f in applying.named_files(folder, "/bin/sh ./install.sh")}
            self.assertEqual(named, {"install.sh", "install-services.sh"})
