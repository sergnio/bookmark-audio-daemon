"""Configuration loading and the safe, explicit default configuration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import tomllib

APP_SUPPORT = Path("~/Library/Application Support/bookmark-audio-daemon").expanduser()
DEFAULT_CONFIG_PATH = APP_SUPPORT / "config.toml"
DEFAULT_BOOKMARKS_PATH = Path("~/Library/Application Support/Vivaldi/Default/Bookmarks").expanduser()
DEFAULT_OUTPUT_DIR = Path("~/Music/Bookmark Audio").expanduser()

CONFIG_TEMPLATE = """# bookmark-audio-daemon configuration\n# All paths are local. The daemon never uploads bookmark data.\n\n[paths]\nbookmarks = \"~/Library/Application Support/Vivaldi/Default/Bookmarks\"\noutput_dir = \"~/Music/Bookmark Audio\"\nstate_dir = \"~/Library/Application Support/bookmark-audio-daemon\"\n\n[operation]\n# The running daemon checks the bookmark file this often while the Mac is awake.\npoll_seconds = 300\n# A full reconciliation occurs at this interval while the daemon is running.\nweekly_catchup_seconds = 604800\nyt_dlp_path = \"yt-dlp\"\n"""


class ConfigError(ValueError):
    """The configuration file cannot be used safely."""


@dataclass(frozen=True)
class Config:
    bookmarks: Path
    output_dir: Path
    state_dir: Path
    poll_seconds: int
    weekly_catchup_seconds: int
    yt_dlp_path: str

    @property
    def state_file(self) -> Path:
        return self.state_dir / "downloads.json"

    @property
    def lock_file(self) -> Path:
        return self.state_dir / "daemon.lock"


def _path(value: object, name: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"paths.{name} must be a non-empty string")
    return Path(os.path.expandvars(value)).expanduser()


def _positive_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ConfigError(f"operation.{name} must be a positive integer")
    return value


def load_config(path: Path) -> Config:
    try:
        with path.open("rb") as file:
            data = tomllib.load(file)
    except FileNotFoundError as error:
        raise ConfigError(f"configuration file does not exist: {path}") from error
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ConfigError(f"cannot read configuration file {path}: {error}") from error

    paths = data.get("paths")
    operation = data.get("operation")
    if not isinstance(paths, dict) or not isinstance(operation, dict):
        raise ConfigError("configuration requires [paths] and [operation] sections")

    yt_dlp_path = operation.get("yt_dlp_path")
    if not isinstance(yt_dlp_path, str) or not yt_dlp_path.strip():
        raise ConfigError("operation.yt_dlp_path must be a non-empty string")

    return Config(
        bookmarks=_path(paths.get("bookmarks"), "bookmarks"),
        output_dir=_path(paths.get("output_dir"), "output_dir"),
        state_dir=_path(paths.get("state_dir"), "state_dir"),
        poll_seconds=_positive_int(operation.get("poll_seconds"), "poll_seconds"),
        weekly_catchup_seconds=_positive_int(
            operation.get("weekly_catchup_seconds"), "weekly_catchup_seconds"
        ),
        yt_dlp_path=yt_dlp_path,
    )


def write_default_config(path: Path) -> None:
    """Create a template without replacing a user's existing configuration."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as file:
        file.write(CONFIG_TEMPLATE)
