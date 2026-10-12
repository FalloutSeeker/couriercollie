"""Talking to GitHub and GitLab: what a URL points to, its releases, and its branches.

Releases come from each site's API. Branches come from `git ls-remote`, which doesn't count against API limits
(DECISIONS.md, D7).
"""

import functools
import hashlib
import http.client
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

USER_AGENT = "couriercollie (https://github.com/FalloutSeeker/couriercollie)"
TIMEOUT = 20
# The biggest answer read from a site. A page of 30 releases of a busy project is about half a megabyte.
ANSWER_MAX_BYTES = 20 * 1024 * 1024
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
    # Its own website, as the project gives it on GitHub ("https://neovim.io"). Empty if none (or on GitLab).
    homepage: str = ""


# ---------------------------------------------------------------------------------------------------------------------
# URLs

# git@host:group/project, or ssh://git@host[:port]/group/project. SSH's port isn't the site's web port, so it's dropped.
_SSH_URL = re.compile(r"^(?:ssh://git@([^:/]+)(?::\d+)?/|git@([^:/]+):)(.+)$")


def parse_url(text: str) -> RepoRef:
    """Turn whatever the user pasted into a RepoRef. Accepts web URLs (with or without https://, extra path like
    /releases or /-/tags, a trailing .git) and git@host:owner/repo SSH addresses."""
    text = text.strip()
    if not text:
        raise ValueError("Enter the project’s web address, e.g. https://github.com/owner/project")
    if m := _SSH_URL.match(text):
        domain, path = m.group(1) or m.group(2), m.group(3)
    else:
        if "://" not in text:
            text = "https://" + text
        parsed = urllib.parse.urlparse(text)
        try:
            port = parsed.port
        except ValueError:  # "host:abc"
            port = -1
        if parsed.scheme not in ("http", "https") or not parsed.hostname or port == -1:
            raise ValueError("That doesn’t look like a web address.")
        domain, path = parsed.hostname.lower(), parsed.path
        # A self-hosted site on a port of its own (gitlab.example.com:8443) is asked there, always over https.
        if port and port not in (80, 443):
            domain = f"{domain}:{port}"
    domain = domain.lower().removeprefix("www.")
    path = path.strip("/")
    # Addresses GitHub serves a project's files and API from: the project's own address is what's tracked.
    if domain in ("raw.githubusercontent.com", "codeload.github.com"):
        domain = "github.com"
    elif domain == "api.github.com" and path.startswith("repos/"):
        domain, path = "github.com", path.removeprefix("repos/")
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


# KDE and GNOME keep their projects on their own GitLab sites and mirror them to GitHub (github.com/KDE/dolphin is
# invent.kde.org/system/dolphin). Their packages may give either address, or KDE's app page, as the homepage.
def _project_key(url: str) -> tuple[str, str] | None:
    """A project's address, as one key for all the addresses it's known by: ("kde", "dolphin") for KDE's own site,
    its GitHub mirror and apps.kde.org; likewise for GNOME. None for an address that isn't a project's."""
    parsed = urllib.parse.urlparse(url if "://" in url else "https://" + url)
    host, parts = (parsed.hostname or "").lower(), [p for p in parsed.path.lower().split("/") if p]
    if host == "apps.kde.org" and parts:
        return "kde", parts[0]
    try:
        ref = parse_url(url)
    except ValueError:
        return None
    owner, name = ref.path.lower().split("/")[0], ref.name.lower()
    if ref.domain == "invent.kde.org" or (ref.domain == "github.com" and owner == "kde"):
        return "kde", name
    if (ref.domain == "gitlab.gnome.org" and owner == "gnome") or (ref.domain == "github.com" and owner == "gnome"):
        return "gnome", name
    return ref.domain, ref.path.lower()


def same_project(url: str, repo_ids: list[str]) -> bool:
    """Whether `url` (e.g. a package's homepage) is one of these projects: the same address, or the same KDE or GNOME
    project by another of its official addresses. Never by a similar name."""
    key = _project_key(url)
    return key is not None and key in {_project_key(i) for i in repo_ids}


def _website(url: str) -> str:
    parsed = urllib.parse.urlparse(url.strip() if "://" in url else "https://" + url.strip())
    host = (parsed.hostname or "").lower().removeprefix("www.")
    return f"{host}{parsed.path.rstrip('/')}" if host else ""


def same_website(a: str, b: str) -> bool:
    """Whether two addresses are the same page ("https://neovim.io/" and "http://www.neovim.io")."""
    return bool(_website(a)) and _website(a) == _website(b)


# ---------------------------------------------------------------------------------------------------------------------
# Package registries: a distro package's homepage may be its crates.io or PyPI page rather than its repository
# (Fedora's Rust packages: https://crates.io/crates/ripgrep). The registry says which repository it comes from; asked
# once per page, and remembered.

