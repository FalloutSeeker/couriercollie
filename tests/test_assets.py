import unittest

from couriercollie import assets
from couriercollie.assets import KIND_APPIMAGE, KIND_ARCH, KIND_DEB, KIND_FILE, KIND_OTHER, KIND_PROGRAM, KIND_RPM


class ClassifyTest(unittest.TestCase):
    def setUp(self):
        # A Fedora computer, whatever this one is.
        saved, assets.PACKAGE_TOOLS = assets.PACKAGE_TOOLS, {"dnf"}
        self.addCleanup(setattr, assets, "PACKAGE_TOOLS", saved)

    def check(self, name, kind, suits, url="", machine="x86_64"):
        info = assets.classify(name, url, machine)
        self.assertEqual((info.kind, info.suits), (kind, suits), name)
        return info

    def test_files_for_this_pc(self):
        self.check("LocalSend-1.18.2-linux-x86-64.AppImage", KIND_APPIMAGE, True)
        self.check("someapp-1.5.2.x86_64.rpm", KIND_RPM, True)
        self.check("someapp-1.5.2.noarch.rpm", KIND_RPM, True)
        self.check("eget-1.3.4-linux_amd64.tar.gz", KIND_PROGRAM, True)
        self.check("Single.AppImage", KIND_APPIMAGE, True)

    def test_files_for_other_systems(self):
        self.assertIn("Windows", self.check("LocalSend-1.18.2-windows-x86-64.exe", KIND_OTHER, False).note)
        self.check("LocalSend-1.18.2-linux-x86-64.deb", KIND_OTHER, False)
        self.check("LocalSend-1.18.2-android-arm64v8.apk", KIND_OTHER, False)
        self.assertIn("macOS", self.check("eget-1.3.4-darwin_amd64.tar.gz", KIND_PROGRAM, False).note)
        self.assertIn("arm64", self.check("LocalSend-1.18.2-linux-arm64.AppImage", KIND_APPIMAGE, False).note)
        self.check("eget-1.3.4-linux_386.tar.gz", KIND_PROGRAM, False)
        self.check("someapp-1.5.2.src.rpm", KIND_OTHER, False)
        self.check("checksums.sha256", KIND_OTHER, False)

    def test_package_files_suit_only_where_they_can_be_installed(self):
        def note(name):
            return self.check(name, KIND_OTHER, False).note

        # Fedora: RPMs; another distro's packages say why not.
        self.check("app-1.0.x86_64.rpm", KIND_RPM, True)
        self.assertEqual(note("app-1.0-1-x86_64.pkg.tar.zst"), "Arch package: not supported on your distro")
        self.assertEqual(note("app_1.0_amd64.deb"), "Debian package: not supported on your distro")
        self.assertEqual(note("app.flatpakref"), "Flatpak: install it with your software center instead")
        self.assertEqual(note("app-1.0-x86_64.flatpak"), "Flatpak: flatpak isn\u2019t installed")
        assets.PACKAGE_TOOLS = {"dnf", "flatpak"}
        self.check("app-1.0-x86_64.flatpak", assets.KIND_FLATPAK, True)  # a bundle: installed for you, with flatpak
        assets.PACKAGE_TOOLS = {"dnf"}
        assets.PACKAGE_TOOLS = {"pacman"}  # Arch
        self.assertEqual(note("app-1.0.x86_64.rpm"), "RPM: not supported on your distro")
        self.check("app-1.0-1-x86_64.pkg.tar.zst", KIND_ARCH, True)
        self.check("app-1.0-1-aarch64.pkg.tar.zst", KIND_ARCH, False)  # another processor
        self.check("app-1.0-linux-x86_64.tar.zst", KIND_PROGRAM, True)  # a plain archive is still a program
        assets.PACKAGE_TOOLS = {"apt"}  # Debian, Ubuntu
        self.check("app_1.0_amd64.deb", KIND_DEB, True)
        assets.PACKAGE_TOOLS = {"zypper"}  # openSUSE: RPMs too
        self.check("app-1.0.x86_64.rpm", KIND_RPM, True)

    def test_files_that_belong_to_another_systems_package(self):
        # Obtainium (an Android app) ships signature files next to each .apk; "x86_64" in the name mustn't count.
        self.assertIn("Android", self.check("app-x86_64-release.apk.idsig", KIND_OTHER, False).note)
        self.check("app-x86_64-release.apk.sha256.sig", KIND_OTHER, False)
        self.check("app-release.apk.idsig", KIND_OTHER, False)

    def test_windows_installers_and_screensavers(self):
        # Aerial ("Apple TV screen saver for Windows") names neither file after Windows.
        self.assertIn("Windows", self.check("Aerial.Setup.1.2.1.zip", KIND_OTHER, False).note)
        self.check("Aerial.v1.2.1.SCR.zip", KIND_OTHER, False)
        self.check("tool-setup-x64.zip", KIND_OTHER, False)
        # "setup" as part of a word, or in a Linux package, is fine.
        self.check("setuptools-helper-1.0-linux-x86_64.tar.gz", KIND_PROGRAM, True)
        self.check("app-setup-1.0.x86_64.rpm", KIND_RPM, True)

    def test_arm_computer(self):
        self.check("LocalSend-1.18.2-linux-arm64.AppImage", KIND_APPIMAGE, True, machine="aarch64")
        self.check("LocalSend-1.18.2-linux-x86-64.AppImage", KIND_APPIMAGE, False, machine="aarch64")

    def test_whole_words_only_for_systems(self):
        self.check("MyStudios-1.0-x86_64.AppImage", KIND_APPIMAGE, True)
        self.check("Darwinia-1.0-x86_64.AppImage", KIND_APPIMAGE, True)

    def test_gitlab_labels_fall_back_to_the_link(self):
        self.check("Linux (x86_64)", KIND_FILE, True, url="https://gitlab.com/v/v/-/jobs/1/artifacts/download")
        self.check("Windows (x86_64)", KIND_FILE, False, url="https://gitlab.com/v/v/-/jobs/2/artifacts/download")
        self.check("Download", KIND_FILE, False)
        self.check("Fedora package", KIND_RPM, True, url="https://example.org/files/app-2.0-1.x86_64.rpm?x=1")


