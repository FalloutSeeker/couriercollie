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


class ReadmeSectionTest(unittest.TestCase):
    """The README's own steps, shown beside the step (applying.readme_section)."""

    def section(self, readme: str | None, clone: str = "clone", **files):
        with tempfile.TemporaryDirectory() as parent:
            folder = Path(parent) / clone
            folder.mkdir()
            if readme is not None:
                (folder / "README.md").write_text(readme)
            for name, text in files.items():
                (folder / name.replace("__", "/")).parent.mkdir(parents=True, exist_ok=True)
                (folder / name.replace("__", "/")).write_text(text)
            return applying.readme_section(str(folder))

    def test_updating_first_then_installing(self):
        readme = "# App\n\n## Installation\n\nRun ./install.sh\n\n## Updating\n\ngit pull, then ./install.sh\n\n## License\n\nMIT\n"
        self.assertEqual(self.section(readme), ("Updating", "git pull, then ./install.sh"))
        self.assertEqual(self.section(readme.replace("## Updating\n\ngit pull, then ./install.sh\n\n", "")),
                         ("Installation", "Run ./install.sh"))

    def test_up_to_the_next_heading_as_big(self):
        readme = "## Install\n\nStep one.\n\n### From source\n\n```sh\n# not a heading\nmake install\n```\n\n## Usage\n\nx\n"
        title, text = self.section(readme)
        self.assertEqual(title, "Install")
        self.assertIn("### From source", text)
        self.assertIn("make install", text)
        self.assertNotIn("Usage", text)

    def test_underlined_headings(self):
        self.assertEqual(self.section("App\n===\n\nInstall\n-------\n\nRun it.\n\nMore\n----\n\nx\n"),
                         ("Install", "Run it."))

    def test_badges_and_pictures_are_not_its_words(self):
        # A badge saying "Build" doesn't make a heading about building; a section's badges and comments don't show.
        readme = ("# tool [![Build Status][badge]][link]\n\nA tool.\n\n## Installation\n\n<!-- comment -->\n"
                  "[![Packaging status](https://repology.org/x.svg)](https://repology.org)\n\nUse your package manager.\n")
        self.assertEqual(self.section(readme), ("Installation", "Use your package manager."))

    def test_a_readme_that_points_elsewhere_is_followed(self):
        readme = "# Theme\n\n## Installation\n\nSee [INSTALL.md](./INSTALL.md) for a detailed guide.\n"
        install = "# Installation\n\n## Prerequisites\n\nx\n\n### Updating Theme\n\nRun git pull, then ./install.sh again.\n"
        self.assertEqual(self.section(readme, **{"INSTALL.md": install}),
                         ("INSTALL.md · Updating Theme", "Run git pull, then ./install.sh again."))

    def test_without_steps_the_usual_files(self):
        self.assertEqual(self.section("# Thing\n\nIt does things.\n", **{"docs__INSTALL.md": "## Build\n\nmake\n"}),
                         ("docs/INSTALL.md · Build", "make"))

    def test_never_outside_the_clone(self):
        readme = "## Install\n\nSee [the guide](../../../etc/passwd.md).\n"
        self.assertEqual(self.section(readme)[0], "Install")

    def test_none(self):
        self.assertEqual(self.section("# Thing\n\nIt does things.\n"), ("", ""))

    def test_long_sections_are_shortened_without_an_open_code_block(self):
        title, text = self.section("## Install\n\n```sh\n" + "echo step\n" * 600 + "```\n")
        self.assertLessEqual(len(text), applying.SECTION_MAX_CHARS + 10)
        self.assertEqual(sum(1 for line in text.splitlines() if line.startswith("```")) % 2, 0)

    def test_restructuredtext_and_docs_readme(self):
        readme = "Thing\n=====\n\nInstall\n-------\n\nRun ``make install``.\n\nUsage\n-----\n\nx\n"
        self.assertEqual(self.section(None, **{"README.rst": readme}), ("Install", "Run ``make install``."))
        self.assertEqual(self.section(None, **{"docs__README.md": "## Install\n\nmake\n"}), ("Install", "make"))

    def test_more_files_of_steps(self):
        # BUILDING.md and the like; one whose headings don't say (a plain INSTALL) shows from its beginning: not a script.
        self.assertEqual(self.section("# Thing\n", **{"BUILDING.md": "# Building\n\nmake\n"}),
                         ("BUILDING.md · Building", "make"))
        self.assertEqual(self.section("# Thing\n", INSTALL="Normally just run make.\n"),
                         ("INSTALL", "Normally just run make."))
        self.assertEqual(self.section("# Thing\n", INSTALL="#!/bin/sh\nmake install\n"), ("", ""))

    def test_headings_that_only_seem_about_it(self):
        # The README's title, part of a hyphenated word, news of an update or a migration from an old version.
        readme = ("# Luke's build of dwm\n\nA window manager.\n\n## Post-update hooks\n\nx\n\n## Update notes\n\nx\n\n"
                  "## Upgrading from v1\n\nx\n\n## Installation\n\nmake install\n")
        self.assertEqual(self.section(readme), ("Installation", "make install"))

    def test_installing_before_getting_started_usage_and_what_it_needs(self):
        readme = ("## Getting started\n\nPress q to quit.\n\n## Install dependencies\n\nmeson, ninja\n\n"
                  "## Requirements\n\n### Building\n\ngcc\n\n## Installation\n\nmeson setup build\n")
        self.assertEqual(self.section(readme), ("Installation", "meson setup build"))
        self.assertEqual(self.section(readme.replace("## Installation\n\nmeson setup build\n", ""))[0], "Getting started")
        theme = "# Theme\n\n## Previews\n\nx\n\n## Usage\n\n1. Copy the theme into ~/.themes\n"
        self.assertEqual(self.section(theme), ("Usage", "1. Copy the theme into ~/.themes"))
        self.assertEqual(self.section("## Usage\n\nRun it with --help.\n"), ("", ""))  # (not the steps to set it up)

    def test_from_the_clone_rather_than_packages(self):
        self.assertEqual(self.section("## Install from package\n\napt install x\n\n## Install from source\n\nmake\n"),
                         ("Install from source", "make"))
        # A wall of distro packages, too long to show: its part about the clone.
        packages = "".join(f"### Distro {n}\n\n```sh\nsudo pkg install thing\n```\n\n" for n in range(100))
        readme = f"## Installation\n\n{packages}### From source\n\n```sh\nmake install\n```\n\n## License\n\nMIT\n"
        self.assertEqual(self.section(readme), ("From source", "```sh\nmake install\n```"))

    def test_updating_something_else_isnt_the_steps(self):
        readme = "## Installation\n\nRun ./install.sh\n\n### Updating plugins\n\nfisher update\n"
        self.assertEqual(self.section(readme)[0], "Installation")
        # Unless it's just that word, or names the project (as its clone is named).
        self.assertEqual(self.section(readme.replace("Updating plugins", "Updating"))[0], "Updating")
        self.assertEqual(self.section(readme.replace("plugins", "Fisher"), clone="fisher")[0], "Updating Fisher")

    def test_a_paragraph_with_the_steps_it_announces(self):
        self.assertEqual(self.section("# Thing\n\nTo install, run:\n\n```sh\nmake install\n```\n\nEnjoy.\n"),
                         ("", "To install, run:\n\n```sh\nmake install\n```"))

    def test_a_link_to_a_website_gives_way_to_install_md(self):
        readme = "## Install\n\nAll instructions are at [the website](https://example.org/install).\n"
        self.assertEqual(self.section(readme, **{"INSTALL.md": "## Install manually\n\nCopy it to ~/.themes\n"}),
                         ("INSTALL.md · Install manually", "Copy it to ~/.themes"))
        self.assertEqual(self.section(readme)[0], "Install")

    def test_a_section_that_starts_by_pointing_elsewhere(self):
        readme = "## Installing\n\nSee [INSTALL.md](INSTALL.md).\n\n### Configuration\n\n" + "Set things.\n" * 50
        self.assertEqual(self.section(readme, **{"INSTALL.md": "# Installing\n\nmeson setup build\n"}),
                         ("INSTALL.md · Installing", "meson setup build"))
        # (to a file that isn't about the steps: not followed)
        self.assertEqual(self.section(readme.replace("INSTALL.md", "docs/options.md"),
                                      **{"docs__options.md": "# Options\n\nx\n"})[0], "Installing")


