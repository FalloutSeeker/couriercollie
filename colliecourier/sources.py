"""Talking to GitHub and GitLab: what a URL points to, its releases, and its branches.

Releases come from each site's API. Branches come from `git ls-remote`, which doesn't count against API limits
(DECISIONS.md, D7).
"""

import hashlib
import json
import os
import re
import subprocess
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

USER_AGENT = "colliecourier (https://github.com/FalloutSeeker/colliecourier)"
TIMEOUT = 20
RELEASES_PER_PAGE = 30


class SourceError(Exception):
    """Something went wrong talking to a site. The message is shown to the user as is."""


class NotFound(SourceError):
    pass


class Unsupported(SourceError):
    """The project is on a site the app can't talk to (yet): not GitHub, and not a GitLab site."""


def unsupported_text(domain: str) -> str:
    return f"{domain} isn\u2019t supported yet: only GitHub and GitLab sites are."


class BadAnswer(SourceError):
    """The site answered, but with an unexpected error code or something that isn't JSON."""


class Unreachable(SourceError):
    """The site didn't answer (no connection, or it's down). Nothing is known about the project either way."""


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
class Commit:
    sha: str
    title: str  # the first line of the commit message


@dataclass
class ProjectInfo:
    ref: RepoRef  # canonical: follows renames and moves
    host: str  # "github" or "gitlab"
    name: str
    description: str
    default_branch: str
    # The project's picture: its own icon (GitLab), or its organization's or group's picture. Not a person's profile
    # picture, which wouldn't represent the project. Empty if there's none.
    icon_url: str = ""


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


# ---------------------------------------------------------------------------------------------------------------------
# The GitHub login (github_login.py): sent with requests to GitHub's API, and nowhere else

GITHUB_API = "api.github.com"
_login: Callable[[], str] | None = None  # gives the login's token, or ""
_token: str | None = None  # the token, once asked for this run
_token_lock = threading.Lock()
# GitHub turned the login down (revoked on GitHub, or signed out of gh): requests carry on without it.
login_rejected = False


def use_github_login(get_token: Callable[[], str] | None) -> None:
    """Send requests to GitHub's API with this login (a function giving its token), or with none."""
    global _login, _token, login_rejected
    with _token_lock:
        _login, _token, login_rejected = get_token, None, False


# What a GitHub login looks like ("gho_…", "ghp_…", "github_pat_…"). Anything else isn't sent: a stray character
# could break the request, and the error would then quote the login.
_TOKEN_FORM = re.compile(r"[A-Za-z0-9_]{20,255}")


def _github_token() -> str:
    global _token, login_rejected
    with _token_lock:
        if _token is None:
            try:
                _token = ((_login() if _login else "") or "").strip()
            except Exception:  # noqa: BLE001  (a password store that can't be reached: carry on without)
                _token = ""
            if _token and not _TOKEN_FORM.fullmatch(_token):
                _token, login_rejected = "", True
        return _token


def _drop_rejected_login() -> None:
    global _token, login_rejected
    with _token_lock:
        _token, login_rejected = "", True


# Release lists are kept with their ETag, and asked for with it: an unchanged list comes back as "304 Not Modified",
# with nothing to download, and (signed in) without counting against the hourly limit.


def _etag_dir() -> Path:
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "colliecourier" / "github"


def _etag_file(url: str) -> Path:
    return _etag_dir() / f"{hashlib.sha1(url.encode()).hexdigest()[:16]}.json"