class PatternTest(unittest.TestCase):
    def test_version_becomes_a_wildcard(self):
        pattern = assets.pattern_for("LocalSend-1.18.2-linux-x86-64.AppImage", "v1.18.2")
        self.assertEqual(pattern, "LocalSend-*-linux-x86-64.AppImage")
        self.assertTrue(assets.matches(pattern, "LocalSend-1.19.0-linux-x86-64.AppImage"))
        self.assertFalse(assets.matches(pattern, "LocalSend-1.19.0-linux-arm-64.AppImage"))

    def test_version_appearing_twice(self):
        pattern = assets.pattern_for("app-2.0/app-2.0-x86_64.rpm", "2.0")
        self.assertTrue(assets.matches(pattern, "app-2.1/app-2.1-x86_64.rpm"))

    def test_name_without_version_matches_itself_only(self):
        pattern = assets.pattern_for("Linux (x86_64)", "v0.18.0")
        self.assertTrue(assets.matches(pattern, "Linux (x86_64)"))
        self.assertFalse(assets.matches(pattern, "Linux (aarch64)"))

    def test_special_characters_are_literal(self):
        pattern = assets.pattern_for("app[beta]-1.0?.zip", "1.0")
        self.assertTrue(assets.matches(pattern, "app[beta]-1.1?.zip"))
        self.assertFalse(assets.matches(pattern, "appb-1.1x.zip"))

    def test_wildcard_only_matches_versions(self):
        # LocalSend ships the app and a command-line tool side by side; picking one must not follow the other.
        pattern = assets.pattern_for("LocalSend-1.18.2-linux-x86-64.tar.gz", "v1.18.2")
        self.assertTrue(assets.matches(pattern, "LocalSend-1.19.0-linux-x86-64.tar.gz"))
        self.assertFalse(assets.matches(pattern, "LocalSend-CLI-1.19.0-linux-x86-64.tar.gz"))
        rpm = assets.pattern_for("app-1.2-x86_64.rpm", "1.2")
        self.assertFalse(assets.matches(rpm, "app-1.3-debuginfo-x86_64.rpm"))

    def test_version_shapes(self):
        pattern = assets.pattern_for("app-1.2.0-x86_64.AppImage", "v1.2.0")
        for name in ["app-1.3.0-x86_64.AppImage", "app-2.0-rc1-x86_64.AppImage", "app-10.0.1+build5-x86_64.AppImage",
                     "app-2026-01-05-x86_64.AppImage"]:
            self.assertTrue(assets.matches(pattern, name), name)
        self.assertFalse(assets.matches(pattern, "app--x86_64.AppImage"))

    def test_tag_that_isnt_a_v_version(self):
        self.assertEqual(assets.version_of("v1.2"), "1.2")
        self.assertEqual(assets.version_of("release-2"), "2")
        self.assertEqual(assets.version_of("latest"), "")
        pattern = assets.pattern_for("tool-nightly-2026.01.zip", "nightly-2026.01")
        self.assertEqual(pattern, "tool-nightly-*.zip")
        self.assertTrue(assets.matches(pattern, "tool-nightly-2026.02.zip"))
        self.assertEqual(assets.pattern_for("tool.zip", "latest"), "tool.zip")

    def test_empty_pattern_matches_nothing(self):
        self.assertFalse(assets.matches("", "anything"))



