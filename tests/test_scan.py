import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from couriercollie import config, scan, sources
from couriercollie.config import Config, TrackedRepo
from couriercollie.scan import Found
from couriercollie.sources import ProjectInfo, RepoRef

AERO_NEW = "gitgud.io/aeroshell/atp/aerothemeplasma"
AERO_OLD = "gitgud.io/wackyideas/aerothemeplasma"


def aero_clone(repo_id=AERO_OLD, version="e4cca91b12dd9419485c19bece76534972324f6a"):
    return Found(id=repo_id, name="aerothemeplasma", url=f"https://{repo_id}", host="gitlab",
                 path="/home/me/aero/aerothemeplasma", kind="git", version=version, branch="Plasma/6.7")


class MergeTest(unittest.TestCase):
    """A scan must turn manual entries into scanned ones, never add them twice (DECISIONS.md, D12)."""

    def manual_aero(self, **kw):
        return TrackedRepo(id=AERO_NEW, name="Aero", url=f"https://{AERO_NEW}", host="gitlab", follow="branch",
                           branch="Plasma/6.7", kind="git", installed="f9eb10a" + "0" * 33, **kw)

    def test_new_find_is_added_as_scanned(self):
        cfg = Config()
        result = scan.merge(cfg, [aero_clone(AERO_NEW)])
        self.assertEqual(len(cfg.repos), 1)
        self.assertEqual(result.added, cfg.repos)
        repo = cfg.repos[0]
        self.assertEqual((repo.source, repo.local_path, repo.follow, repo.branch),
                         ("scanned", "/home/me/aero/aerothemeplasma", "branch", "Plasma/6.7"))
        self.assertTrue(repo.installed.startswith("e4cca91"))

    def test_manual_entry_becomes_scanned_not_duplicated(self):
        cfg = Config(repos=[self.manual_aero()])
        result = scan.merge(cfg, [aero_clone(AERO_NEW)])
        self.assertEqual(len(cfg.repos), 1)
        self.assertEqual(result.added, [])
        repo = cfg.repos[0]
        self.assertEqual(repo.source, "scanned")
        self.assertEqual(repo.name, "Aero")  # the name you gave it stays
        self.assertTrue(repo.installed.startswith("e4cca91"))  # the version on disk wins

    def test_a_clone_following_releases_stays_so_when_found_again(self):
        # Installed at a release's tag (Inkscape: INKSCAPE_1_4): a later scan used to switch it to following master.
        tracked = self.manual_aero(source="scanned", local_path="/home/me/aero/aerothemeplasma")
        tracked.follow, tracked.installed = "releases", "v6.7.0"
        cfg = Config(repos=[tracked])
        scan.merge(cfg, [aero_clone(AERO_NEW)])
        self.assertEqual((cfg.repos[0].follow, cfg.repos[0].installed), ("releases", "v6.7.0"))

    def test_clone_under_an_old_address_matches_a_remembered_alias(self):
        # Added by hand as the old address; the site redirected, so the old one was kept as an alias.
        cfg = Config(repos=[self.manual_aero(aliases=[AERO_OLD])])
        scan.merge(cfg, [aero_clone(AERO_OLD)], resolve=lambda _id: self.fail("shouldn’t need to ask the site"))
        self.assertEqual(len(cfg.repos), 1)
        self.assertEqual(cfg.repos[0].source, "scanned")

    def test_clone_under_an_old_address_asks_the_site_once(self):
        # Added by hand with the new address; the clone on disk still uses the old one.
        cfg = Config(repos=[self.manual_aero()])
        asked = []

        def resolve(repo_id):
            asked.append(repo_id)
            return AERO_NEW if repo_id == AERO_OLD else None

        scan.merge(cfg, [aero_clone(AERO_OLD)], resolve)
        self.assertEqual(len(cfg.repos), 1)
        self.assertEqual(cfg.repos[0].source, "scanned")
        self.assertEqual(cfg.repos[0].aliases, [AERO_OLD])
        # Next scan: matched straight away.
        scan.merge(cfg, [aero_clone(AERO_OLD)], resolve)
        self.assertEqual(asked, [AERO_OLD])
        self.assertEqual(len(cfg.repos), 1)

    def test_upper_and_lower_case_are_the_same_project(self):
        cfg = Config(repos=[TrackedRepo(id="github.com/ImranR98/Obtainium", name="obt", url="", host="github")])
        found = Found(id="github.com/imranr98/obtainium", name="Obtainium", url="", host="github",
                      path="/home/me/Obtainium", kind="git", version="abc")
        scan.merge(cfg, [found])
        self.assertEqual(len(cfg.repos), 1)

    def test_installed_from_the_app_then_scanned(self):
        # Installed from the app: the next scan finds it on disk and marks it as scanned, the same entry.
        cfg = Config(repos=[TrackedRepo(id="github.com/localsend/localsend", name="LocalSend", url="", host="github",
                                        asset_pattern="LocalSend-*-linux-x86-64.AppImage", kind="AppImage",
                                        installed="v1.18.2")])
        found = Found(id="github.com/localsend/localsend", name="LocalSend", url="", host="github",
                      path="/home/me/Applications/LocalSend-1.18.2-linux-x86-64.AppImage", kind="AppImage",
                      version="v1.18.2")
        scan.merge(cfg, [found])
        repo = cfg.repos[0]
        self.assertEqual((len(cfg.repos), repo.source, repo.follow, repo.asset_pattern),
                         (1, "scanned", "releases", "LocalSend-*-linux-x86-64.AppImage"))

    def test_same_project_found_twice_in_one_scan(self):
        cfg = Config()
        scan.merge(cfg, [aero_clone(AERO_NEW), aero_clone(AERO_NEW)])
        self.assertEqual(len(cfg.repos), 1)

    def test_scanned_entries_survive_saving(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "repos.toml"
            cfg = Config(repos=[self.manual_aero()])
            scan.merge(cfg, [aero_clone(AERO_OLD)], lambda _id: AERO_NEW)
            config.save(cfg, path)
            repo = config.load(path).repos[0]
            self.assertEqual((repo.source, repo.aliases), ("scanned", [AERO_OLD]))



def make_clone(folder: Path, remote: str | None, branch: str = "main") -> str:
    """A real git clone with one commit and an "origin" remote. Returns the commit."""
    folder.mkdir(parents=True)
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_GLOBAL": "/dev/null"}

    def git(*args):
        return subprocess.run(["git", "-C", str(folder), *args], check=True, capture_output=True, text=True,
                              env=env).stdout.strip()

    git("init", "-q", "-b", branch)
    git("commit", "-q", "--allow-empty", "-m", "first")
    if remote:
        git("remote", "add", "origin", remote)
    return git("rev-parse", "HEAD")


class FindOnDiskTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.home = Path(self.dir.name)

    def tearDown(self):
        self.dir.cleanup()

    def test_git_clones(self):
        commit = make_clone(self.home / "aero/aerothemeplasma", "https://gitgud.io/wackyideas/aerothemeplasma.git",
                            "Plasma/6.7")
        make_clone(self.home / "aero/aerothemeplasma/repos/smod", "git@gitgud.io:aeroshell/smod.git")
        make_clone(self.home / "notes", None)  # no remote: not from a site
        make_clone(self.home / "local-copy", "/srv/git/thing.git")  # a folder, not a project page
        make_clone(self.home / ".hidden/proj", "https://github.com/a/hidden")
        make_clone(self.home / "app/node_modules/dep", "https://github.com/a/dep")
        found = {f.id: f for f in scan.walk(scan.scan_roots([str(self.home)]))[0]}
        self.assertEqual(set(found), {"gitgud.io/wackyideas/aerothemeplasma", "gitgud.io/aeroshell/smod"})
        aero = found["gitgud.io/wackyideas/aerothemeplasma"]
        self.assertEqual((aero.kind, aero.branch, aero.version, aero.path),
                         ("git", "Plasma/6.7", commit, str(self.home / "aero/aerothemeplasma")))

    def test_depth_limit(self):
        make_clone(self.home / "a/b/c/d/e/f/g/deep", "https://github.com/a/deep")
        self.assertEqual(scan.walk(scan.scan_roots([str(self.home)]), max_depth=6)[0], [])
        self.assertEqual(len(scan.walk(scan.scan_roots([str(self.home)]), max_depth=8)[0]), 1)

    def test_rpms_a_repository_offers_are_left_to_dnf(self):
        installed = ("tool|1.0|@commandline|https://github.com/a/tool\n"
                     "self-repo|2.0|@commandline|https://github.com/b/self-repo\n"  # added its own repository
                     "fedora-thing|3.0|fedora|https://github.com/c/thing\n")
        asked = []

        def dnf(*args):
            asked.append(args)
            if "--installed" in args:
                return installed
            return "self-repo\n"  # the only one a repository offers

        self.assertEqual([f.name for f in scan.find_rpms(dnf)], ["tool"])
        self.assertEqual(asked[1][-2:], ("tool", "self-repo"))  # one question about just the candidates

    def test_debian_packages_from_a_downloaded_file(self):
        # apt marks a package no repository offers as "local"; its homepage says which project it's from.
        outputs = {
            "apt": "Listing...\ncc-tool/now 2.0-1 all [installed,local]\ncurl/noble 8.5.0-2 amd64 [installed]\n",
            "dpkg-query": "cc-tool|1:2.0-1ubuntu1|https://github.com/example/tool\n",
        }
        found = scan.find_debs(lambda *args: outputs[args[0]])
        self.assertEqual([(f.id, f.version, f.path) for f in found],
                         [("github.com/example/tool", "2.0", "Debian package \u201ccc-tool\u201d")])

    def test_opensuse_rpms_from_a_downloaded_file(self):
        # zypper lists a package no repository offers under "(System Packages)".
        outputs = {
            "zypper": '<solvable status="installed" name="cc-tool" kind="package" edition="2.0-1" arch="noarch" '
                      'repository="(System Packages)"/>\n<solvable status="installed" name="curl" kind="package" '
                      'edition="8.5-1" arch="x86_64" repository="Main Repository (OSS)"/>',
            "rpm": "cc-tool|2.0|https://gitlab.com/example/tool\n",
        }
        found = scan.find_zypper_rpms(lambda *args: outputs[args[0]])
        self.assertEqual([(f.id, f.path) for f in found], [("gitlab.com/example/tool", "RPM package \u201ccc-tool\u201d")])

    def test_if_dnf_cant_say_which_are_offered_none_are_listed(self):
        def dnf(*args):
            return "tool|1.0|@commandline|https://github.com/a/tool\n" if "--installed" in args else None

        self.assertEqual(scan.find_rpms(dnf), [])

    def test_rpms_from_a_downloaded_file(self):
        text = ("7zip|26.04|updates|https://7-zip.org\n"
                "kmod-nvidia|615.71|@commandline|https://www.nvidia.com/\n"
                "someapp|1.5.2|@commandline|https://github.com/owner/someapp\n"
                "repoapp|2.0|fedora|https://github.com/owner/repoapp\n"
                "broken line\n")
        found = scan.parse_rpm_list(text)
        self.assertEqual([(f.id, f.kind, f.version) for f in found], [("github.com/owner/someapp", "RPM", "1.5.2")])

    def test_appimages(self):
        apps = self.home / "Applications"
        apps.mkdir()
        (apps / "LocalSend-1.18.2-linux-x86-64.AppImage").write_bytes(
            b"\x7fELF" + b"\0" * 5000 + b"gh-releases-zsync|localsend|localsend|latest|*x86-64.AppImage.zsync\0")
        (apps / "Mystery-2.0.AppImage").write_bytes(b"\x7fELF no update info")
        (apps / "notes.txt").write_text("not an AppImage")
        found = scan.find_appimages([str(apps), str(self.home / "missing")])
        self.assertEqual([(f.id, f.kind, f.version) for f in found], [("github.com/localsend/localsend", "AppImage", "1.18.2")])

    def test_renamed_appimage_follows_the_file_it_updates_from(self):
        apps = self.home / "Applications"
        apps.mkdir()
        (apps / "nvim.appimage").write_bytes(
            b"\x7fELF" + b"\0" * 5000 + b"gh-releases-zsync|neovim|neovim|latest|nvim-linux-x86_64.appimage.zsync\0")
        found = scan.find_appimages([str(apps)])
        self.assertEqual([(f.id, f.version, f.release_file) for f in found],
                         [("github.com/neovim/neovim", "", "nvim-linux-x86_64.appimage")])
        cfg = Config()
        scan.merge(cfg, found)
        self.assertEqual((cfg.repos[0].asset_pattern, cfg.repos[0].kind), ("nvim-linux-x86_64.appimage", "AppImage"))

    def test_appimage_name_wins_over_a_wildcard_it_updates_from(self):
        apps = self.home / "Applications"
        apps.mkdir()
        (apps / "LocalSend-1.18.2-linux-x86-64.AppImage").write_bytes(
            b"\x7fELF" + b"\0" * 5000 + b"gh-releases-zsync|localsend|localsend|latest|*x86-64.AppImage.zsync\0")
        (apps / "Other.AppImage").write_bytes(
            b"\x7fELF" + b"\0" * 5000 + b"gh-releases-zsync|someone|other|latest|*x86_64.AppImage.zsync\0")
        cfg = Config()
        scan.merge(cfg, scan.find_appimages([str(apps)]))
        patterns = {r.id: r.asset_pattern for r in cfg.repos}
        self.assertEqual(patterns, {"github.com/localsend/localsend": "LocalSend-*-linux-x86-64.AppImage",
                                    "github.com/someone/other": ""})  # "*" there is any text: you pick the file

    def test_version_in_appimage_names(self):
        for name, version in [("LocalSend-1.18.2-linux-x86-64.AppImage", "1.18.2"), ("App_v2.0.1.AppImage", "2.0.1"),
                              ("tool-3.1-beta.2-x86_64.AppImage", "3.1-beta.2"), ("NoVersion.AppImage", "")]:
            self.assertEqual(scan.appimage_version(name), version, name)

    def test_each_project_listed_once(self):
        make_clone(self.home / "aero/aerothemeplasma", "https://gitgud.io/wackyideas/aerothemeplasma.git")
        make_clone(self.home / "aero/aerothemeplasma/aerothemeplasma", "https://gitgud.io/WackyIdeas/aerothemeplasma")
        found = scan.find_all([str(self.home)], system_packages=list, bundles=list)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].other_paths, [str(self.home / "aero/aerothemeplasma/aerothemeplasma")])


