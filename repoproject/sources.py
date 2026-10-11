"""Talking to GitHub and GitLab: what a URL points to, its releases, and its branches.

Releases come from each site's API. Branches come from `git ls-remote`, which doesn't count against API limits
(DECISIONS.md, D7).
"""

import json
import os
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone

USER_AGENT = "RepoProject (https://github.com/FalloutSeeker)"
TIMEOUT = 20
RELEASES_PER_PAGE = 30


class SourceError(Exception):
    """Something went wrong talking to a site. The message is shown to the user as is."""


class NotFound(SourceError):
    pass


class BadAnswer(SourceError):
    """The site answered, but with an unexpected error code or something that isn't JSON."""


class RateLimited(SourceError):
    def __init__(self, message: str, reset_at: datetime | None = None):
        super().__init__(message)
        self.reset_at = reset_at


@dataclass(frozen=True)
class RepoRef:
    domain: str  # "github.com", "gitgud.io"
    path: str  # "owner/name", or "group/subgroup/name" on GitLab

    @classmethod
    def from_id(cls, repo_id: str) -> "RepoRef":
        domain, _, path = repo_id.partition("/")
        return cls(domain, path)

    @property
    def id(self) -> str:
        return f"{self.domain}/{self.path}"

    @property
    def web_url(self) -> str:
        return f"https://{self.domain}/{self.path}"

    @property
    def git_url(self) -> str:
        return f"{self.web_url}.git"

    @property
    def name(self) -> str:
        return self.path.rsplit("/", 1)[-1]


@dataclass
class Asset:
    name: str
    url: str
    size: int | None = None
    digest: str = ""  # "sha256:…" when the site provides one


@dataclass
class Release:
    tag: str
    title: str
    date: datetime | None
    prerelease: bool
    notes: str
    url: str
    assets: list[Asset] = field(default_factory=list)


@dataclass
class Branch:
    name: str
    sha: str


@dataclass
class ProjectInfo:
    ref: RepoRef  # canonical: follows renames and moves
    host: str  # "github" or "gitlab"
    name: str
    description: str
    default_branch: str


# ---------------------------------------------------------------------------------------------------------------------
# URLs

_SSH_URL = re.compile(r"^(?:ssh://)?git@([^:/]+)[:/](.+)$")


def parse_url(text: str) -> RepoRef:
    """Turn whatever the user pasted into a RepoRef. Accepts web URLs (with or without https://, extra path like
    /releases or /-/tags, a trailing .git) and git@host:owner/repo SSH addresses."""
    text = text.strip()
    if not text:
        raise ValueError("Enter the project’s web address, e.g. https://github.com/owner/project")
    if m := _SSH_URL.match(text):
        domain, path = m.group(1), m.group(2)
    else:
        if "://" not in text:
            text = "https://" + text
        parsed = urllib.parse.urlparse(text)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError("That doesn’t look like a web address.")
        domain, path = parsed.hostname.lower(), parsed.path
    domain = domain.lower().removeprefix("www.")
    path = path.strip("/")
    # GitLab puts sub-pages after "/-/"; GitHub's sub-pages come after owner/name.
    path = path.split("/-/", 1)[0]
    if path.endswith("/-"):
        path = path[:-2]
    parts = [p for p in path.split("/") if p]
    if domain == "github.com":
        parts = parts[:2]
    if len(parts) < 2:
        raise ValueError("The address needs to include the owner and the project, e.g. github.com/owner/project")
    parts[-1] = parts[-1].removesuffix(".git")
    return RepoRef(domain, "/".join(parts))


# ---------------------------------------------------------------------------------------------------------------------
# HTTP


def _reset_time(headers) -> datetime | None:
    for name in ("x-ratelimit-reset", "ratelimit-reset"):
        if value := headers.get(name):
            try:
                return datetime.fromtimestamp(int(value), tz=timezone.utc)
            except ValueError:
                pass
    return None


