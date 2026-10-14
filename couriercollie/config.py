"""The settings file: global settings and the list of tracked repos.

Lives at ~/.config/couriercollie/repos.toml (or $COURIERCOLLIE_CONFIG). Plain text, so it can be read, edited or
backed up.
"""

import os
import tomllib
from dataclasses import MISSING, asdict, dataclass, field, fields
from datetime import datetime
from pathlib import Path

from . import tomlwrite

FOLLOW_RELEASES = "releases"
FOLLOW_BRANCH = "branch"
NOT_INSTALLED = "-"
# How a repo got onto the list. A manual entry becomes a scanned one when a scan finds it on this computer.
SOURCE_MANUAL = "manual"
SOURCE_SCANNED = "scanned"


# The choices offered in the window (DESIGN.md §6, §7).
# In hours: daily, every 7 days, every 14 days, monthly (4 weeks).
CHECK_INTERVALS_HOURS = (24, 168, 336, 672)
# Scanned by default (DECISIONS.md, D12). Kept in sync with scan.DEFAULT_SCAN_FOLDERS (a test checks).
DEFAULT_SCAN_FOLDERS = ["~", "/opt", "/usr/local", "/srv"]


@dataclass
class Settings:
    first_launch_done: bool = False
    auto_check: bool = False
    check_interval_hours: int = 24
    toasts: bool = True
    scanning: bool = False
    scan_folders: list[str] = field(default_factory=lambda: list(DEFAULT_SCAN_FOLDERS))
    # Signed in to GitHub (github_login.py): "" no, "app" yes, with a code (the login is in the password store). And
    # the account's name, to show.
    github_login: str = ""
    github_user: str = ""
    # Which way repo icons were looked up (icons.py). Raised when that changes, so saved icons are looked up again.
    icon_lookup: int = 0
    # Open when you log in (an autostart entry, integration.set_start_at_login); in the tray if keep_in_tray is on.
    start_at_login: bool = False
    # Closing the window leaves couriercollie running in the tray (tray.py), rather than quitting.
    keep_in_tray: bool = False
    # couriercollie added itself to the list (Backend._track_myself): once, so if you stop tracking it, it stays gone.
    tracked_itself: bool = False


@dataclass
class TrackedRepo:
    # "<domain>/<path>", e.g. "github.com/localsend/localsend". Unique.
    id: str
    name: str
    url: str
    host: str  # "github" or "gitlab"
    follow: str = FOLLOW_RELEASES
    branch: str = ""
    # Which release file to follow, with the version replaced by "*" (see assets.pattern_for).
    asset_pattern: str = ""
    # What's being followed: "git" for a branch, or the chosen file's kind (assets.KIND_*). Empty until a file is
    # picked.
    kind: str = ""
    prereleases: bool = False
    # Your version: a release tag, or a commit when following a branch. NOT_INSTALLED if you don't have it. Empty until
    # known: it's then set to the newest version the first time the repo's releases or branches are loaded.
    installed: str = ""
    description: str = ""
    added_at: str = ""
    source: str = SOURCE_MANUAL
    # Where a scan found it on this computer (a git clone's folder, an AppImage, …). Empty for manual entries.
    local_path: str = ""
    # Other addresses for the same project: what was typed when adding, and old names the site redirected from.
    # A scan matches against these too, so a clone made under an old name isn't added a second time.
    aliases: list[str] = field(default_factory=list)
    # The icon found for it (icons.py): "theme:<name>", "file:<path>", "-" for none. Empty until looked up, which
    # happens once.
    icon: str = ""
    # The category it's in (one of Config.categories), or empty for Uncategorized.
    category: str = ""
    # For a release archive with several programs in it: the one to run (its file name). Empty: worked out.
    program: str = ""
    # For a clone: the step run after each update (a command, in its folder), and the fingerprint of what you
    # approved (the command and the files it names). If they change, it isn't run until approved again.
    apply_command: str = ""
    apply_approved: str = ""
    apply_commit: str = ""  # the clone's commit when it was approved: what changed since is shown (applying.changes)
    # For a clone: Only Download was chosen, so Update only downloads, and doesn't ask what to run.
    apply_skip: bool = False
    # What installed it, when that's something that keeps it up to date ("dnf", "Flatpak"): found when its page
    # loads and on every check, so nothing here updates it (checker.installed_with).
    managed_by: str = ""
    # The newest release has builds, but only for other systems (Android, Windows, macOS): only its versions are
    # tracked, and Install never clones it (a phone app's source is no use here). Found when its page loads.
    other_systems: bool = False
    # The project's own website, as it gives it on GitHub ("https://neovim.io"), or "-" if it gives none: a package
    # whose homepage is that website is this project (packages.managed_by_system). Looked up once.
    homepage: str = ""


