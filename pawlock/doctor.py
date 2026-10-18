"""``pawlock --doctor``: a plain-English health check.

Runs a series of harmless checks (it never blocks any input) and reports
what works, what doesn't, and what to do about it. Attach its output to bug
reports.
"""

from __future__ import annotations

import os
import platform
import sys
import time
from pathlib import Path
from typing import Callable, List, Tuple

from . import __version__, autostart, paths
from .config import load_config
from .instance import find_running

OK, WARN, FAIL = "OK", "WARN", "FAIL"
Check = Tuple[str, str, str]  # (status, title, detail)


def _probe(title: str, fn: Callable[[], Tuple[str, str]]) -> Check:
    try:
        status, detail = fn()
    except Exception as exc:
        status, detail = FAIL, f"{type(exc).__name__}: {exc}"
    return status, title, detail


def _system() -> Tuple[str, str]:
    frozen = " (packaged executable)" if paths.is_frozen() else ""
    return OK, f"{platform.platform()}, Python {platform.python_version()}{frozen}"


def _settings(config_file: Path) -> Callable[[], Tuple[str, str]]:
    def check() -> Tuple[str, str]:
        config, warnings = load_config(config_file)
        hotkey = config.parsed_hotkey()
        detail = f"{config_file} | hotkey {hotkey.display()} | sensitivity {config.sensitivity}"
        problems = warnings + [f"hotkey: {w}" for w in hotkey.warnings()]
        if problems:
            return WARN, detail + " | " + "; ".join(problems)
        return OK, detail

    return check


def _display_server() -> Tuple[str, str]:
    session = os.environ.get("XDG_SESSION_TYPE", "?")
    if os.environ.get("WAYLAND_DISPLAY") and session == "wayland":
        return WARN, (
            "Wayland session detected. Global input hooks are blocked on Wayland; log in with "
            "an 'X11'/'Xorg' session, or see docs/TROUBLESHOOTING.md for the uinput option."
        )
    if not os.environ.get("DISPLAY"):
        return FAIL, "No DISPLAY set; PawLock needs a graphical X11 session"
    return OK, f"X11 (DISPLAY={os.environ['DISPLAY']}, session={session})"


def _input_hooks() -> Tuple[str, str]:
    from pynput import keyboard, mouse

    backend = keyboard.Listener.__module__.rsplit(".", 1)[-1].lstrip("_")
    kb = keyboard.Listener(on_press=lambda *_: None)
    ms = mouse.Listener(on_click=lambda *_: None)
    kb.start()
    ms.start()
    try:
        kb.wait()
        ms.wait()
        time.sleep(0.3)
        alive = kb.is_alive() and ms.is_alive()
        trusted = getattr(kb, "IS_TRUSTED", True)
    finally:
        kb.stop()
        ms.stop()
    if sys.platform == "darwin" and not trusted:
        return FAIL, (
            "macOS has not granted access. Enable PawLock (or your Terminal) under System "
            "Settings > Privacy & Security > Accessibility AND Input Monitoring"
        )
    if not alive:
        return FAIL, f"pynput backend '{backend}' could not keep its hooks installed"
    return OK, f"global keyboard + mouse hooks work (pynput backend: {backend})"


def _tray() -> Tuple[str, str]:
    import pystray

    return OK, f"pystray backend: {pystray.Icon.__module__.rsplit('.', 1)[-1].lstrip('_')}"


def _overlay() -> Tuple[str, str]:
    import tkinter

    return OK, f"Tk {tkinter.TkVersion}"


def _instance() -> Tuple[str, str]:
    process = find_running(paths.pid_path())
    if process is None:
        return OK, "not running"
    return OK, f"running (PID {process.pid})"


def _autostart() -> Tuple[str, str]:
    if not autostart.is_supported():
        return WARN, "not supported on this platform"
    return OK, "enabled" if autostart.is_enabled() else "disabled"


def run_doctor(config_file: Path) -> Tuple[str, bool]:
    """Return ``(report, everything_ok)``."""
    checks: List[Check] = [
        _probe("System", _system),
        _probe("Settings", _settings(config_file)),
    ]
    if sys.platform.startswith("linux"):
        checks.append(_probe("Display server", _display_server))
    checks += [
        _probe("Input hooks", _input_hooks),
        _probe("Tray icon", _tray),
        _probe("On-screen banner", _overlay),
        _probe("PawLock process", _instance),
        _probe("Start at login", _autostart),
        (OK, "Log file", str(paths.log_file())),
    ]
    lines = [f"PawLock {__version__}: doctor report", "=" * 44]
    lines += [f"[{status:^4}] {title}: {detail}" for status, title, detail in checks]
    healthy = all(status != FAIL for status, _, _ in checks)
    lines += ["", "All good! PawLock should work on this computer." if healthy
              else "Some checks failed. See docs/TROUBLESHOOTING.md for fixes."]
    return "\n".join(lines), healthy
