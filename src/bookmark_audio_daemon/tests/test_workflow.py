import json
from pathlib import Path

from ..config import Config
from ..core import scan


def _fake_bookmarks(path: Path) -> None:
    document = {
        "roots": {
            "bookmark_bar": {
                "type": "folder",
                "name": "Music",
                "children": [
                    {
                        "type": "url",
                        "name": "My Loop",
                        "url": "https://looptube.io/video?videoId=123456&start=10&end=20",
                    }
                ],
            }
        }
    }
    path.write_text(json.dumps(document), encoding="utf-8")


def test_full_workflow(tmp_path: Path) -> None:
    bookmarks_path = tmp_path / "Bookmarks"
    _fake_bookmarks(bookmarks_path)
    config = Config(
        bookmarks=bookmarks_path,
        output_dir=tmp_path / "output",
        state_dir=tmp_path / "state",
        poll_seconds=300,
        weekly_catchup_seconds=604800,
        yt_dlp_path="yt-dlp",
    )

    calls = []

    def fake_runner(command, **kwargs):
        calls.append(command)

        class Result:
            returncode = 0

        return Result()

    downloaded, skipped, failed = scan(config, runner=fake_runner)
    assert (downloaded, skipped, failed) == (1, 0, 0)
    assert len(calls) == 1
    assert calls[0][0] == "yt-dlp"
    assert calls[0][-1] == "https://www.youtube.com/watch?v=123456"

    # Re-scanning is idempotent: the clip is already recorded in state.
    downloaded, skipped, failed = scan(config, runner=fake_runner)
    assert (downloaded, skipped, failed) == (0, 1, 0)
    assert len(calls) == 1