class ReadmeOutsideTest(unittest.TestCase):
    def test_a_readme_linked_outside_the_clone_isnt_read(self):
        with tempfile.TemporaryDirectory() as outside, tempfile.TemporaryDirectory() as folder:
            (Path(outside) / "secret.md").write_text("## Install\n\nthe secret\n")
            (Path(folder) / "README.md").symlink_to(Path(outside) / "secret.md")
            self.assertEqual(applying.readme_section(folder), ("", ""))


class CoveredFilesTest(unittest.TestCase):
    """What a step's approval covers, whatever kind of file the step uses (applying.named_files)."""

    def clone(self, files: dict[str, str | bytes]) -> str:
        folder = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, folder)
        for name, text in files.items():
            file = Path(folder) / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(text if isinstance(text, bytes) else text.encode())
        subprocess.run(["git", "init", "-q", folder], check=True)
        subprocess.run(["git", "-C", folder, "add", "."], check=True)
        return folder

    def covered(self, folder: str, command: str = "/bin/sh ./install.sh") -> set[str]:
        return {str(f.relative_to(Path(folder).resolve())) for f in applying.named_files(folder, command)}

    def test_sourced_and_run_files_of_any_kind(self):
        folder = self.clone({
            "install.sh": ". ./scripts/common\nsource build.conf\nbash ./tools/post\npython3 -m tools.inst\nmake -f rules.mk\n",
            "scripts/common": "echo common\n", "build.conf": "PREFIX=/usr\n", "tools/post": "echo post\n",
            "tools/inst.py": "print('inst')\n", "rules.mk": "include extra.mk\n", "extra.mk": "all:\n\techo\n"})
        self.assertEqual(self.covered(folder), {"install.sh", "scripts/common", "build.conf", "tools/post",
                                                "tools/inst.py", "rules.mk", "extra.mk"})

    def test_a_change_to_a_sourced_file_is_a_change_to_the_step(self):
        folder = self.clone({"install.sh": ". ./scripts/common\n", "scripts/common": "echo one\n"})
        before = applying.fingerprint(folder, "/bin/sh ./install.sh")
        (Path(folder) / "scripts/common").write_text("rm -rf ~\n")
        self.assertNotEqual(applying.fingerprint(folder, "/bin/sh ./install.sh"), before)

    def test_a_big_file_is_covered_and_said_to_be(self):
        folder = self.clone({"install.sh": "sh ./payload.sh\n", "payload.sh": b"#" * (applying.FILE_MAX_BYTES + 10)})
        self.assertIn("payload.sh", self.covered(folder))
        self.assertIn("too big to show here", applying.review_text(folder, "/bin/sh ./install.sh"))

    def test_not_documentation_pictures_or_untracked_files(self):
        folder = self.clone({"install.sh": "cat README.md docs/guide.md\ncp logo.png ~/\n./build/out\n",
                             "README.md": "x", "docs/guide.md": "x", "logo.png": b"\x89PNG"})
        (Path(folder) / "build").mkdir()
        (Path(folder) / "build/out").write_text("left by a build\n")  # (not tracked)
        self.assertEqual(self.covered(folder), {"install.sh"})

    def test_a_long_word_is_data_and_quick(self):
        import time

        folder = self.clone({"install.sh": "echo " + "ab" * 50_000 + "\n"})
        start = time.monotonic()
        self.assertEqual(self.covered(folder), {"install.sh"})
        self.assertLess(time.monotonic() - start, 2)


class MissingTest(unittest.TestCase):
    def test_the_scripts_a_command_runs_that_are_gone(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "setup.sh").write_text("echo\n")
            self.assertEqual(applying.missing(folder, "/bin/sh ./install.sh"), ["./install.sh"])
            self.assertEqual(applying.missing(folder, "sh ./setup.sh"), [])