@dataclass
class Config:
    settings: Settings = field(default_factory=Settings)
    # Your categories, in the order they're shown. Repos are shown in the order of `repos` within each one.
    categories: list[str] = field(default_factory=list)
    repos: list[TrackedRepo] = field(default_factory=list)

    def find(self, repo_id: str) -> TrackedRepo | None:
        return next((r for r in self.repos if r.id == repo_id), None)

    def find_any(self, repo_id: str) -> TrackedRepo | None:
        """Find a repo by its address or any of its other addresses. Ignores upper/lower case, as GitHub and GitLab
        do (github.com/ImranR98/Obtainium and github.com/imranr98/obtainium are the same project)."""
        key = repo_id.lower()
        return next((r for r in self.repos if key == r.id.lower() or key in (a.lower() for a in r.aliases)), None)


class ConfigError(Exception):
    """The settings file exists but can't be read. We never overwrite it in that case."""


def default_path() -> Path:
    if env := os.environ.get("COURIERCOLLIE_CONFIG"):
        return Path(env)
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "couriercollie" / "repos.toml"


def _fits(value, like) -> bool:
    """Whether a value from the file is the same kind as a field's default (a list of text for lists)."""
    if isinstance(like, bool):
        return isinstance(value, bool)
    if isinstance(like, int):
        return isinstance(value, int) and not isinstance(value, bool)
    if isinstance(like, list):
        return isinstance(value, list) and all(isinstance(v, str) for v in value)
    return isinstance(value, type(like))


def _from_dict(cls, data: dict):
    # Keys we don't know (e.g. from a newer version) are ignored. Missing keys, and values of the wrong kind (e.g. a
    # hand-edited file), get the default. A required field (no default) that's missing or wrong makes the file
    # unreadable, so it's never overwritten.
    values = {}
    for f in fields(cls):
        if f.name not in data:
            continue
        if f.default is not MISSING:
            like = f.default
        else:
            like = f.default_factory() if f.default_factory is not MISSING else ""
        if _fits(data[f.name], like):
            values[f.name] = data[f.name]
    return cls(**values)


def _nearest_interval(hours) -> int:
    """Interval choices have changed over time; an old saved value becomes the next choice up (6 hours -> daily)."""
    try:
        hours = int(hours)
    except (TypeError, ValueError):
        return Settings.check_interval_hours
    return next((h for h in CHECK_INTERVALS_HOURS if h >= hours), CHECK_INTERVALS_HOURS[-1])


def load(path: Path | None = None) -> Config:
    """Read the settings file; a missing one is a fresh start. A broken one raises ConfigError rather than being
    replaced: the app then saves nothing until it's fixed, so your list is never lost."""
    path = path or default_path()
    if not path.exists():
        return Config()
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise ConfigError(f"Couldn’t read {path}: {e}") from e
    return loads(text, path)


