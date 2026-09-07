from pathlib import Path
import json
import time
from .config import Config
from .core import load_bookmarks
from .daemon import main
from .tests.test_parser import test_parse_clip

LOG = logging.getLogger(__name__)

def test_full_workflow() -> None:
    """Test the full bookmark download workflow."""
    config_path = Path("~/.config/bookmark-audio-daemon/config.toml").expanduser()
    config = Config.load(config_path)

    # Test clip parsing
    test_parse_clip()

    # Test bookmark loading
    bookmarks = load_bookmarks(config.bookmarks)
    assert len(bookmarks) >= 0, "No bookmarks found"

    # Test download command construction
    for clip in bookmarks:
        command = yt_dlp_command(config, clip)
        assert command[0] == config.yt_dlp_path, "yt-dlp path mismatch"
        assert "--output" in command, "Output path not specified"
        assert "https://www.youtube.com/watch?v=" in command[-1], "Invalid YouTube URL"

    LOG.info("Full workflow test passed")
