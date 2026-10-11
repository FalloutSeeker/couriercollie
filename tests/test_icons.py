import io
import os
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from couriercollie import config, icons, sources
from couriercollie.backend import Backend
from couriercollie.config import TrackedRepo

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 32
SAMPLE_APPIMAGE = Path(__file__).resolve().parent.parent / ".uicheck/appimage-sample/LocalSend.AppImage"


class SitePictureTest(unittest.TestCase):
    """Which picture represents a project (sources.ProjectInfo.icon_url)."""

    def test_github_organizations_only(self):
        org = sources.parse_github_project({"full_name": "localsend/localsend", "name": "localsend",
                                            "owner": {"type": "Organization", "avatar_url": "https://a/u/1?v=4"}})
        person = sources.parse_github_project({"full_name": "ImranR98/Obtainium", "name": "Obtainium",
                                               "owner": {"type": "User", "avatar_url": "https://a/u/2?v=4"}})
        self.assertEqual((org.icon_url, person.icon_url), ("https://a/u/1?v=4", ""))

    def test_gitlab_project_then_group_never_a_person(self):
        def project(avatar, kind, namespace_avatar):
            return sources.parse_gitlab_project("gitgud.io", {
                "path_with_namespace": "g/p", "path": "p", "avatar_url": avatar,
                "namespace": {"kind": kind, "avatar_url": namespace_avatar}})

        self.assertEqual(project("https://gitgud.io/p.png", "group", "/g.png").icon_url, "https://gitgud.io/p.png")
        self.assertEqual(project(None, "group", "/uploads/frame.png").icon_url, "https://gitgud.io/uploads/frame.png")
        self.assertEqual(project(None, "user", "https://gravatar/x").icon_url, "")


class OnThisComputerTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        self.saved = (icons.APPLICATION_DIRS, icons.ICON_DIRS, os.environ.get("XDG_CACHE_HOME"))
        self.apps = self.root / "applications"
        self.apps.mkdir()
        theme = self.root / "icons"
        (theme / "hicolor/48x48/apps").mkdir(parents=True)
        (theme / "hicolor/48x48/apps/localsend.png").write_bytes(PNG)
        icons.APPLICATION_DIRS, icons.ICON_DIRS = (str(self.apps),), (str(theme),)
        os.environ["XDG_CACHE_HOME"] = str(self.root / "cache")

    def tearDown(self):
        icons.APPLICATION_DIRS, icons.ICON_DIRS, cache = self.saved
        if cache is None:
            os.environ.pop("XDG_CACHE_HOME", None)
        else:
            os.environ["XDG_CACHE_HOME"] = cache
        self.dir.cleanup()

    def entry(self, file_name, name, icon):
        (self.apps / file_name).write_text(f"[Desktop Entry]\nType=Application\nName={name}\nIcon={icon}\n")

    def test_installed_app_by_file_name_part_or_name(self):
        self.entry("org.localsend.localsend_app.desktop", "LocalSend", "localsend")
        self.assertEqual(icons.from_installed_app(["localsend"]), "theme:localsend")
        self.assertEqual(icons.from_installed_app(["LocalSend"]), "theme:localsend")

    def test_installed_app_icon_must_exist(self):
        self.entry("ghost.desktop", "Ghost", "no-such-icon")
        self.assertEqual(icons.from_installed_app(["ghost"]), "")
        picture = self.root / "pic.png"
        picture.write_bytes(PNG)
        self.entry("ghost.desktop", "Ghost", str(picture))
        self.assertEqual(icons.from_installed_app(["ghost"]), f"file:{picture}")

    def test_short_names_dont_match_by_chance(self):
        self.entry("obt.desktop", "obt", "localsend")
        self.assertEqual(icons.from_installed_app(["obt"]), "")

    def test_icon_file_in_a_clone(self):
        clone = self.root / "smod"
        (clone / ".git").mkdir(parents=True)
        (clone / "assets").mkdir()
        (clone / "assets/logo.png").write_bytes(PNG)
        icon = icons.on_this_computer("gitgud.io/aeroshell/smod", "SMOD", "smod", str(clone))
        self.assertTrue(icon.startswith("file:") and Path(icon[5:]).read_bytes() == PNG, icon)
        self.assertEqual(Path(icon[5:]).parent, icons.cache_dir())

    def test_not_a_picture_is_ignored(self):
        clone = self.root / "x"
        (clone / ".git").mkdir(parents=True)
        (clone / "icon.png").write_bytes(b"not really a png")
        self.assertEqual(icons.from_clone("github.com/a/x", clone, "x"), "")

    @unittest.skipUnless(SAMPLE_APPIMAGE.is_file() and icons.shutil.which("7z"), "needs the sample AppImage and 7z")
    def test_appimage_icon_read_without_running_it(self):
        icon = icons.from_appimage("github.com/localsend/localsend", SAMPLE_APPIMAGE)
        self.assertTrue(Path(icon[5:]).read_bytes().startswith(b"\x89PNG"), icon)


class DownloadTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.saved = (urllib.request.urlopen, os.environ.get("XDG_CACHE_HOME"))
        os.environ["XDG_CACHE_HOME"] = self.dir.name
        self.urls = []

    def tearDown(self):
        urllib.request.urlopen, cache = self.saved
        if cache is None:
            os.environ.pop("XDG_CACHE_HOME", None)
        else:
            os.environ["XDG_CACHE_HOME"] = cache
        self.dir.cleanup()

    def serve(self, body=PNG, content_type="image/png", error=None):
        from email.message import Message

        def fake(req, timeout=None):
            self.urls.append(req.full_url)
            if error:
                raise error
            msg = Message()
            msg["Content-Type"] = content_type
            resp = io.BytesIO(body)
            resp.headers = msg
            return resp

        urllib.request.urlopen = fake

    def test_picture_is_kept(self):
        self.serve()
        icon = icons.download("github.com/localsend/localsend", "https://avatars.githubusercontent.com/u/1?v=4")
        self.assertEqual(Path(icon[5:]).read_bytes(), PNG)
        self.assertEqual(self.urls, ["https://avatars.githubusercontent.com/u/1?v=4&s=128"])

    def test_not_a_picture(self):
        self.serve(b"<html>", "text/html")
        self.assertEqual(icons.download("a/b/c", "https://x/y"), "")
        self.serve(b"x" * (icons.MAX_BYTES + 10))
        self.assertEqual(icons.download("a/b/c", "https://x/y"), "")

    def test_site_says_no_vs_cant_be_reached(self):
        self.serve(error=urllib.error.HTTPError("https://x/y", 404, "Not Found", None, io.BytesIO()))
        self.assertEqual(icons.download("a/b/c", "https://x/y"), "")
        self.serve(error=urllib.error.URLError("offline"))
        with self.assertRaises(icons.Unreachable):
            icons.download("a/b/c", "https://x/y")


class OrderTest(unittest.TestCase):
    """On this computer, then the site, then none."""

    def setUp(self):
        self.saved = (icons.on_this_computer, icons.download, sources.project_info)

    def tearDown(self):
        icons.on_this_computer, icons.download, sources.project_info = self.saved

    def test_order(self):
        icons.on_this_computer = lambda *a: "theme:localsend"
        icons.download = lambda *a: self.fail("the site isn't asked when the computer has an icon")
        self.assertEqual(icons.resolve("github.com/localsend/localsend", "LocalSend", ""), "theme:localsend")
        icons.on_this_computer = lambda *a: ""
        icons.download = lambda repo_id, url: "file:/c/x.png" if url else ""
        self.assertEqual(icons.resolve("github.com/a/b", "B", "", icon_url="https://x/y.png"), "file:/c/x.png")
        self.assertEqual(icons.resolve("github.com/a/b", "B", "", icon_url=""), icons.NONE)

    def test_site_asked_only_if_its_answer_isnt_known(self):
        icons.on_this_computer = lambda *a: ""
        icons.download = lambda repo_id, url: ""
        asked = []
        sources.project_info = lambda ref: asked.append(ref) or sources.ProjectInfo(ref, "github", "b", "", "main")
        icons.resolve("github.com/a/b", "B", "", icon_url="")
        self.assertEqual(asked, [])
        icons.resolve("github.com/a/b", "B", "")
        self.assertEqual(len(asked), 1)

    def test_unreachable_site(self):
        icons.on_this_computer = lambda *a: ""

        def offline(ref):
            raise sources.SourceError("Couldn’t reach github.com.")

        sources.project_info = offline
        with self.assertRaises(icons.Unreachable):
            icons.resolve("github.com/a/b", "B", "")