APPIMAGE_BYTES = b"\x7fELF" + b"\0" * 100 + b"gh-releases-zsync|localsend|localsend|latest|*.zsync\0"


class ScanFoldersTest(unittest.TestCase):
    """Default folders: home, /opt, /usr/local, /srv (DECISIONS.md, D12); more can be added in Settings."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name).resolve()
        self.home = self.root / "home"
        self.home.mkdir()
        self.old_home = os.environ.get("HOME")
        os.environ["HOME"] = str(self.home)

    def tearDown(self):
        os.environ["HOME"] = self.old_home
        for path in self.root.rglob("*"):
            path.chmod(0o755)  # undo read-only folders so they can be cleaned up
        self.dir.cleanup()

    def test_defaults(self):
        self.assertEqual(scan.DEFAULT_SCAN_FOLDERS, ("~", "/opt", "/usr/local", "/srv"))

    def test_overlapping_and_missing_folders(self):
        (self.home / "Projects").mkdir()
        roots = scan.scan_roots(["~/Projects", "~", str(self.root / "missing"), "~"])
        self.assertEqual(roots, [self.home])

    def test_clones_and_appimages_in_every_folder(self):
        opt = self.root / "opt"
        make_clone(opt / "tool", "https://github.com/someone/tool")
        (self.home / "Downloads/apps").mkdir(parents=True)
        (self.home / "Downloads/apps/LocalSend-1.18.2-linux-x86-64.AppImage").write_bytes(APPIMAGE_BYTES)
        found = {f.id: f for f in scan.find_all(["~", str(opt)], system_packages=list, bundles=list)}
        self.assertEqual(set(found), {"github.com/someone/tool", "github.com/localsend/localsend"})
        self.assertEqual(found["github.com/localsend/localsend"].version, "1.18.2")

    def test_hidden_appimage_folder_only_when_its_home_is_scanned(self):
        (self.home / ".local/bin").mkdir(parents=True)
        (self.home / ".local/bin/LocalSend-1.18.2-linux-x86-64.AppImage").write_bytes(APPIMAGE_BYTES)
        self.assertEqual(len(scan.find_all(["~"], system_packages=list, bundles=list)), 1)
        self.assertEqual(scan.find_all([str(self.root / "elsewhere")], system_packages=list, bundles=list), [])

    @unittest.skipIf(os.geteuid() == 0, "root can write to read-only folders")
    def test_folders_this_user_cant_change_need_a_password_to_update(self):
        opt = self.root / "opt"
        make_clone(opt / "system-tool", "https://github.com/someone/system-tool")
        make_clone(self.home / "mine", "https://github.com/someone/mine")
        (opt / "system-tool").chmod(0o555)
        found = {f.id: f for f in scan.find_all(["~", str(opt)], system_packages=list, bundles=list)}
        self.assertTrue(found["github.com/someone/system-tool"].needs_password)
        self.assertFalse(found["github.com/someone/mine"].needs_password)


class VersionOnDiskTest(unittest.TestCase):
    """A scanned repo's version is re-read from where it was found, each time its page opens."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)

    def tearDown(self):
        self.dir.cleanup()

    def test_clone(self):
        commit = make_clone(self.root / "smod", "https://gitgud.io/aeroshell/smod.git")
        self.assertEqual(scan.version_on_disk(str(self.root / "smod")), (commit, True))

    def test_appimage(self):
        app = self.root / "LocalSend-1.19.0-linux-x86-64.AppImage"
        app.write_bytes(APPIMAGE_BYTES)
        self.assertEqual(scan.version_on_disk(str(app)), ("1.19.0", True))

    def test_gone(self):
        self.assertEqual(scan.version_on_disk(str(self.root / "deleted")), ("", False))
        if shutil.which("rpm"):  # (without rpm, whether it's installed can't be told: not "gone")
            self.assertEqual(scan.version_on_disk("RPM package \u201cno-such-package-xyz\u201d"), ("", False))