class OtherProcessorsTest(unittest.TestCase):
    def test_less_common_processor_names_dont_suit_this_pc(self):
        for name in ("bottom_loongarch64-unknown-linux-gnu.tar.gz", "bottom_powerpc64le-unknown-linux-gnu.tar.gz",
                     "tool-linux-ppc64.tar.gz", "tool-linux-mips64el.tar.gz", "tool-linux-riscv64.tar.gz",
                     "tool-linux-sparc64.tar.gz"):
            self.assertFalse(assets.classify(name, machine="x86_64").suits, name)
        self.assertTrue(assets.classify("bottom_x86_64-unknown-linux-gnu.tar.gz", machine="x86_64").suits)


class PackagesTest(unittest.TestCase):
    def test_versions_and_places(self):
        from couriercollie import packages

        self.assertEqual(packages.upstream_version("1:2.3.4-1ubuntu2"), "2.3.4")  # epoch and Debian revision off
        self.assertEqual(packages.upstream_version("2.3.4-1"), "2.3.4")  # Arch's pkgrel off
        self.assertEqual(packages.upstream_version("2.3.4"), "2.3.4")
        place = packages.place(assets.KIND_DEB, "tool")
        self.assertEqual((place, packages.from_place(place)), ("Debian package “tool”", (assets.KIND_DEB, "tool")))
        self.assertIsNone(packages.from_place("/home/you/tool"))
        self.assertEqual(packages.A_LABEL[assets.KIND_RPM], "an RPM package")


class FlatpaksTest(unittest.TestCase):
    def test_bundles_and_places(self):
        import subprocess
        import tempfile
        from pathlib import Path

        from couriercollie import flatpaks

        with tempfile.TemporaryDirectory() as d:
            bundle = Path(d) / "tool.flatpak"
            bundle.write_bytes(b"\x00flatpak\x00" + b"app/org.example.Tool/x86_64/stable\x00" + b"\x01" * 100)
            self.assertEqual(flatpaks.bundle_app(bundle), ("org.example.Tool", "x86_64"))
            bundle.write_bytes(b"not a bundle")
            self.assertEqual(flatpaks.bundle_app(bundle), ("", ""))
        self.assertEqual(flatpaks.from_place(flatpaks.place("org.example.Tool")), ("org.example.Tool", "user"))
        self.assertEqual(flatpaks.from_place(flatpaks.place("org.example.Tool", "system")), ("org.example.Tool", "system"))
        self.assertEqual(flatpaks.from_place("/home/you/tool"), ("", ""))

        # Installed from a bundle: its origin has no address. From Flathub: it has one, so Flatpak updates it.
        answers = {
            "list": "org.example.Tool\ttool-origin\tuser\norg.flathub.App\tflathub\tsystem\n",
            "remotes --user": "tool-origin\t\n",
            "remotes --system": "flathub\thttps://dl.flathub.org/repo/\n",
        }

        def fake(*args, timeout=60):
            key = args[0] if args[0] == "list" else f"{args[0]} {args[1]}"
            return subprocess.CompletedProcess(args, 0, answers.get(key, ""), "")

        saved = flatpaks._flatpak
        flatpaks._flatpak = fake
        self.addCleanup(setattr, flatpaks, "_flatpak", saved)
        self.assertEqual(flatpaks.from_bundles(), [("org.example.Tool", "user")])


if __name__ == "__main__":
    unittest.main()
