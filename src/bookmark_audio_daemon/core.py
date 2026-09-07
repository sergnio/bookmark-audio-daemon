"""Bookmark parsing, idempotent state, and yt-dlp invocation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import logging
from pathlib import Path
import re
import subprocess
from typing import Callable, Iterator
from urllib.parse import parse_qs, unquote, urlparse

from .config import Config

LOG = logging.getLogger(__name__)
Runner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class Clip:
    video_id: str
    start: str
    end: str | None
    title: str | None
    source_url: str

    @property
    def key(self) -> str:
        canonical = "\0".join((self.video_id, self.start, self.end or ""))
        return hashlib.sha256(canonical.encode()).hexdigest()


def _seconds(value: str | None) -> str | None:
    """Normalize seconds and common YouTube 1h2m3s time syntax."""
    if not value:
        return None
    value = unquote(value).strip().lower()
    if re.fullmatch(r"\d+(?:\.\d+)?", value):
        return str(float(value)).rstrip("0").rstrip(".") if "." in value else value
    match = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+(?:\.\d+)?)s)?", value)
    if not match or not any(match.groups()):
        return None
    hours, minutes, seconds = match.groups()
    total = int(hours or 0) * 3600 + int(minutes or 0) * 60 + float(seconds or 0)
    return str(int(total)) if total.is_integer() else str(total)


def _one(query: dict[str, list[str]], *names: str) -> str | None:
    for name in names:
        if query.get(name):
            return query[name][0]
    return None


def parse_clip(url: str, title: str | None) -> Clip | None:
    """Return a supported clip or None for a non-video/malformed bookmark."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").casefold()
    query = parse_qs(parsed.query)
    video_id: str | None = None
    start: str | None = None
    end: str | None = None

    if host == "looptube.io" or host.endswith(".looptube.io"):
        video_id = _one(query, "videoId", "video_id")
        start = _seconds(_one(query, "start"))
        end = _seconds(_one(query, "end"))
    elif host == "youtu.be" or host.endswith(".youtu.be"):
        video_id = parsed.path.strip("/").split("/")[0] or None
        start = _seconds(_one(query, "t", "start"))
        if start is None and parsed.fragment:
            start = _seconds(parsed.fragment.removeprefix("t="))

    if not video_id or not re.fullmatch(r"[A-Za-z0-9_-]{6,}", video_id):
        return None
    if end is not None and float(end) <= float(start or 0):
        return None
    return Clip(
        video_id=video_id,
        start=start or "0",
        end=end,
        title=title.strip() if isinstance(title, str) and title.strip() else None,
        source_url=url,
    )


def _walk_music_bookmarks(node: object, in_music_folder: bool = False) -> Iterator[tuple[str, str | None]]:
    if not isinstance(node, dict):
        return
    is_music_folder = node.get("type") == "folder" and str(node.get("name", "")).casefold() == "music"
    active = in_music_folder or is_music_folder
    if active and node.get("type") == "url" and isinstance(node.get("url"), str):
        yield node["url"], node.get("name") if isinstance(node.get("name"), str) else None
    children = node.get("children")
    if isinstance(children, list):
        for child in children:
            yield from _walk_music_bookmarks(child, active)


def load_bookmarks(path: Path) -> list[Clip]:
    """Read supported clips without allowing a browser write/corruption to crash the daemon."""
    try:
        with path.open(encoding="utf-8") as file:
            document = json.load(file)
    except (OSError, json.JSONDecodeError) as error:
        LOG.warning("bookmarks unavailable or malformed (%s); will retry later", error)
        return []

    roots = document.get("roots") if isinstance(document, dict) else None
    top_nodes = roots.values() if isinstance(roots, dict) else [document]

    clips: dict[str, Clip] = {}
    for node in top_nodes:
        for url, title in _walk_music_bookmarks(node):
            clip = parse_clip(url, title)
            if clip is not None:
                clips.setdefault(clip.key, clip)
    return list(clips.values())


def _safe_filename_title(title: str | None) -> str:
    if not title:
        return "%(title)s"
    cleaned = re.sub(r"[/:\\\x00]", "-", title)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return (cleaned or "%(title)s")[:180]


def _load_state(path: Path) -> dict[str, object]:
    try:
        with path.open(encoding="utf-8") as file:
            state = json.load(file)
    except FileNotFoundError:
        return {"version": 1, "downloads": {}}
    except (OSError, json.JSONDecodeError) as error:
        LOG.warning("state file is unreadable (%s); preserving it and retrying downloads", error)
        return {"version": 1, "downloads": {}}
    if not isinstance(state, dict) or not isinstance(state.get("downloads"), dict):
        LOG.warning("state file has an invalid shape; preserving it and retrying downloads")
        return {"version": 1, "downloads": {}}
    return state


def _write_state(path: Path, state: dict[str, object]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as file:
        json.dump(state, file, indent=2, sort_keys=True)
        file.write("\n")
    temporary.replace(path)


def yt_dlp_command(config: Config, clip: Clip) -> list[str]:
    """Build an argument list, never a shell command, for a single clip."""
    title = _safe_filename_title(clip.title)
    end = clip.end or "inf"
    suffix = f"_{clip.start}-{end}_clip.%(ext)s"
    return [
        config.yt_dlp_path,
        "--no-playlist",
        "--no-overwrites",
        "-f",
        "bestaudio",
        "--download-sections",
        f"*{clip.start}-{end}",
        "--force-keyframes-at-cuts",
        "--output",
        str(config.output_dir / f"{title} [%(id)s]{suffix}"),
        f"https://www.youtube.com/watch?v={clip.video_id}",
    ]


def scan(config: Config, runner: Runner = subprocess.run) -> tuple[int, int, int]:
    """Download unseen clips. Returns (downloaded, skipped, failed)."""
    config.output_dir.mkdir(parents=True, exist_ok=True)
    config.state_dir.mkdir(parents=True, exist_ok=True)
    with config.lock_file.open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            LOG.info("another bookmark-audio-daemon scan is active; skipping")
            return 0, 0, 0

        state = _load_state(config.state_file)
        downloads = state["downloads"]
        assert isinstance(downloads, dict)
        downloaded = skipped = failed = 0
        for clip in load_bookmarks(config.bookmarks):
            if clip.key in downloads:
                skipped += 1
                continue
            command = yt_dlp_command(config, clip)
            LOG.info("downloading %s from %s", clip.video_id, clip.source_url)
            try:
                result = runner(command, check=False, text=True)
            except OSError as error:
                LOG.error("could not start yt-dlp for %s: %s", clip.video_id, error)
                failed += 1
                continue
            if result.returncode != 0:
                LOG.error("yt-dlp failed for %s with exit status %s", clip.video_id, result.returncode)
                failed += 1
                continue
            downloads[clip.key] = {
                **asdict(clip),
                "downloaded_at": datetime.now(timezone.utc).isoformat(),
            }
            _write_state(config.state_file, state)
            downloaded += 1
        return downloaded, skipped, failed