def info(repo_id, host="gitlab", name="", description=""):
    ref = RepoRef.from_id(repo_id)
    return ProjectInfo(ref=ref, host=host, name=name or ref.name, description=description, default_branch="main")


class IdentifyTest(unittest.TestCase):
    def test_known_finds_arent_looked_up(self):
        item = aero_clone(AERO_NEW)
        checked = scan.identify([item], known=lambda _id: True, lookup=lambda ref: self.fail("no request needed"))
        self.assertEqual(checked[0].problem, "")

    def test_moved_project_gets_its_current_address(self):
        item = aero_clone(AERO_OLD)
        checked = scan.identify([item], known=lambda _id: False,
                                lookup=lambda ref: info(AERO_NEW, name="AeroThemePlasma", description="Win 7 look"))
        f = checked[0].found
        self.assertEqual((f.id, f.host, f.aliases, f.name, f.description),
                         (AERO_NEW, "gitlab", [AERO_OLD], "AeroThemePlasma", "Win 7 look"))

    def test_problems_are_explained(self):
        def lookup(ref):
            if ref.path == "me/private":
                raise sources.NotFound("nope")
            raise sources.Unsupported(sources.unsupported_text("example.org"))

        checked = scan.identify([aero_clone("github.com/me/private"), aero_clone("example.org/a/b")],
                                known=lambda _id: False, lookup=lookup)
        self.assertIn("private", checked[0].problem)
        self.assertIn("isn’t supported yet", checked[1].problem)


