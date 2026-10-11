import hashlib
import http.server
import os
import tempfile
import threading
import unittest
from pathlib import Path

from couriercollie import assets, config, packages, sources, updater
from couriercollie.sources import Asset, Release

APP = b"\x7fELF\x02\x01\x01\x00AI\x02" + os.urandom(300_000)  # what an AppImage starts with, then anything
SHA = hashlib.sha256(APP).hexdigest()
NAME = "App-2.0-x86_64.AppImage"


class _Files(http.server.SimpleHTTPRequestHandler):
    files: dict[str, bytes] = {}

    def do_GET(self):
        body = self.files.get(self.path.lstrip("/"))
        if body is None:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class AppImageCase(unittest.TestCase):
    """A small local web server stands in for the project's release files."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        root = Path(self.dir.name)
        self.saved_env = {k: os.environ.get(k) for k in ("XDG_DATA_HOME", "COURIERCOLLIE_APPS", "XDG_CACHE_HOME")}
        os.environ.update(XDG_DATA_HOME=str(root / "data"), COURIERCOLLIE_APPS=str(root / "Applications"),
                          XDG_CACHE_HOME=str(root / "cache"))
        _Files.files = {NAME: APP, "SHA256SUMS": f"{'0' * 64}  other.AppImage\n{SHA}  {NAME}\n".encode(),
                        "not-an-app.AppImage": b"<html>sign in</html>", "wrong.sha256": f"{'1' * 64}\n".encode()}
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Files)
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}/"
        self.folder = root / "apps"
        self.folder.mkdir()

    def tearDown(self):
        self.server.shutdown()
        for k, v in self.saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.dir.cleanup()

    def asset(self, name=NAME, digest=f"sha256:{SHA}", path=None):
        return Asset(name, self.url + (path or name), len(_Files.files.get(path or name, b"")), digest)


class InstallTest(AppImageCase):
    def test_update_swaps_in_the_new_file_then_removes_the_old(self):
        old = self.folder / "App-1.0-x86_64.AppImage"
        old.write_bytes(b"old version")
        seen = []
        new, verified = updater.install_appimage(self.asset(), [], self.folder, old,
                                                 progress=lambda done, total: seen.append((done, total)))
        self.assertEqual((new, verified), (self.folder / NAME, True))
        self.assertEqual(new.read_bytes(), APP)
        self.assertTrue(os.access(new, os.X_OK))
        self.assertFalse(old.exists())  # removed once the new one was in place
        self.assertEqual(seen[-1], (len(APP), len(APP)))
        self.assertEqual([p.name for p in self.folder.iterdir()], [NAME])  # no half-downloaded file left

    def test_a_checksum_file_in_the_release_is_used_when_the_site_gives_none(self):
        others = [self.asset("SHA256SUMS", digest="")]
        self.assertTrue(updater.install_appimage(self.asset(digest=""), others, self.folder, None)[1])

    def test_a_download_that_doesnt_match_its_checksum_is_thrown_away(self):
        old = self.folder / "App-1.0-x86_64.AppImage"
        old.write_bytes(b"old version")
        others = [self.asset("App-2.0-x86_64.AppImage.sha256", digest="", path="wrong.sha256")]
        with self.assertRaisesRegex(updater.UpdateError, "doesn’t match the checksum"):
            updater.install_appimage(self.asset(digest=""), others, self.folder, old)
        self.assertEqual([p.name for p in self.folder.iterdir()], [old.name])  # yours untouched, nothing left over

    def test_something_thats_not_an_appimage_isnt_installed(self):
        with self.assertRaisesRegex(updater.UpdateError, "isn’t an AppImage"):
            updater.install_appimage(self.asset(NAME, "", "not-an-app.AppImage"), [], self.folder, None)
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_no_published_checksum_is_said_not_hidden(self):
        self.assertFalse(updater.install_appimage(self.asset(digest=""), [], self.folder, None)[1])

    def test_never_a_path_from_the_site(self):
        new, _ = updater.install_appimage(Asset("../../evil/" + NAME, self.url + NAME, len(APP), f"sha256:{SHA}"),
                                          [], self.folder, None)
        self.assertEqual(new, self.folder / NAME)

    def test_menu_entries_follow_the_new_file(self):
        menu = updater.menu_dir()
        menu.mkdir(parents=True)
        old, new = self.folder / "App-1.0.AppImage", self.folder / NAME
        (menu / "appimagekit-app.desktop").write_text(f"[Desktop Entry]\nName=App\nExec={old} %U\nTryExec={old}\n")
        (menu / "other.desktop").write_text("[Desktop Entry]\nExec=/usr/bin/other\n")
        self.assertEqual(updater.repoint_menu_entries(old, new), 1)
        self.assertIn(f"Exec={new} %U", (menu / "appimagekit-app.desktop").read_text())
        self.assertTrue(updater.menu_entry_for(new))
        entry = updater.write_menu_entry("github.com/a/app", "App", self.folder / "My $App.AppImage", "")
        text = entry.read_text()
        self.assertIn('Exec="' + str(self.folder) + '/My \\\\$App.AppImage" %U', text)
        self.assertIn("X-couriercollie-Repo=github.com/a/app", text)

    def test_a_name_cant_add_lines_to_the_menu_entry(self):
        entry = updater.write_menu_entry("github.com/a/app", "App\nExec=rm -rf ~", Path("/x/App.AppImage"), "")
        lines = entry.read_text().splitlines()
        self.assertIn("Name=App Exec=rm -rf ~", lines)
        self.assertEqual([line for line in lines if line.startswith("Exec=")], ['Exec="/x/App.AppImage" %U'])


class InstallClickedTest(AppImageCase):
    """Install / Update clicked in the window for a repo that follows an AppImage."""

    def setUp(self):
        super().setUp()
        from couriercollie.backend import Backend

        self.path = Path(self.dir.name) / "repos.toml"
        self.id = "github.com/a/app"
        config.save(config.Config(repos=[config.TrackedRepo(
            id=self.id, name="App", url="", host="github", asset_pattern="App-*-x86_64.AppImage", kind="AppImage",
            installed="-")]), self.path)
        self.backend = Backend(self.path)
        self.backend._run = lambda work, done: done(*self._attempt(work))
        release = Release("v2.0", "v2.0", None, False, "", "", [self.asset()])
        self.saved = sources.releases
        sources.releases = lambda ref, host, **_: [release]

    def tearDown(self):
        sources.releases = self.saved
        self.backend.shutdown()
        super().tearDown()

    @staticmethod
    def _attempt(work):
        try:
            return work(), None
        except Exception as e:  # noqa: BLE001
            return None, e

    def test_install_puts_it_in_applications_with_a_menu_entry(self):
        self.assertTrue(self.backend.repo(self.id)["canUpdate"])
        self.backend.updateRepo(self.id)
        repo = config.load(self.path).repos[0]
        app = updater.apps_dir() / NAME
        self.assertEqual((repo.installed, repo.local_path, repo.source), ("v2.0", str(app), "scanned"))
        self.assertTrue(app.is_file())
        self.assertTrue(updater.menu_entry_for(app))
        note = self.backend.details(self.id)
        self.assertEqual(note["updateNoteKind"], "done")
        self.assertIn("Installed v2.0", note["updateNote"])

    def test_a_failed_download_says_why(self):
        _Files.files.pop(NAME)
        self.backend.updateRepo(self.id)
        d = self.backend.details(self.id)
        self.assertEqual(d["updateNoteKind"], "error")
        self.assertIn("didn’t finish", d["updateNote"])
        self.assertEqual(config.load(self.path).repos[0].installed, "-")


def _archive(kind: str, files: dict[str, tuple[bytes, int]]) -> bytes:
    """A .tar.gz or .zip holding `files` ({path: (content, mode)})."""
    import io
    import tarfile
    import zipfile

    out = io.BytesIO()
    if kind == "zip":
        with zipfile.ZipFile(out, "w") as z:
            for path, (data, mode) in files.items():
                info = zipfile.ZipInfo(path)
                info.external_attr = mode << 16
                z.writestr(info, data)
    else:
        with tarfile.open(fileobj=out, mode="w:gz") as t:
            for path, (data, mode) in files.items():
                info = tarfile.TarInfo(path)
                info.size, info.mode = len(data), mode
                t.addfile(info, io.BytesIO(data))
    return out.getvalue()


ELF = b"\x7fELF" + b"\x00" * 60


class ProgramTest(AppImageCase):
    def setUp(self):
        super().setUp()
        os.environ["COURIERCOLLIE_BIN"] = str(Path(self.dir.name) / "bin")
        self.addCleanup(os.environ.pop, "COURIERCOLLIE_BIN", None)
        for version in ("1.0", "2.0"):
            files = {f"tool-{version}/tool": (ELF + version.encode(), 0o755),
                     f"tool-{version}/lib/libtool.so.1": (ELF, 0o755),  # a library, not the program
                     f"tool-{version}/README.md": (b"read me", 0o644)}
            _Files.files[f"tool-{version}.tar.gz"] = _archive("tar", files)
            _Files.files[f"tool-{version}.zip"] = _archive("zip", files)

    def install(self, tag, name, wanted="", hints=("tool",)):
        data = _Files.files[name]
        return updater.install_program("github.com/a/tool", tag, Asset(name, self.url + name, len(data),
                                       f"sha256:{hashlib.sha256(data).hexdigest()}"), [], wanted, list(hints))

    def test_installs_with_a_link_then_updates_removing_the_old_version(self):
        from couriercollie import scan

        link, verified, replaced = self.install("v1.0", "tool-1.0.tar.gz")
        self.assertEqual((link, verified, replaced), (updater.bin_dir() / "tool", True, False))
        self.assertEqual(link.read_bytes(), ELF + b"1.0")  # the link starts the program
        self.assertTrue((link.resolve().parent / "lib/libtool.so.1").is_file())  # with the files next to it
        self.assertEqual(scan.version_on_disk(str(link)), ("v1.0", True))
        link, _, replaced = self.install("v2.0", "tool-2.0.zip")
        self.assertTrue(replaced)
        self.assertEqual(link.read_bytes(), ELF + b"2.0")
        self.assertTrue(os.access(link, os.X_OK))  # a zip keeps the program runnable
        self.assertEqual(updater.program_version(link), "v2.0")
        folders = [p.name for p in (updater.programs_dir() / "github.com_a_tool").iterdir()]
        self.assertEqual(folders, ["v2.0"])  # the old version removed, nothing half-done left behind
        # The same version again (e.g. reinstalling a broken one): still exactly one, working.
        self.install("v2.0", "tool-2.0.tar.gz")
        self.assertEqual(link.read_bytes(), ELF + b"2.0")
        self.assertEqual([p.name for p in (updater.programs_dir() / "github.com_a_tool").iterdir()], ["v2.0"])

    def test_never_replaces_a_command_it_didnt_put_there(self):
        updater.bin_dir().mkdir(parents=True)
        (updater.bin_dir() / "tool").write_text("#!/bin/sh\necho mine\n")
        with self.assertRaisesRegex(updater.UpdateError, "wasn’t put there by couriercollie"):
            self.install("v1.0", "tool-1.0.tar.gz")
        self.assertEqual((updater.bin_dir() / "tool").read_text(), "#!/bin/sh\necho mine\n")

    def test_several_programs_are_asked_about(self):
        _Files.files["two.tar.gz"] = _archive("tar", {"a/alpha": (ELF, 0o755), "a/beta": (ELF, 0o755)})
        with self.assertRaises(updater.SeveralPrograms) as caught:
            self.install("v1", "two.tar.gz", hints=("gamma",))
        self.assertEqual(caught.exception.choices, ["alpha", "beta"])
        self.assertEqual(self.install("v1", "two.tar.gz", wanted="beta")[0], updater.bin_dir() / "beta")

    def test_an_archive_reaching_outside_its_folder_isnt_unpacked(self):
        _Files.files["evil.tar.gz"] = _archive("tar", {"../../escaped": (ELF, 0o755)})
        _Files.files["evil.zip"] = _archive("zip", {"../../escaped": (ELF, 0o755)})
        for name in ("evil.tar.gz", "evil.zip"):
            with self.assertRaisesRegex(updater.UpdateError, "outside|unsafe"):
                self.install("v1", name)
        self.assertFalse(any(Path(self.dir.name).rglob("escaped")))

    def test_no_program_inside(self):
        _Files.files["docs.tar.gz"] = _archive("tar", {"docs/README": (b"text", 0o644)})
        with self.assertRaisesRegex(updater.UpdateError, "no program for Linux"):
            self.install("v1", "docs.tar.gz")


class ProgramClickedTest(InstallClickedTest):
    """Install clicked for a repo that follows a program archive; one with several programs asks which."""

    def setUp(self):
        AppImageCase.setUp(self)
        from couriercollie.backend import Backend

        os.environ["COURIERCOLLIE_BIN"] = str(Path(self.dir.name) / "bin")
        self.addCleanup(os.environ.pop, "COURIERCOLLIE_BIN", None)
        _Files.files["pair-2.0.tar.gz"] = _archive("tar", {"pair/left": (ELF, 0o755), "pair/right": (ELF, 0o755)})
        self.path = Path(self.dir.name) / "repos.toml"
        self.id = "github.com/a/pair"
        config.save(config.Config(repos=[config.TrackedRepo(
            id=self.id, name="Pair", url="", host="github", asset_pattern="pair-*.tar.gz", kind="Program",
            installed="-")]), self.path)
        self.backend = Backend(self.path)
        self.backend._run = lambda work, done: done(*self._attempt(work))
        release = Release("v2.0", "v2.0", None, False, "", "", [Asset("pair-2.0.tar.gz", self.url + "pair-2.0.tar.gz")])
        self.saved = sources.releases
        sources.releases = lambda ref, host, **_: [release]

    def test_install_puts_it_in_applications_with_a_menu_entry(self):
        pass  # (an AppImage test; not for programs)

    def test_a_failed_download_says_why(self):
        pass

    def test_several_programs_ask_which_then_install(self):
        self.backend.updateRepo(self.id)
        d = self.backend.details(self.id)
        self.assertEqual((d["updateNoteKind"], d["programChoices"]), ("error", ["left", "right"]))
        self.backend.chooseProgram(self.id, "right")
        self.backend.updateRepo(self.id)
        d = self.backend.details(self.id)
        self.assertEqual(d["updateNoteKind"], "warning")  # no checksum published here: said so
        self.assertEqual((d["command"], config.load(self.path).repos[0].installed), ("right", "v2.0"))
        self.assertTrue((updater.bin_dir() / "right").is_symlink())
        self.assertEqual(config.load(self.path).repos[0].program, "right")


class RpmTest(AppImageCase):
    """Installing a release's .rpm with dnf. dnf (and the password) are stand-ins that note what they were asked;
    nothing is installed."""

    def setUp(self):
        super().setUp()
        self.rpm = packages.MAGIC[assets.KIND_RPM][0] + os.urandom(50_000)
        _Files.files["tool-2.0-1.x86_64.rpm"] = self.rpm
        self.asked = Path(self.dir.name) / "dnf-asked"
        fake_dnf = Path(self.dir.name) / "dnf"
        # Notes its arguments, and that the file was there to install; fails if told to by DNF_FAILS.
        fake_dnf.write_text('#!/bin/sh\nfor a in "$@"; do echo "$a"; done > "$ASKED"\n[ -f "$3" ] && echo exists >> "$ASKED"\n'
                            'if [ -n "$DNF_FAILS" ]; then echo "Error: $DNF_FAILS" >&2; exit 1; fi\n')
        fake_dnf.chmod(0o755)
        saved = updater.ROOT, dict(packages.INSTALL), packages.file_info, assets.PACKAGE_TOOLS
        updater.ROOT = ["env", f"ASKED={self.asked}"]
        packages.INSTALL["dnf"] = [str(fake_dnf), "install", "-y"]
        packages.file_info = lambda kind, path: ("tool", "2.0", "x86_64")
        assets.PACKAGE_TOOLS = {"dnf"}  # a Fedora computer, whatever this one is
        self.addCleanup(lambda: (setattr(updater, "ROOT", saved[0]), packages.INSTALL.update(saved[1]),
                                 setattr(packages, "file_info", saved[2]), setattr(assets, "PACKAGE_TOOLS", saved[3])))
        self.addCleanup(os.environ.pop, "DNF_FAILS", None)

    def asset(self, name="tool-2.0-1.x86_64.rpm", digest=None, path=None):
        data = _Files.files.get(path or name, b"")
        return Asset(name, self.url + (path or name), len(data),
                     f"sha256:{hashlib.sha256(data).hexdigest()}" if digest is None else digest)

    def test_installs_with_dnf_and_cleans_up(self):
        started = []
        result = updater.install_package(self.asset(), [], assets.KIND_RPM, "tool", installing=lambda: started.append(1))
        self.assertEqual((result, started), (("tool", "2.0", True, "dnf"), [1]))
        asked = self.asked.read_text().split()
        self.assertEqual(asked[:2], ["install", "-y"])
        self.assertTrue(asked[2].endswith("tool-2.0-1.x86_64.rpm") and asked[3] == "exists")
        self.assertEqual(list(updater.downloads_dir().iterdir()), [])  # the download is deleted

    def test_installs_a_copy_only_root_can_change(self):
        updater.install_package(self.asset(), [], assets.KIND_RPM, "tool")
        installed = Path(self.asked.read_text().split()[2])
        self.assertNotEqual(installed.parent, updater.downloads_dir())  # not the copy in your folder
        self.assertFalse(installed.parent.exists())  # and it's cleaned up

    def test_a_file_swapped_after_it_was_checked_isnt_installed(self):
        # Something running as you swaps the checked file just as dnf is asked for (here: the password prompt).
        updater.ROOT = ["sh", "-c", 'printf swapped > "$5"; exec "$@"', "polkit"]
        with self.assertRaisesRegex(updater.UpdateError, "changed after it was checked"):
            updater.install_package(self.asset(), [], assets.KIND_RPM, "tool")
        self.assertFalse(self.asked.exists())  # dnf was never asked

    def test_a_different_package_isnt_installed(self):
        with self.assertRaisesRegex(updater.UpdateError, "not “other” that you have"):
            updater.install_package(self.asset(), [], assets.KIND_RPM, "other")
        self.assertFalse(self.asked.exists())  # dnf was never asked

    def test_dnf_failing_says_why(self):
        os.environ["DNF_FAILS"] = "nothing provides libfoo.so.3"
        with self.assertRaisesRegex(updater.UpdateError, "dnf couldn’t install it: Error: nothing provides"):
            updater.install_package(self.asset(), [], assets.KIND_RPM)
        self.assertEqual(list(updater.downloads_dir().iterdir()), [])

    def test_no_password_nothing_installed(self):
        updater.ROOT = ["sh", "-c", "exit 126", "polkit"]
        with self.assertRaisesRegex(updater.UpdateError, "password wasn’t given"):
            updater.install_package(self.asset(), [], assets.KIND_RPM)

    def test_something_thats_not_an_rpm_isnt_installed(self):
        with self.assertRaisesRegex(updater.UpdateError, "isn’t an RPM package"):
            updater.install_package(self.asset("tool-2.0-1.x86_64.rpm", "", "not-an-app.AppImage"), [], assets.KIND_RPM)
        self.assertFalse(self.asked.exists())

    def test_install_clicked(self):
        from couriercollie.backend import Backend

        path = Path(self.dir.name) / "repos.toml"
        config.save(config.Config(repos=[config.TrackedRepo(
            id="github.com/a/tool", name="Tool", url="", host="github", asset_pattern="tool-*-1.x86_64.rpm",
            kind="RPM", installed="-")]), path)
        backend = Backend(path)
        self.addCleanup(backend.shutdown)
        backend._run = lambda work, done: done(*InstallClickedTest._attempt(work))
        release = Release("v2.0", "v2.0", None, False, "", "", [self.asset()])
        saved = sources.releases
        sources.releases = lambda ref, host, **_: [release]
        self.addCleanup(setattr, sources, "releases", saved)
        self.assertTrue(backend.details("github.com/a/tool")["updateNeedsPassword"])
        backend.updateRepo("github.com/a/tool")
        repo = config.load(path).repos[0]
        self.assertEqual((repo.installed, repo.local_path), ("v2.0", "RPM package “tool”"))
        self.assertIn("Installed v2.0 with dnf", backend.details("github.com/a/tool")["updateNote"])

    def test_a_scanned_rpm_must_stay_the_same_package(self):
        from couriercollie.backend import Backend

        path = Path(self.dir.name) / "repos.toml"
        config.save(config.Config(repos=[config.TrackedRepo(
            id="github.com/a/tool", name="Tool", url="", host="github", asset_pattern="tool-*-1.x86_64.rpm",
            kind="RPM", source="scanned", local_path="RPM package “other”", installed="v1.0")]), path)
        backend = Backend(path)
        self.addCleanup(backend.shutdown)
        backend._run = lambda work, done: done(*InstallClickedTest._attempt(work))
        release = Release("v2.0", "v2.0", None, False, "", "", [self.asset()])
        saved = sources.releases
        sources.releases = lambda ref, host, **_: [release]
        self.addCleanup(setattr, sources, "releases", saved)
        backend.updateRepo("github.com/a/tool")
        self.assertIn("not “other” that you have", backend.details("github.com/a/tool")["updateNote"])
        self.assertFalse(self.asked.exists())  # dnf was never asked


class NewCopyTest(unittest.TestCase):
    """An AppImage you have, added by hand: where your copy is isn't known, so the page offers Install (a new copy),
    and the list's one-click Update isn't offered, so a click can't quietly add a second copy."""

    def test_install_not_update(self):
        import tempfile

        from couriercollie.backend import Backend

        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "repos.toml"
            config.save(config.Config(repos=[config.TrackedRepo(
                id="github.com/a/app", name="App", url="", host="github", asset_pattern="App-*-x86_64.AppImage",
                kind="AppImage", installed="v1")]), path)
            backend = Backend(path)
            self.addCleanup(backend.shutdown)
            self.assertTrue(backend.details("github.com/a/app")["newCopy"])
            self.assertFalse(backend.repo("github.com/a/app")["canUpdate"])
            repo = backend._config.find("github.com/a/app")
            repo.source, repo.local_path = "scanned", str(Path(d) / "App-1-x86_64.AppImage")  # found: Update it is
            self.assertFalse(backend.details("github.com/a/app")["newCopy"])
            self.assertTrue(backend.repo("github.com/a/app")["canUpdate"])


if __name__ == "__main__":
    unittest.main()