def _cached(url: str) -> dict | None:
    try:
        cached = json.loads(_etag_file(url).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return cached if isinstance(cached, dict) and cached.get("url") == url and cached.get("etag") else None


def _keep(url: str, etag: str, body) -> None:
    path = _etag_file(url)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps({"url": url, "etag": etag, "body": body}), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass  # asked for in full next time


def http_get_json(url: str, headers: dict | None = None, _without_login: bool = False):
    """GET a URL and parse the JSON answer. Follows redirects (sites redirect renamed projects)."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    parsed = urllib.parse.urlparse(url)
    domain = parsed.hostname
    token = _github_token() if domain == GITHUB_API and parsed.scheme == "https" and not _without_login else ""
    if token:
        # Not carried over if the request is redirected, so it can't end up anywhere but GitHub's API.
        req.add_unredirected_header("Authorization", f"Bearer {token}")
    cached = _cached(url) if domain == GITHUB_API and parsed.path.endswith("/releases") else None
    if cached:
        req.add_unredirected_header("If-None-Match", cached["etag"])
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.load(resp)
            etag = getattr(resp, "headers", None) and resp.headers.get("ETag")
            if etag and domain == GITHUB_API and parsed.path.endswith("/releases"):
                _keep(url, etag, data)
            return data
    except urllib.error.HTTPError as e:
        if e.code == 304 and cached:
            return cached["body"]
        if e.code == 401 and token:
            # The login no longer works (revoked on GitHub, or gh signed out): carry on without it; Settings says so.
            _drop_rejected_login()
            return http_get_json(url, headers, _without_login=True)
        if e.code == 404:
            # GitHub and GitLab say "not found" in JSON. Any other website's 404 page means it's not one of them.
            try:
                json.loads(e.read() or b"null")
            except (json.JSONDecodeError, OSError):
                raise BadAnswer(f"{domain} sent an answer that isn’t from a GitHub or GitLab site.") from e
            raise NotFound("Project not found. Check the address, and that the project is public.") from e
        remaining = e.headers.get("x-ratelimit-remaining") or e.headers.get("ratelimit-remaining")
        # GitHub's hourly limit is a 403 with nothing remaining; its "secondary" limit is a 403 with retry-after.
        if e.code == 429 or (e.code == 403 and (remaining == "0" or e.headers.get("retry-after"))):
            reset = _reset_time(e.headers)
            when = f" Try again after {reset.astimezone():%H:%M}." if reset else " Try again later."
            raise RateLimited(f"{domain} says too many requests were made.{when}", reset) from e
        raise BadAnswer(f"{domain} answered with an error ({e.code}). Try again later.") from e
    except urllib.error.URLError as e:
        raise Unreachable(f"Couldn’t reach {domain}. Check your internet connection.") from e
    except (TimeoutError, OSError) as e:
        raise Unreachable(f"{domain} took too long to answer. Try again later.") from e
    except ValueError as e:  # not JSON, or not text at all
        raise BadAnswer(f"{domain} sent an answer that isn’t from a GitHub or GitLab site.") from e


def github_rate() -> dict:
    """GitHub's hourly limit for this login (or none) as it stands: {"limit", "remaining", "reset" (local "HH:MM")}.
    Asking doesn't count against it. Empty if it couldn't be asked."""
    try:
        core = http_get_json(f"https://{GITHUB_API}/rate_limit", _GITHUB_HEADERS)["resources"]["core"]
        reset = datetime.fromtimestamp(int(core["reset"]), tz=timezone.utc).astimezone()
        return {"limit": int(core["limit"]), "remaining": int(core["remaining"]), "reset": f"{reset:%H:%M}"}
    except (SourceError, KeyError, TypeError, ValueError):
        return {}


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
    owner = data.get("owner") or {}
    # GitHub has no project icons; an organization's picture is usually the project's logo.
    icon = owner.get("avatar_url") or "" if owner.get("type") == "Organization" else ""
    return ProjectInfo(
        ref=RepoRef("github.com", data["full_name"]),
        host="github",
        name=data["name"],
        description=data.get("description") or "",
        default_branch=data.get("default_branch") or "",
        icon_url=icon,
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
    namespace = data.get("namespace") or {}
    icon = data.get("avatar_url") or (namespace.get("avatar_url") if namespace.get("kind") == "group" else "") or ""
    if icon.startswith("/"):
        icon = f"https://{domain}{icon}"  # some sites give it relative to themselves
    return ProjectInfo(
        ref=RepoRef(domain, data["path_with_namespace"]),
        host="gitlab",
        name=data.get("name") or data["path"],
        description=data.get("description") or "",
        default_branch=data.get("default_branch") or "",
        icon_url=icon,
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
    try:
        data = get(_gitlab_api(ref.domain, ref.path))
    except NotFound:
        # A GitLab site without this project, or a site that isn't GitLab at all (sourcehut, Codeberg, …, which
        # answer "not found" to GitLab's addresses). Only then is it asked which: saying "not found" for a site that
        # isn't supported would be wrong.
        if not _is_gitlab(ref.domain, get):
            raise Unsupported(unsupported_text(ref.domain)) from None
        raise
    except BadAnswer as e:
        raise Unsupported(unsupported_text(ref.domain)) from e
    if not isinstance(data, dict) or "path_with_namespace" not in data:
        raise Unsupported(unsupported_text(ref.domain))
    return parse_gitlab_project(ref.domain, data)


def _is_gitlab(domain: str, get) -> bool:
    """Whether a site answers like GitLab: a list of its public projects."""
    try:
        return isinstance(get(f"https://{domain}/api/v4/projects?per_page=1"), list)
    except SourceError:
        return False


def releases(ref: RepoRef, host: str, get=http_get_json, count: int = RELEASES_PER_PAGE) -> list[Release]:
    """The newest `count` releases, newest first."""
    if host == "github":
        data = get(f"https://api.github.com/repos/{ref.path}/releases?per_page={count}", _GITHUB_HEADERS)
        return parse_github_releases(data)
    data = get(f"{_gitlab_api(ref.domain, ref.path)}/releases?per_page={count}")
    return parse_gitlab_releases(ref.domain, ref.path, data)


def newest_releases(ref: RepoRef, host: str, count: int, prereleases: bool) -> list[Release]:
    """The newest `count` releases: each comes with its notes and file list, so asking for fewer than a page keeps
    the download small (30 of a busy project can be half a megabyte). If they're all pre-releases you don't follow, a
    full page instead, to find a release that counts."""
    rels = releases(ref, host, count=count)
    if len(rels) == count < RELEASES_PER_PAGE and not prereleases and all(r.prerelease for r in rels):
        rels = releases(ref, host)
    return rels


# How your version relates to a branch's newest commit.
SAME = "same"
BEHIND = "behind"  # the branch has newer commits: an update
AHEAD = "ahead"  # your version is newer than the branch
DIVERGED = "diverged"  # each has commits the other doesn't: your version is from another line of work


@dataclass
class Comparison:
    relation: str
    total: int = 0  # commits on the branch that you don't have
    commits: list[Commit] = field(default_factory=list)  # those commits, newest first (all, or the first page)


def parse_github_compare(data: dict) -> Comparison:
    commits = [Commit(c["sha"], (c["commit"]["message"] or "").splitlines()[0] if c["commit"]["message"] else "")
               for c in data.get("commits", [])]
    # GitHub describes the branch relative to yours, so its "ahead" means you're behind.
    relation = {"identical": SAME, "ahead": BEHIND, "behind": AHEAD, "diverged": DIVERGED}.get(data.get("status"),
                                                                                              DIVERGED)
    return Comparison(relation, data.get("ahead_by", len(commits)), commits[::-1])


def parse_gitlab_compare(data: dict) -> list[Commit]:
    return [Commit(c["id"], c.get("title") or "") for c in data.get("commits", [])][::-1]


def compare(ref: RepoRef, host: str, yours: str, head: str, get=http_get_json) -> Comparison:
    """How your version relates to a branch's newest commit, and the commits on it you don't have. One request on
    GitHub; on GitLab a second one when the branch has commits you don't, to tell "behind" from "diverged"."""
    if yours == head:
        return Comparison(SAME)
    if host == "github":
        try:
            return parse_github_compare(get(f"https://api.github.com/repos/{ref.path}/compare/{yours}...{head}",
                                            _GITHUB_HEADERS))
        except NotFound:
            # Also the answer for branches with no shared history (e.g. a branch started from scratch). If your
            # commit is on the site, that's what this is; if not, it really isn't there.
            get(f"https://api.github.com/repos/{ref.path}/commits/{yours}", _GITHUB_HEADERS)
            return Comparison(DIVERGED)
    api = f"{_gitlab_api(ref.domain, ref.path)}/repository"
    commits = parse_gitlab_compare(get(f"{api}/compare?{urllib.parse.urlencode({'from': yours, 'to': head})}"))
    if not commits:
        return Comparison(AHEAD)  # nothing on the branch that you don't have
    try:
        base = get(f"{api}/merge_base?{urllib.parse.urlencode([('refs[]', yours), ('refs[]', head)])}")
    except NotFound:
        return Comparison(DIVERGED, len(commits), commits)  # no shared history at all
    relation = BEHIND if (base or {}).get("id") == yours else DIVERGED
    return Comparison(relation, len(commits), commits)


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
        raise Unreachable(f"{ref.domain} took too long to list branches. Try again later.") from e
    if result.returncode != 0:
        said = result.stderr.strip()
        if any(s in said.lower() for s in ("could not resolve", "unable to access", "could not connect",
                                           "failed to connect", "network is unreachable", "timed out")):
            raise Unreachable(f"Couldn\u2019t reach {ref.domain}. Check your internet connection.")
        raise SourceError(f"Couldn\u2019t list branches from {ref.domain}: {said.splitlines()[-1] if said else 'unknown error'}")
    return parse_ls_remote(result.stdout)