class MirrorTest(unittest.TestCase):
    """The same project on two sites (Aero on GitHub and gitgud.io) can't be told apart by address."""

    def setUp(self):
        self.cfg = Config(repos=[TrackedRepo(
            id="github.com/aeroshell-desktop/aerothemeplasma", name="Aero", url="", host="github", follow="branch",
            branch="Plasma/6.7", description="An alternative shell for KDE Plasma that aims to replicate the look and "
                                             "feel of Windows 7.")])

    def clone(self, description):
        item = aero_clone(AERO_NEW)
        item.description = description
        return item

    def test_same_name_and_description_looks_like_a_tracked_repo(self):
        # gitgud's description has a trailing space and the name differs in case; still the same.
        item = self.clone("An alternative shell for KDE Plasma that aims to replicate the look and feel of Windows 7. ")
        self.assertIs(scan.looks_like(self.cfg, item), self.cfg.repos[0])

    def test_different_description_isnt_a_match(self):
        self.assertIsNone(scan.looks_like(self.cfg, self.clone("A fork with other goals.")))
        self.assertIsNone(scan.looks_like(self.cfg, self.clone("")))

    def test_linking_merges_into_the_tracked_repo(self):
        item = self.clone("An alternative shell for KDE Plasma that aims to replicate the look and feel of Windows 7.")
        scan.merge(self.cfg, [scan.link_to(item, self.cfg.repos[0])])
        self.assertEqual(len(self.cfg.repos), 1)
        repo = self.cfg.repos[0]
        self.assertEqual((repo.id, repo.source, repo.aliases), ("github.com/aeroshell-desktop/aerothemeplasma",
                                                                 "scanned", [AERO_NEW]))
        # Next scan: the gitgud clone matches directly.
        self.assertIs(self.cfg.find_any(AERO_NEW), repo)


if __name__ == "__main__":
    unittest.main()