def loads(text: str, path: Path | None = None) -> Config:
    """The settings from the file's text (load); `path` is for the message if it's broken."""
    try:
        data = tomllib.loads(text)
        settings_data, repos_data = data.get("settings", {}), data.get("repos", [])
        if not isinstance(settings_data, dict) or not isinstance(repos_data, list) \
                or not all(isinstance(r, dict) for r in repos_data):
            raise TypeError("the settings or repos section isn\u2019t laid out as expected")
        settings = _from_dict(Settings, settings_data)
        settings.check_interval_hours = _nearest_interval(settings.check_interval_hours)
        repos = [_from_dict(TrackedRepo, r) for r in repos_data]
    except (tomllib.TOMLDecodeError, TypeError) as e:
        raise ConfigError(f"Couldn’t read {path or default_path()}: {e}") from e
    # A hand-edited file may list a repo twice: the first is kept (two rows for one address would act as one).
    seen: set[str] = set()
    repos = [r for r in repos if not (r.id.lower() in seen or seen.add(r.id.lower()))]
    if "categories" not in data:
        # Saved before categories existed, when the list was sorted by name. Keep that order; it can be dragged from
        # here on.
        repos.sort(key=lambda r: r.name.lower())
    return Config(settings=settings, categories=_categories(data.get("categories"), repos), repos=repos)


def merge(base: Config, mine: Config, theirs: Config) -> Config:
    """The settings file was changed by hand while the app had changes of its own: both are kept. `base` is the file
    as the app last read or wrote it, `mine` the app's settings now, `theirs` the file now. Each setting, each repo's
    each field, and the categories: whichever side changed it; where both did, the hand edit. A repo added on either
    side is kept. One removed by hand goes (the app changes repos quietly all the time: a check's finding, a page's);
    one removed in the app goes unless it was changed by hand."""
    def pick(b, m, t):
        if m == b:
            return t
        if t == b:
            return m
        if isinstance(b, dict) and isinstance(m, dict) and isinstance(t, dict):
            return {k: pick(b.get(k), m.get(k), t.get(k)) for k in {**m, **t}}
        return t

    by_id = [{r.id.lower(): asdict(r) for r in c.repos} for c in (base, mine, theirs)]
    b_repos, m_repos, t_repos = by_id
    repos = []
    for key, t in t_repos.items():
        if key in b_repos and key not in m_repos and t == b_repos[key]:
            continue  # stopped tracking in the app
        b = b_repos.get(key, {})  # (added by hand: nothing before)
        repos.append(pick(b, m_repos.get(key, b or t), t))  # (removed in the app but changed by hand: kept)
    for key, m in m_repos.items():
        if key not in t_repos and key not in b_repos:
            repos.append(m)  # added in the app
    tracked = [_from_dict(TrackedRepo, r) for r in repos]
    settings = _from_dict(Settings, pick(asdict(base.settings), asdict(mine.settings), asdict(theirs.settings)))
    return Config(settings=settings, repos=tracked,
                  categories=_categories(pick(base.categories, mine.categories, theirs.categories), tracked))


def _categories(saved, repos: list[TrackedRepo]) -> list[str]:
    """The saved categories without blanks or repeats. A repo in a category that isn't listed (a hand-edited file)
    gets that category added, rather than quietly losing it."""
    names: list[str] = []
    for name in (saved if isinstance(saved, list) else []) + [r.category for r in repos]:
        if isinstance(name, str) and name.strip() and name.strip().lower() not in (n.lower() for n in names):
            names.append(name.strip())
    for r in repos:
        r.category = next((n for n in names if n.lower() == r.category.strip().lower()), "") if r.category else ""
    return names


def reset(path: Path | None = None) -> Path | None:
    """Back to a fresh start: the settings file is renamed to a dated backup, not deleted. Returns the backup's path,
    or None if there was nothing to reset."""
    path = path or default_path()
    if not path.exists():
        return None
    backup = path.with_name(f"{path.name}.backup-{datetime.now():%Y%m%d-%H%M%S}")
    os.replace(path, backup)
    return backup


def dumps(config: Config) -> str:
    """The settings file's text."""
    return tomlwrite.dumps({"categories": config.categories, "settings": asdict(config.settings),
                            "repos": [asdict(r) for r in config.repos]})


def save(config: Config, path: Path | None = None) -> str:
    """Write the settings file; returns what was written."""
    path = path or default_path()
    if path.is_symlink():
        path = path.resolve()  # (kept by a dotfile manager, say: the file it points to is written, the link kept)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = dumps(config)
    # Write to a temporary file and rename, so a crash mid-write can't leave a half-written settings file.
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return text
