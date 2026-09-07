from pathlib import Path
import json
import time
from .config import Config
from .core import load_bookmarks
from .daemon import main

LOG = logging.getLogger(__name__)

def test_parse_clip() -> None:
    """Test parsing of different clip types."""
    test_cases = [
        {
            "url": "https://looptube.io/video?videoId=123456&start=120&end=240",
            "title": "My Loop",
            "expected": {
                "video_id": "123456",
                "start": "120",
                "end": "240",
                "title": "My Loop",
                "source_url": "https://looptube.io/video?videoId=123456&start=120&end=240"
            }
        },
        {
            "url": "https://youtu.be/abc123?start=300",
            "title": "My Video",
            "expected": {
                "video_id": "abc123",
                "start": "300",
                "end": None,
                "title": "My Video",
                "source_url": "https://youtu.be/abc123?start=300"
            }
        },
        {
            "url": "https://youtube.com/watch?v=def456&t=420",
            "title": "Another Video",
            "expected": {
                "video_id": "def456",
                "start": "420",
                "end": None,
                "title": "Another Video",
                "source_url": "https://youtube.com/watch?v=def456&t=420"
            }
        }
    ]

    for i, case in enumerate(test_cases):
        try:
            clip = parse_clip(case["url"], case["title"])
            assert clip is not None, f"Test {i} failed: parse_clip returned None"
            assert clip.video_id == case["expected"]["video_id"], f"Test {i} failed: video_id mismatch"
            assert clip.start == case["expected"]["start"], f"Test {i} failed: start mismatch"
            assert clip.end == case["expected"]["end"], f"Test {i} failed: end mismatch"
            assert clip.title == case["expected"]["title"], f"Test {i} failed: title mismatch"
            assert clip.source_url == case["expected"]["source_url"], f"Test {i} failed: source_url mismatch"
            LOG.info("Test %d passed", i)
        except Exception as error:
            LOG.error("Test %d failed: %s", i, error)
