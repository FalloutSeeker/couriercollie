import json
import unittest
from pathlib import Path

from repoproject import sources
from repoproject.sources import RepoRef

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


class ParseUrlTest(unittest.TestCase):
    def check(self, text, domain, path):
        self.assertEqual(sources.parse_url(text), RepoRef(domain, path), text)

    def test_github_forms(self):
        for text in [
            "https://github.com/localsend/localsend",
            "https://github.com/localsend/localsend/",
            "https://github.com/localsend/localsend.git",
            "https://www.github.com/localsend/localsend/releases/tag/v1.0",
            "github.com/localsend/localsend",
            "  https://GitHub.com/localsend/localsend  ",
            "git@github.com:localsend/localsend.git",
        ]:
            self.check(text, "github.com", "localsend/localsend")

    def test_gitlab_nested_groups_and_subpages(self):
        self.check("https://gitgud.io/aeroshell/atp/aerothemeplasma", "gitgud.io", "aeroshell/atp/aerothemeplasma")
        self.check("https://gitgud.io/aeroshell/atp/aerothemeplasma/-/releases", "gitgud.io",
                   "aeroshell/atp/aerothemeplasma")
        self.check("https://gitlab.com/veloren/veloren.git", "gitlab.com", "veloren/veloren")
        self.check("ssh://git@gitlab.com/group/sub/proj.git", "gitlab.com", "group/sub/proj")

    def test_rejects_incomplete_addresses(self):
        for text in ["", "   ", "https://github.com/onlyowner", "https://github.com", "ftp://x.org/a/b"]:
            with self.assertRaises(ValueError, msg=text):
                sources.parse_url(text)

    def test_ref_urls(self):
        ref = RepoRef("gitgud.io", "aeroshell/atp/aerothemeplasma")
        self.assertEqual(ref.web_url, "https://gitgud.io/aeroshell/atp/aerothemeplasma")
        self.assertEqual(ref.git_url, "https://gitgud.io/aeroshell/atp/aerothemeplasma.git")
        self.assertEqual(ref.name, "aerothemeplasma")
        self.assertEqual(ref.id, "gitgud.io/aeroshell/atp/aerothemeplasma")


class GitHubTest(unittest.TestCase):
    def test_project(self):
        info = sources.parse_github_project(fixture("github_project.json"))
        self.assertEqual(info.ref, RepoRef("github.com", "localsend/localsend"))
        self.assertEqual(info.host, "github")
        self.assertEqual(info.default_branch, "main")

    def test_releases(self):
        releases = sources.parse_github_releases(fixture("github_releases.json"))
        self.assertEqual(len(releases), 2)
        latest = releases[0]
        self.assertEqual(latest.tag, "v1.18.2")
        self.assertIsNotNone(latest.date)
        appimage = next(a for a in latest.assets if a.name.endswith(".AppImage"))
        self.assertTrue(appimage.url.startswith("https://github.com/"))
        self.assertGreater(appimage.size, 0)
        self.assertTrue(appimage.digest.startswith("sha256:"))

    def test_drafts_are_skipped(self):
        data = fixture("github_releases.json")
        data[0]["draft"] = True
        self.assertEqual([r.tag for r in sources.parse_github_releases(data)], ["v1.18.1"])


class GitLabTest(unittest.TestCase):
    def test_project(self):
        info = sources.parse_gitlab_project("gitlab.com", fixture("gitlab_project.json"))
        self.assertEqual(info.ref, RepoRef("gitlab.com", "veloren/veloren"))
        self.assertEqual(info.host, "gitlab")

    def test_releases(self):
        releases = sources.parse_gitlab_releases("gitlab.com", "veloren/veloren", fixture("gitlab_releases.json"))
        self.assertEqual(releases[0].tag, "v0.18.0")
        self.assertIn("Linux (x86_64)", [a.name for a in releases[0].assets])
        self.assertTrue(all(a.size is None for a in releases[0].assets))


class ProjectInfoTest(unittest.TestCase):
    """project_info decides which kind of site a URL is on. These use a fake `get` instead of the network."""

    def test_github_goes_to_the_github_api(self):
        calls = []

        def get(url, headers=None):
            calls.append(url)
            return fixture("github_project.json")

        info = sources.project_info(RepoRef("github.com", "localsend/localsend"), get)
        self.assertEqual(calls, ["https://api.github.com/repos/localsend/localsend"])
        self.assertEqual(info.host, "github")

    def test_other_domains_are_tried_as_gitlab_and_follow_moves(self):
        moved = dict(fixture("gitlab_project.json"), path_with_namespace="aeroshell/atp/aerothemeplasma")

        def get(url, headers=None):
            self.assertEqual(url, "https://gitgud.io/api/v4/projects/wackyideas%2Faerothemeplasma")
            return moved

        info = sources.project_info(RepoRef("gitgud.io", "wackyideas/aerothemeplasma"), get)
        self.assertEqual(info.host, "gitlab")
        self.assertEqual(info.ref, RepoRef("gitgud.io", "aeroshell/atp/aerothemeplasma"))

    def test_non_git_sites_are_reported_as_unsupported(self):
        def get(url, headers=None):
            raise sources.BadAnswer("example.org sent an answer that isn’t from a GitHub or GitLab site.")

        with self.assertRaisesRegex(sources.SourceError, "doesn’t look like a GitHub or GitLab site"):
            sources.project_info(RepoRef("example.org", "a/b"), get)

    def test_not_found_passes_through(self):
        def get(url, headers=None):
            raise sources.NotFound("Project not found.")

        with self.assertRaises(sources.NotFound):
            sources.project_info(RepoRef("github.com", "a/b"), get)


class LsRemoteTest(unittest.TestCase):
    def test_parse(self):
        output = (
            "ref: refs/heads/Plasma/6.7\tHEAD\n"
            "e4cca91b12dd9419485c19bece76534972324f6a\tHEAD\n"
            "68b64e5b8b935519566c75f335b954d76ea76116\trefs/heads/Plasma/6.6\n"
            "e4cca91b12dd9419485c19bece76534972324f6a\trefs/heads/Plasma/6.7\n"
            "f9eb10a73bc0a43401b79a78cfe5f6b71d42d9c9\trefs/heads/master\n"
        )
        default, branches = sources.parse_ls_remote(output)
        self.assertEqual(default, "Plasma/6.7")
        # The default branch comes first, then the rest alphabetically.
        self.assertEqual([b.name for b in branches], ["Plasma/6.7", "master", "Plasma/6.6"])
        self.assertEqual(branches[0].sha, "e4cca91b12dd9419485c19bece76534972324f6a")


if __name__ == "__main__":
    unittest.main()
