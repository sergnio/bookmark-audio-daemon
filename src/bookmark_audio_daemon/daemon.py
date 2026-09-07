from pathlib import Path
from datetime import datetime, timezone
import json
import fcntl
from .config import Config
from .core import scan

LOG = logging.getLogger(__name__)

def main() -> None:
    """Entry point for the bookmark-audio-daemon."""
    config_path = Path("~/.config/bookmark-audio-daemon/config.toml").expanduser()
    config = Config.load(config_path)

    try:
        fcntl.flock(config.lock_file.open("a+"), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        LOG.info("another instance is running; exiting")
        return

    try:
        while True:
            LOG.info("Scanning bookmarks... [PID: %d]", os.getpid())
            downloaded, skipped, failed = scan(config)
            LOG.info(
                "Scanned %d bookmarks: %d downloaded, %d skipped, %d failed",
                downloaded + skipped + failed, downloaded, skipped, failed
            )
            
            if downloaded > 0:
                LOG.info("Sleeping for %d seconds until next scan", config.poll_seconds)
                time.sleep(config.poll_seconds)
            else:
                LOG.info("No downloads; sleeping for %d seconds until next scan", config.poll_seconds)
                time.sleep(config.poll_seconds)
    except KeyboardInterrupt:
        LOG.info("Interrupted by user")
    finally:
        LOG.info("Cleaning up and exiting")
