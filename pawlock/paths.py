"""Where PawLock keeps its settings, logs and PID file.

=========  ===================================================
Windows    ``%APPDATA%\\PawLock``
macOS      ``~/Library/Application Support/PawLock``
Linux      ``$XDG_CONFIG_HOME/pawlock`` (usually ``~/.config/pawlock``)
=========  ===================================================

Set the ``PAWLOCK_HOME`` environment variable to use a different folder
(handy for portable installs and for the test suite).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from . import APP_NAME


def app_dir() -> Path:
    override = os.environ.get("PAWLOCK_HOME")
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        return (Path(base) if base else Path.home() / "AppData" / "Roaming") / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    base = os.environ.get("XDG_CONFIG_HOME")
    return (Path(base) if base else Path.home() / ".config") / "pawlock"


def config_path() -> Path:
    return app_dir() / "config.json"


def log_dir() -> Path:
    return app_dir() / "logs"


def log_file() -> Path:
    return log_dir() / "pawlock.log"


def pid_path() -> Path:
    return app_dir() / "pawlock.pid"


def show_request_path() -> Path:
    """A second PawLock leaves this note so the running one opens its window."""
    return app_dir() / "show-window.request"


def welcome_marker_path() -> Path:
    """Exists once the welcome window has been shown."""
    return app_dir() / "welcome-shown"


def is_frozen() -> bool:
    """True when running as a PyInstaller-built executable."""
    return bool(getattr(sys, "frozen", False))


def open_in_default_app(path: Path) -> None:
    """Open a file or folder the way double-clicking it would."""
    if sys.platform == "win32":
        os.startfile(str(path))  # type: ignore[attr-defined]  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])  # noqa: S603, S607
    else:
        subprocess.Popen(["xdg-open", str(path)])  # noqa: S603, S607
