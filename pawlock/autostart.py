"""Start PawLock automatically when you log in (tray menu: "Start at login").

=========  ==============================================================
Windows    ``HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run`` value
macOS      ``~/Library/LaunchAgents/io.github.pawlock.plist`` (LaunchAgent)
Linux      ``~/.config/autostart/pawlock.desktop`` (XDG autostart)
=========  ==============================================================

Nothing here needs administrator rights, and turning the option off removes
exactly what turning it on added.
"""

from __future__ import annotations

import os
import plistlib
import shlex
import subprocess
import sys
from pathlib import Path
from typing import List

from . import APP_NAME
from .paths import is_frozen

_MAC_LABEL = "io.github.pawlock"
_WINDOWS_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def launch_command() -> List[str]:
    """The command that starts this copy of PawLock."""
    if is_frozen():
        exe = Path(sys.executable)
        bundle = next((p for p in exe.parents if p.suffix == ".app"), None)
        if sys.platform == "darwin" and bundle is not None:
            return ["/usr/bin/open", "-a", str(bundle)]
        return [str(exe)]
    python = Path(sys.executable)
    if sys.platform == "win32":
        # pythonw.exe runs without a console window.
        windowless = python.with_name("pythonw.exe")
        if windowless.exists():
            python = windowless
    return [str(python), "-m", "pawlock"]


def is_supported() -> bool:
    return sys.platform in ("win32", "darwin") or sys.platform.startswith("linux")


def _mac_plist() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{_MAC_LABEL}.plist"


def _linux_desktop_file() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "autostart" / "pawlock.desktop"


def is_enabled() -> bool:
    if sys.platform == "win32":
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _WINDOWS_RUN_KEY) as key:
                winreg.QueryValueEx(key, APP_NAME)
            return True
        except OSError:
            return False
    if sys.platform == "darwin":
        return _mac_plist().exists()
    return _linux_desktop_file().exists()


def set_enabled(enabled: bool) -> None:
    """Turn start-at-login on or off. Raises ``OSError`` on failure."""
    command = launch_command()
    if sys.platform == "win32":
        import winreg

        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, _WINDOWS_RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, subprocess.list2cmdline(command))
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                except FileNotFoundError:
                    pass
        return

    if sys.platform == "darwin":
        plist = _mac_plist()
        if enabled:
            plist.parent.mkdir(parents=True, exist_ok=True)
            with plist.open("wb") as handle:
                plistlib.dump(
                    {"Label": _MAC_LABEL, "ProgramArguments": command, "RunAtLoad": True,
                     "ProcessType": "Interactive"},
                    handle,
                )
        elif plist.exists():
            plist.unlink()
        return

    desktop = _linux_desktop_file()
    if enabled:
        desktop.parent.mkdir(parents=True, exist_ok=True)
        desktop.write_text(
            "[Desktop Entry]\n"
            "Type=Application\n"
            f"Name={APP_NAME}\n"
            "Comment=Cat-proof your keyboard and trackpad\n"
            f"Exec={shlex.join(command)}\n"
            "X-GNOME-Autostart-enabled=true\n",
            encoding="utf-8",
        )
    elif desktop.exists():
        desktop.unlink()