def http_get_json(url: str, headers: dict | None = None):
    """GET a URL and parse the JSON answer. Follows redirects (sites redirect renamed projects)."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    domain = urllib.parse.urlparse(url).hostname
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            # GitHub and GitLab say "not found" in JSON. Any other website's 404 page means it's not one of them.
            try:
                json.loads(e.read() or b"null")
            except (json.JSONDecodeError, OSError):
                raise BadAnswer(f"{domain} sent an answer that isn’t from a GitHub or GitLab site.") from e
            raise NotFound("Project not found. Check the address, and that the project is public.") from e
        remaining = e.headers.get("x-ratelimit-remaining") or e.headers.get("ratelimit-remaining")
        if e.code == 429 or (e.code == 403 and remaining == "0"):
            reset = _reset_time(e.headers)
            when = f" Try again after {reset.astimezone():%H:%M}." if reset else " Try again later."
            raise RateLimited(f"{domain} says too many requests were made.{when}", reset) from e
        raise BadAnswer(f"{domain} answered with an error ({e.code}). Try again later.") from e
    except urllib.error.URLError as e:
        raise SourceError(f"Couldn’t reach {domain}. Check your internet connection.") from e
    except (TimeoutError, OSError) as e:
        raise SourceError(f"{domain} took too long to answer. Try again later.") from e
    except json.JSONDecodeError as e:
        raise BadAnswer(f"{domain} sent an answer that isn’t from a GitHub or GitLab site.") from e


def _parse_date(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


# ---------------------------------------------------------------------------------------------------------------------
# GitHub

_GITHUB_HEADERS = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}


def parse_github_project(data: dict) -> ProjectInfo:
    return ProjectInfo(
        ref=RepoRef("github.com", data["full_name"]),
        host="github",
        name=data["name"],
        description=data.get("description") or "",
        default_branch=data.get("default_branch") or "",
    )


def parse_github_releases(data: list) -> list[Release]:
    releases = []
    for r in data:
        if r.get("draft"):
            continue
        releases.append(
            Release(
                tag=r["tag_name"],
                title=r.get("name") or r["tag_name"],
                date=_parse_date(r.get("published_at") or r.get("created_at")),
                prerelease=bool(r.get("prerelease")),
                notes=r.get("body") or "",
                url=r.get("html_url") or "",
                assets=[
                    Asset(a["name"], a["browser_download_url"], a.get("size"), a.get("digest") or "")
                    for a in r.get("assets", [])
                ],
            )
        )
    return releases


# ---------------------------------------------------------------------------------------------------------------------
# GitLab


def _gitlab_api(domain: str, path: str) -> str:
    return f"https://{domain}/api/v4/projects/{urllib.parse.quote(path, safe='')}"


def parse_gitlab_project(domain: str, data: dict) -> ProjectInfo:
    return ProjectInfo(
        ref=RepoRef(domain, data["path_with_namespace"]),
        host="gitlab",
        name=data.get("name") or data["path"],
        description=data.get("description") or "",
        default_branch=data.get("default_branch") or "",
    )


def parse_gitlab_releases(domain: str, path: str, data: list) -> list[Release]:
    releases = []
    for r in data:
        links = r.get("assets", {}).get("links", [])
        releases.append(
            Release(
                tag=r["tag_name"],
                title=r.get("name") or r["tag_name"],
                date=_parse_date(r.get("released_at") or r.get("created_at")),
                # GitLab has no "pre-release" flag; "upcoming" (scheduled for later) is the closest.
                prerelease=bool(r.get("upcoming_release")),
                notes=r.get("description") or "",
                url=(r.get("_links") or {}).get("self") or f"https://{domain}/{path}/-/releases/{r['tag_name']}",
                # GitLab doesn't give file sizes for release links.
                assets=[Asset(l["name"], l.get("direct_asset_url") or l["url"]) for l in links],
            )
        )
    return releases


# ---------------------------------------------------------------------------------------------------------------------
# Either site


def project_info(ref: RepoRef, get=http_get_json) -> ProjectInfo:
    """Find out which kind of site a repo is on and fetch its basic info."""
    if ref.domain == "github.com":
        return parse_github_project(get(f"https://api.github.com/repos/{ref.path}", _GITHUB_HEADERS))
    # Anything else: see if it answers like a GitLab site.
    unsupported = f"{ref.domain} doesn’t look like a GitHub or GitLab site. Only those are supported."
    try:
        data = get(_gitlab_api(ref.domain, ref.path))
    except BadAnswer as e:
        raise SourceError(unsupported) from e
    if not isinstance(data, dict) or "path_with_namespace" not in data:
        raise SourceError(unsupported)
    return parse_gitlab_project(ref.domain, data)


def releases(ref: RepoRef, host: str, get=http_get_json) -> list[Release]:
    if host == "github":
        data = get(f"https://api.github.com/repos/{ref.path}/releases?per_page={RELEASES_PER_PAGE}", _GITHUB_HEADERS)
        return parse_github_releases(data)
    data = get(f"{_gitlab_api(ref.domain, ref.path)}/releases?per_page={RELEASES_PER_PAGE}")
    return parse_gitlab_releases(ref.domain, ref.path, data)


def parse_ls_remote(output: str) -> tuple[str, list[Branch]]:
    """Parse `git ls-remote --symref <url> HEAD refs/heads/*` into (default branch, branches)."""
    default, branches = "", []
    for line in output.splitlines():
        if line.startswith("ref: ") and line.endswith("\tHEAD"):
            default = line[len("ref: ") : -len("\tHEAD")].removeprefix("refs/heads/")
            continue
        sha, _, ref = line.partition("\t")
        if ref.startswith("refs/heads/"):
            branches.append(Branch(ref.removeprefix("refs/heads/"), sha))
    branches.sort(key=lambda b: (b.name != default, b.name.lower()))
    return default, branches


def branches(ref: RepoRef) -> tuple[str, list[Branch]]:
    # GIT_TERMINAL_PROMPT=0: a private or missing repo fails instead of waiting for a password nobody will type.
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "", "SSH_ASKPASS": ""}
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--symref", ref.git_url, "HEAD", "refs/heads/*"],
            capture_output=True, text=True, timeout=TIMEOUT, env=env,
        )
    except FileNotFoundError as e:
        raise SourceError("git isn’t installed, so branches can’t be listed.") from e
    except subprocess.TimeoutExpired as e:
        raise SourceError(f"{ref.domain} took too long to list branches. Try again later.") from e
    if result.returncode != 0:
        raise SourceError(f"Couldn’t list branches from {ref.domain}: {result.stderr.strip() or 'unknown error'}")
    return parse_ls_remote(result.stdout)