_CRATE = re.compile(r"^https?://crates\.io/crates/([A-Za-z0-9_-]+)", re.I)
_PYPI = re.compile(r"^https?://(?:pypi\.org/project|pypi\.io/project|pypi\.python\.org/pypi)/([A-Za-z0-9_.-]+)", re.I)
_registry_answers: dict[str, list[str]] | None = None
_registry_lock = threading.Lock()


def _registry_file() -> Path:
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "couriercollie" / "registries.json"


def registry_repositories(url: str, get=None) -> list[str]:
    """The addresses a crates.io or PyPI page's registry gives for the package's source (repository, homepage).
    [] for any other address, or if the registry couldn't be asked (asked again next time)."""
    global _registry_answers
    if m := _CRATE.match(url):
        api = f"https://crates.io/api/v1/crates/{m[1]}"
    elif m := _PYPI.match(url):
        api = f"https://pypi.org/pypi/{m[1]}/json"
    else:
        return []
    with _registry_lock:
        if _registry_answers is None:
            try:
                _registry_answers = json.loads(_registry_file().read_text(encoding="utf-8"))
            except (OSError, ValueError):
                _registry_answers = {}
        if api in _registry_answers:
            return _registry_answers[api]
    try:
        data = (get or http_get_json)(api)
    except SourceError:
        return []
    if not isinstance(data, dict):
        return []
    if "crate" in data:
        crate = data.get("crate") or {}
        found = [crate.get("repository"), crate.get("homepage")]
    else:
        info = data.get("info") or {}
        found = [*(info.get("project_urls") or {}).values(), info.get("home_page")]
    found = [f for f in found if isinstance(f, str) and f.strip()]
    with _registry_lock:
        _registry_answers[api] = found
        try:
            _registry_file().parent.mkdir(parents=True, exist_ok=True)
            tmp = _registry_file().with_suffix(f".{os.getpid()}.tmp")
            tmp.write_text(json.dumps(_registry_answers), encoding="utf-8")
            os.replace(tmp, _registry_file())
        except OSError:
            pass  # asked again next time
    return found


# ---------------------------------------------------------------------------------------------------------------------
# The GitHub login (github_login.py): sent with requests to GitHub's API, and nowhere else

GITHUB_API = "api.github.com"
_login: Callable[[], str] | None = None  # gives the login's token, or ""
_token: str | None = None  # the token, once asked for this run
_token_lock = threading.Lock()
# GitHub turned the login down (revoked on GitHub): requests carry on without it.
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


# ---------------------------------------------------------------------------------------------------------------------
# Remembered release lists

# Release lists are kept with their ETag, and asked for with it: an unchanged list comes back as "304 Not Modified",
# with nothing to download, and (signed in) without counting against the hourly limit.


def _etag_dir() -> Path:
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "couriercollie" / "github"


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


# ---------------------------------------------------------------------------------------------------------------------
# HTTP


def _reset_time(headers) -> datetime | None:
    for name in ("x-ratelimit-reset", "ratelimit-reset"):
        if value := headers.get(name):
            try:
                return datetime.fromtimestamp(int(value), tz=timezone.utc)
            except (ValueError, OverflowError, OSError):  # not a time, or one out of range
                pass
    return None


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
            body = resp.read(ANSWER_MAX_BYTES + 1)
            if len(body) > ANSWER_MAX_BYTES:  # a site (self-hosted, say) mustn't be able to fill the memory
                raise BadAnswer(f"{domain} sent an answer far bigger than any project's.")
            data = json.loads(body)
            etag = getattr(resp, "headers", None) and resp.headers.get("ETag")
            if etag and domain == GITHUB_API and parsed.path.endswith("/releases"):
                _keep(url, etag, data)
            return data
    except urllib.error.HTTPError as e:
        if e.code == 304 and cached:
            return cached["body"]
        if e.code == 401 and token:
            # The login no longer works (revoked on GitHub): carry on without it; Settings says so.
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
    except http.client.HTTPException as e:  # the connection dropped partway through the answer
        raise Unreachable(f"{domain} stopped answering partway. Try again later.") from e
    except (TimeoutError, OSError) as e:
        raise Unreachable(f"{domain} took too long to answer. Try again later.") from e
    except ValueError as e:  # not JSON, or not text at all
        raise BadAnswer(f"{domain} sent an answer that isn’t from a GitHub or GitLab site.") from e


def _parse_date(text: str | None) -> datetime | None:
    if not text or not isinstance(text, str):
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _readable(parse):
    """For a function reading a site's answer: an answer of the wrong shape (a proxy's or captive portal's page, a
    site's bug) raises BadAnswer, which is said as is, rather than an error that would stop a whole check."""
    @functools.wraps(parse)
    def read(*args):
        try:
            return parse(*args)
        except (KeyError, TypeError, AttributeError, ValueError, IndexError) as e:
            raise BadAnswer("The site sent an answer that couldn\u2019t be read. Try again later.") from e
    return read


def _text(value) -> str:
    """A field that must be text (a tag, a file's name or address)."""
    if not isinstance(value, str) or not value:
        raise TypeError(f"expected text, got {value!r}")
    return value


