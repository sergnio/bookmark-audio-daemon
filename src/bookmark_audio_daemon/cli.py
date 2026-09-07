"""Command-line interface and macOS launchd integration."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import time

from .config import ConfigError, DEFAULT_CONFIG_PATH, load_config, write_default_config
from .core import scan

LABEL = "com.sergnio.bookmark-audio-daemon"
LAUNCH_AGENTS = Path("~/Library/LaunchAgents").expanduser()


def _config_path(value: str) -> Path:
    return Path(value).expanduser()


def _launch_agent_path() -> Path:
    return LAUNCH_AGENTS / f"{LABEL}.plist"


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )


def _run_scan(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    downloaded, skipped, failed = scan(config)
    logging.info("scan complete: %d downloaded, %d already processed, %d failed", downloaded, skipped, failed)
    return 1 if failed else 0


def _watch(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    logging.info(
        "watching %s every %d seconds; the weekly reconciliation runs only while this process is awake",
        config.bookmarks,
        config.poll_seconds,
    )
    next_weekly = time.monotonic() + config.weekly_catchup_seconds
    while True:
        _run_scan(args)
        # A normal sleeping process is paused by macOS. This timer has no wake capability.
        time.sleep(config.poll_seconds)
        if time.monotonic() >= next_weekly:
            logging.info("running weekly catch-all reconciliation")
            next_weekly = time.monotonic() + config.weekly_catchup_seconds


def _launch_agent(config_path: Path) -> dict[str, object]:
    executable = str(Path(sys.argv[0]).resolve())
    log_dir = config_path.parent / "logs"
    return {
        "Label": LABEL,
        "ProgramArguments": [executable, "watch", "--config", str(config_path)],
        "WorkingDirectory": str(config_path.parent),
        "RunAtLoad": True,
        "KeepAlive": True,
        "ProcessType": "Background",
        "StandardOutPath": str(log_dir / "launchd.out.log"),
        "StandardErrorPath": str(log_dir / "launchd.err.log"),
        # launchd has a minimal PATH. Preserve the installer's PATH so Homebrew yt-dlp works.
        "EnvironmentVariables": {"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
    }


def _launchctl(*arguments: str, check: bool = True) -> None:
    subprocess.run(["launchctl", *arguments], check=check, text=True)


def _install(args: argparse.Namespace) -> int:
    config = load_config(args.config)  # Validate before touching launchd.
    plist_path = _launch_agent_path()
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    (args.config.parent / "logs").mkdir(parents=True, exist_ok=True)
    with plist_path.open("wb") as file:
        plistlib.dump(_launch_agent(args.config), file, sort_keys=False)

    domain = f"gui/{os.getuid()}"
    _launchctl("bootout", domain, str(plist_path), check=False)
    _launchctl("bootstrap", domain, str(plist_path))
    logging.info("installed and started %s", plist_path)
    logging.info("audio output: %s", config.output_dir)
    return 0


def _uninstall(args: argparse.Namespace) -> int:
    if not args.yes:
        raise ConfigError("uninstall stops the daemon and removes its launchd registration; rerun with --yes")
    plist_path = _launch_agent_path()
    _launchctl("bootout", f"gui/{os.getuid()}", str(plist_path), check=False)
    try:
        plist_path.unlink()
    except FileNotFoundError:
        pass
    logging.info("uninstalled %s; downloaded audio and state were retained", LABEL)
    return 0


def _status(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    state_file = config.state_file
    count = "unknown"
    try:
        import json

        with state_file.open(encoding="utf-8") as file:
            count = str(len(json.load(file).get("downloads", {})))
    except (OSError, ValueError, AttributeError):
        pass
    print(f"config: {args.config}")
    print(f"bookmarks: {config.bookmarks}")
    print(f"output: {config.output_dir}")
    print(f"state: {state_file} ({count} recorded clips)")
    print(f"launchd: {'installed' if _launch_agent_path().exists() else 'not installed'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Download audio from Vivaldi music bookmarks.")
    parser.add_argument("--verbose", action="store_true", help="include diagnostic logging")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init-config", help="write a non-destructive configuration template")
    init.add_argument("--config", type=_config_path, default=DEFAULT_CONFIG_PATH)

    for name, help_text in (("scan", "scan bookmarks once"), ("watch", "watch bookmarks while logged in"), ("status", "show local configuration and state"), ("install", "install the current command as a launchd user agent")):
        command = subparsers.add_parser(name, help=help_text)
        command.add_argument("--config", type=_config_path, default=DEFAULT_CONFIG_PATH)

    uninstall = subparsers.add_parser("uninstall", help="remove the launchd user agent")
    uninstall.add_argument("--yes", action="store_true", help="confirm stopping and removing the launchd registration")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _configure_logging(args.verbose)
    try:
        if args.command == "init-config":
            write_default_config(args.config)
            logging.info("created configuration template at %s", args.config)
            return 0
        if args.command == "scan":
            return _run_scan(args)
        if args.command == "watch":
            return _watch(args)
        if args.command == "install":
            return _install(args)
        if args.command == "uninstall":
            return _uninstall(args)
        if args.command == "status":
            return _status(args)
    except ConfigError as error:
        logging.error("%s", error)
        return 2
    except KeyboardInterrupt:
        logging.info("stopped")
        return 0
    return 2
