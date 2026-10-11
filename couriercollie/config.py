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
    # For a clone: your version (as `installed`) when you last started its install script from the app. Empty if
    # never. The app can't see whether the script worked, only that it was started.
    script_run_at: str = ""
    # What installed it, when that's something that keeps it up to date ("dnf", "Flatpak"): found when its page
    # loads and on every check, so nothing here updates it (checker.installed_with).
    managed_by: str = ""


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
    path = path or default_path()
    if not path.exists():
        return Config()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        settings_data, repos_data = data.get("settings", {}), data.get("repos", [])
        if not isinstance(settings_data, dict) or not isinstance(repos_data, list) \
                or not all(isinstance(r, dict) for r in repos_data):
            raise TypeError("the settings or repos section isn\u2019t laid out as expected")
        settings = _from_dict(Settings, settings_data)
        settings.check_interval_hours = _nearest_interval(settings.check_interval_hours)
        repos = [_from_dict(TrackedRepo, r) for r in repos_data]
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError, TypeError) as e:
        raise ConfigError(f"Couldn’t read {path}: {e}") from e
    if "categories" not in data:
        # Saved before categories existed, when the list was sorted by name. Keep that order; it can be dragged from
        # here on.
        repos.sort(key=lambda r: r.name.lower())
    return Config(settings=settings, categories=_categories(data.get("categories"), repos), repos=repos)


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


def save(config: Config, path: Path | None = None) -> None:
    path = path or default_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    text = tomlwrite.dumps({"categories": config.categories, "settings": asdict(config.settings),
                            "repos": [asdict(r) for r in config.repos]})
    # Write to a temporary file and rename, so a crash mid-write can't leave a half-written settings file.
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