# ---------------------------------------------------------------------------------------------------------------------
# GitHub

_GITHUB_HEADERS = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}


@_readable
def parse_github_project(data: dict) -> ProjectInfo:
    """GitHub's answer about a project. Its address may differ from the one asked for: renamed projects redirect."""
    owner = data.get("owner") or {}
    # GitHub has no project icons; an organization's picture is usually the project's logo.
    icon = owner.get("avatar_url") or "" if owner.get("type") == "Organization" else ""
    return ProjectInfo(
        ref=RepoRef("github.com", _text(data["full_name"])),
        host="github",
        name=_text(data["name"]),
        description=data.get("description") or "",
        default_branch=data.get("default_branch") or "",
        icon_url=icon,
        homepage=data.get("homepage") if isinstance(data.get("homepage"), str) else "",
    )


@_readable
def parse_github_releases(data: list) -> list[Release]:
    """GitHub's release list, newest first, without drafts (unpublished: only the project's maintainers see them)."""
    releases = []
    for r in data:
        if r.get("draft"):
            continue
        releases.append(
            Release(
                tag=_text(r["tag_name"]),
                title=r.get("name") or r["tag_name"],
                date=_parse_date(r.get("published_at") or r.get("created_at")),
                prerelease=bool(r.get("prerelease")),
                notes=r.get("body") or "",
                url=r.get("html_url") or "",
                assets=[
                    Asset(_text(a["name"]), _text(a["browser_download_url"]), a.get("size"), a.get("digest") or "")
                    for a in r.get("assets") or []
                ],
            )
        )
    return releases


# ---------------------------------------------------------------------------------------------------------------------
# GitLab


def _gitlab_api(domain: str, path: str) -> str:
    return f"https://{domain}/api/v4/projects/{urllib.parse.quote(path, safe='')}"


@_readable
def parse_gitlab_project(domain: str, data: dict) -> ProjectInfo:
    """A GitLab site's answer about a project (gitlab.com, or one hosted elsewhere, like gitgud.io)."""
    namespace = data.get("namespace") or {}
    icon = data.get("avatar_url") or (namespace.get("avatar_url") if namespace.get("kind") == "group" else "") or ""
    if icon.startswith("/"):
        icon = f"https://{domain}{icon}"  # some sites give it relative to themselves
    return ProjectInfo(
        ref=RepoRef(domain, _text(data["path_with_namespace"])),
        host="gitlab",
        name=data.get("name") or data["path"],
        description=data.get("description") or "",
        default_branch=data.get("default_branch") or "",
        icon_url=icon,
    )


@_readable
def parse_gitlab_releases(domain: str, path: str, data: list) -> list[Release]:
    """A GitLab site's release list. Its files are links the project added to each release, so they can point
    anywhere: the site's own uploads, its package registry, or another site."""
    releases = []
    for r in data:
        links = (r.get("assets") or {}).get("links") or []
        releases.append(
            Release(
                tag=_text(r["tag_name"]),
                title=r.get("name") or r["tag_name"],
                date=_parse_date(r.get("released_at") or r.get("created_at")),
                # GitLab has no "pre-release" flag; "upcoming" (scheduled for later) is the closest.
                prerelease=bool(r.get("upcoming_release")),
                notes=r.get("description") or "",
                url=(r.get("_links") or {}).get("self") or f"https://{domain}/{path}/-/releases/{r['tag_name']}",
                # GitLab doesn't give file sizes for release links.
                assets=[Asset(_text(l["name"]), _text(l.get("direct_asset_url") or l["url"])) for l in links],
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
    # A release under a moving name (Neovim's "stable") is a copy of a numbered one, and could be listed first and
    # taken for the newest: left out where there are numbered releases. Pre-releases ("nightly") are kept, as are
    # projects that only publish under such a name ("continuous").
    if any(not r.prerelease and re.search(r"\d", r.tag) for r in rels):
        rels = [r for r in rels if r.prerelease or re.search(r"\d", r.tag)]
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


def _first_line(text: str | None) -> str:
    return text.splitlines()[0] if text else ""


@_readable
def parse_github_compare(data: dict) -> Comparison:
    commits = [Commit(c["sha"], _first_line(c["commit"].get("message"))) for c in data.get("commits", [])]
    # GitHub describes the branch relative to yours, so its "ahead" means you're behind.
    relation = {"identical": SAME, "ahead": BEHIND, "behind": AHEAD, "diverged": DIVERGED}.get(data.get("status"),
                                                                                              DIVERGED)
    return Comparison(relation, data.get("ahead_by", len(commits)), commits[::-1])


@_readable
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
    """The project's default branch and every branch's newest commit, from git itself (`git ls-remote`): it works
    for any site, and doesn't count against GitHub's hourly limit."""
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
        last = said.splitlines()[-1] if said else "unknown error"
        raise SourceError(f"Couldn\u2019t list branches from {ref.domain}: {last}")
    return parse_ls_remote(result.stdout)
