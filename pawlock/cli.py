"""Command-line interface: ``pawlock`` / ``python -m pawlock``.

Double-clicking the packaged app is the same as running ``pawlock`` with no
arguments. The flags are for testing, troubleshooting and power users.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path
from typing import List, Optional

from . import __version__, messages, paths
from .config import LOG_LEVELS, SENSITIVITIES, Config, load_config, save_config
from .messages import HAS_CONSOLE, show_message

log = logging.getLogger("pawlock")

_EPILOG = """\
examples:
  pawlock                     start protecting (tray icon appears)
  pawlock --practice          start locked for 30 s to practise unlocking
  pawlock --dry-run           show what would be locked without blocking anything
  pawlock --away-minutes 5    lock by itself after 5 minutes with nobody at the computer
  pawlock --stop              emergency stop for a running PawLock
  pawlock --doctor            check that everything works on this computer

default hotkey: Ctrl + Alt + Shift + L (locks and unlocks)
while locked you can also type the word: unlock
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pawlock",
        description="PawLock: cat-proof your computer by locking the keyboard and trackpad.",
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"PawLock {__version__}")

    run = parser.add_argument_group("running")
    run.add_argument("--config", type=Path, metavar="FILE", help="use this settings file instead of the default")
    run.add_argument("--dry-run", action="store_true", help="detect and report, but never block any input")
    run.add_argument("--lock", action="store_true", help="start in the locked state")
    run.add_argument(
        "--practice", nargs="?", const=30.0, type=float, metavar="SECONDS",
        help="start locked, auto-unlocking after SECONDS (default 30): a safe way to try the hotkey",
    )
    run.add_argument("--sensitivity", choices=SENSITIVITIES, help="cat-detector sensitivity for this run")
    run.add_argument("--max-lock-minutes", type=float, metavar="N", help="auto-unlock after N minutes (0 = never)")
    run.add_argument(
        "--away-minutes", type=float, metavar="N",
        help="away mode: lock after N minutes with no keyboard/mouse use (0 = off)",
    )
    run.add_argument("--no-auto-detect", action="store_true", help="only lock when you press the hotkey")
    run.add_argument("--no-tray", action="store_true", help="don't show the tray icon")
    run.add_argument("--no-overlay", action="store_true", help="don't show the on-screen banner")
    run.add_argument("--no-sound", action="store_true", help="no sound effects")
    run.add_argument("--log-level", choices=LOG_LEVELS, type=str.upper, help="logging detail")

    tools = parser.add_argument_group("tools")
    tools.add_argument("--stop", action="store_true", help="stop the running PawLock (kill switch)")
    tools.add_argument("--status", action="store_true", help="is PawLock running?")
    tools.add_argument("--doctor", action="store_true", help="run a health check and print a report")
    tools.add_argument("--where", action="store_true", help="show where settings and logs live")
    tools.add_argument("--reset-config", action="store_true", help="restore default settings (keeps a backup)")
    tools.add_argument("--quiet", action="store_true", help="no dialogs or output (for installers and scripts)")
    tools.add_argument("--welcome", action="store_true", help="show the welcome window, as on the first run")
    return parser


def _ensure_streams() -> None:
    """Windowed executables have no stdout/stderr; give them somewhere harmless to write."""
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))  # noqa: SIM115


def _report(text: str, error: bool = False) -> None:
    """Long reports go to the console, or to a text file that we open, if there's no console."""
    if messages.QUIET:
        return
    if HAS_CONSOLE:
        print(text, file=sys.stderr if error else sys.stdout)
        return
    report = paths.app_dir() / "pawlock-report.txt"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(text + "\n", encoding="utf-8")
    try:
        paths.open_in_default_app(report)
    except OSError:
        show_message(text, error=error)


def main(argv: Optional[List[str]] = None) -> int:
    _ensure_streams()
    args = build_parser().parse_args(argv)
    config_file: Path = args.config or paths.config_path()
    if args.quiet:
        messages.QUIET = True

    # -- tools that don't start PawLock ------------------------------------
    if args.stop:
        from .instance import stop_running

        result = stop_running(paths.pid_path())
        outcome = {
            "stopped": "PawLock has been stopped. Your keyboard and mouse are free.",
            "not-running": "PawLock is not running.",
            "failed": "Could not stop PawLock. Use Task Manager / Activity Monitor to end it.",
        }
        show_message(outcome[result], error=result == "failed")
        return 1 if result == "failed" else 0

    if args.status:
        from .instance import find_running

        process = find_running(paths.pid_path())
        show_message(f"PawLock is running (PID {process.pid})." if process else "PawLock is not running.")
        return 0 if process else 1

    if args.where:
        _report(
            f"Settings: {config_file}\nLogs:     {paths.log_file()}\nPID file: {paths.pid_path()}"
        )
        return 0

    if args.reset_config:
        if config_file.exists():
            backup = config_file.with_name(f"{config_file.name}.{time.strftime('%Y%m%d-%H%M%S')}.bak")
            config_file.replace(backup)
            note = f" Your old settings were saved as {backup.name}."
        else:
            note = ""
        save_config(Config(), config_file)
        show_message(f"Default settings restored in {config_file}.{note}")
        return 0

    if args.doctor:
        from .doctor import run_doctor

        report, healthy = run_doctor(config_file)
        _report(report, error=not healthy)
        return 0 if healthy else 1

    # -- normal run ----------------------------------------------------------
    from .logging_setup import setup_logging

    config, warnings = load_config(config_file)
    setup_logging(args.log_level or config.log_level, paths.log_file(), console=HAS_CONSOLE)
    for warning in warnings:
        log.warning("Settings: %s", warning)

    from .app import PawLockApp, RunOptions

    options = RunOptions(
        dry_run=args.dry_run,
        start_locked=True if args.lock else None,
        practice_seconds=max(5.0, args.practice) if args.practice is not None else 0.0,
        tray=False if args.no_tray else None,
        overlay=False if args.no_overlay else None,
        sound=False if args.no_sound else None,
        auto_detect=False if args.no_auto_detect else None,
        sensitivity=args.sensitivity,
        max_lock_minutes=args.max_lock_minutes,
        first_run=args.welcome or not paths.welcome_marker_path().exists(),
        away_minutes=max(0.0, args.away_minutes) if args.away_minutes is not None else None,
    )
    try:
        return PawLockApp(config, config_file, options).run()
    except KeyboardInterrupt:
        return 0
