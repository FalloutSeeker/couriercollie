"""The settings file: global settings and the list of tracked repos.

Lives at ~/.config/repoproject/repos.toml (or $REPOPROJECT_CONFIG). Plain text, so it can be read, edited or backed up.
"""

import os
import tomllib
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from . import tomlwrite

FOLLOW_RELEASES = "releases"
FOLLOW_BRANCH = "branch"


@dataclass
class Settings:
    first_launch_done: bool = False
    auto_check: bool = False
    check_interval_hours: int = 6
    toasts: bool = True
    scanning: bool = False
    delete_old: bool = False
    delete_old_days: int = 30


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
    # What's being followed: "git" for a branch, or the chosen file's kind (assets.KIND_*). Empty until a file is picked.
    kind: str = ""
    prereleases: bool = False
    description: str = ""
    added_at: str = ""


@dataclass
class Config:
    settings: Settings = field(default_factory=Settings)
    repos: list[TrackedRepo] = field(default_factory=list)

    def find(self, repo_id: str) -> TrackedRepo | None:
        return next((r for r in self.repos if r.id == repo_id), None)


class ConfigError(Exception):
    """The settings file exists but can't be read. We never overwrite it in that case."""


def default_path() -> Path:
    if env := os.environ.get("REPOPROJECT_CONFIG"):
        return Path(env)
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "repoproject" / "repos.toml"


def _from_dict(cls, data: dict):
    # Ignore keys we don't know (e.g. from a newer version); missing keys get defaults.
    known = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in data.items() if k in known})


def load(path: Path | None = None) -> Config:
    path = path or default_path()
    if not path.exists():
        return Config()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        settings = _from_dict(Settings, data.get("settings", {}))
        repos = [_from_dict(TrackedRepo, r) for r in data.get("repos", [])]
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError, TypeError) as e:
        raise ConfigError(f"Couldn't read {path}: {e}") from e
    return Config(settings=settings, repos=repos)


def save(config: Config, path: Path | None = None) -> None:
    path = path or default_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    text = tomlwrite.dumps({"settings": asdict(config.settings), "repos": [asdict(r) for r in config.repos]})
    # Write to a temporary file and rename, so a crash mid-write can't leave a half-written settings file.
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