class OnceTest(unittest.TestCase):
    """Icons are looked up once per repo, when it first shows; the result (even "none") is saved."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "repos.toml"
        config.save(config.Config(repos=[
            TrackedRepo(id="github.com/a/b", name="B", url="", host="github"),
            TrackedRepo(id="github.com/c/d", name="D", url="", host="github", icon="theme:already"),
        ]), self.path)
        self.backend = Backend(self.path, find_icons=True)
        self.backend._run = lambda work, done: self._finish(work, done)
        self.calls = []
        self.answer = "theme:found"
        self.saved = icons.resolve

        def resolve(repo_id, name, local_path, icon_url=None):
            self.calls.append(repo_id)
            if self.answer is None:
                raise icons.Unreachable("offline")
            return self.answer

        icons.resolve = resolve

    def _finish(self, work, done):
        try:
            result, error = work(), None
        except Exception as e:  # noqa: BLE001
            result, error = None, e
        done(result, error)

    def tearDown(self):
        icons.resolve = self.saved
        self.backend.shutdown()
        self.dir.cleanup()

    def test_once(self):
        self.backend.loadIcons()
        self.backend.loadIcons()
        self.assertEqual(self.calls, ["github.com/a/b"])
        self.assertEqual(config.load(self.path).find("github.com/a/b").icon, "theme:found")
        self.assertEqual(self.backend.repo("github.com/a/b")["icon"], "found")

    def test_nothing_found_is_saved_too(self):
        self.answer = icons.NONE
        self.backend.loadIcons()
        self.backend.loadIcons()
        self.assertEqual(self.calls, ["github.com/a/b"])
        self.assertEqual(self.backend.repo("github.com/a/b")["icon"], "package-x-generic")  # the default

    def test_unreachable_is_tried_again_next_time(self):
        self.answer = None
        self.backend.loadIcons()
        self.assertEqual(config.load(self.path).find("github.com/a/b").icon, "")
        self.answer = "theme:found"
        self.backend.loadIcons()
        self.assertEqual(self.calls, ["github.com/a/b", "github.com/a/b"])
        self.assertEqual(config.load(self.path).find("github.com/a/b").icon, "theme:found")

    def test_off_unless_turned_on(self):
        backend = Backend(self.path)
        backend.loadIcons()
        self.assertEqual(self.calls, [])
        backend.shutdown()

    def test_deleted_picture_falls_back_and_removing_cleans_up(self):
        old = os.environ.get("XDG_CACHE_HOME")
        os.environ["XDG_CACHE_HOME"] = self.dir.name
        try:
            picture = icons.cache_dir() / "x.png"
            picture.parent.mkdir(parents=True)
            picture.write_bytes(PNG)
            repo = self.backend._config.find("github.com/a/b")
            repo.icon = f"file:{picture}"
            self.assertEqual(self.backend.repo("github.com/a/b")["icon"], f"file://{picture}")
            self.backend.removeRepo("github.com/a/b")
            self.assertFalse(picture.exists())
            repo.icon = f"file:{picture}"  # a picture that's gone shows the default icon
            self.assertEqual(Backend._icon_source(repo), "package-x-generic")
        finally:
            if old is None:
                os.environ.pop("XDG_CACHE_HOME", None)
            else:
                os.environ["XDG_CACHE_HOME"] = old


if __name__ == "__main__":
    unittest.main()
