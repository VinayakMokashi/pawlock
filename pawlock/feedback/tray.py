"""System-tray / menu-bar icon (via pystray).

The paw changes colour with the state: green = watching for cats,
grey = cat detector paused, red = locked, amber = dry-run "would lock".
Left-clicking the icon (Windows) runs the default action, "Lock now".
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Dict

from .icons import tray_icon

log = logging.getLogger(__name__)


class TrayIcon:
    """Thin wrapper around ``pystray.Icon``.

    *actions* is the application object (see ``PawLockApp``). It provides
    the status queries and commands the menu needs.
    """

    def __init__(self, actions: Any) -> None:
        import pystray  # Imported lazily: pulls in a GUI toolkit.

        self._pystray = pystray
        self._actions = actions
        self._images: Dict[str, Any] = {}
        self._state = "watching"
        self._icon = pystray.Icon(
            "PawLock",
            icon=self._image("watching"),
            title="PawLock",
            menu=self._build_menu(),
        )

    # -- menu ------------------------------------------------------------

    def _safe(self, fn: Callable[[], None]) -> Callable[..., None]:
        """Menu callbacks must never kill the tray thread."""

        def run(*_args: Any) -> None:
            try:
                fn()
            except Exception:
                log.exception("Tray action failed")

        return run

    def _build_menu(self) -> Any:
        p, a = self._pystray, self._actions
        item = p.MenuItem
        has_window = a.window_available()
        return p.Menu(
            # Clicking the paw opens the PawLock window (the default item).
            # Without a window (macOS default) the click does nothing scary.
            item("Open PawLock", self._safe(a.open_home), default=True, visible=has_window),
            item(lambda _: a.status_text(), None, enabled=False),
            item(lambda _: f"Unlock with {a.hotkey_text()}", None, enabled=False),
            p.Menu.SEPARATOR,
            item("Lock now", self._safe(a.lock_now), enabled=lambda _: not a.is_locked()),
            item("Practice lock (30 s)", self._safe(a.practice_lock), enabled=lambda _: not a.is_locked()),
            item("Unlock", self._safe(a.unlock_now), enabled=lambda _: a.is_locked()),
            p.Menu.SEPARATOR,
            item(
                "Detect cats automatically",
                self._safe(lambda: a.set_auto_detect(not a.auto_detect_enabled())),
                checked=lambda _: a.auto_detect_enabled(),
            ),
            item(
                lambda _: a.away_text(),
                self._safe(lambda: a.set_away_lock(not a.away_lock_enabled())),
                checked=lambda _: a.away_lock_enabled(),
            ),
            item(
                "Sound effects",
                self._safe(lambda: a.set_sound(not a.sound_enabled())),
                checked=lambda _: a.sound_enabled(),
            ),
            item(
                "Start at login",
                self._safe(lambda: a.set_autostart(not a.autostart_enabled())),
                checked=lambda _: a.autostart_enabled(),
                visible=a.autostart_supported(),
            ),
            p.Menu.SEPARATOR,
            item("Settings…", self._safe(a.open_settings_window)),
            item("How to use PawLock", self._safe(a.open_home if has_window else a.open_help)),
            item(
                "Advanced",
                p.Menu(
                    item("Edit settings file…", self._safe(a.open_settings)),
                    item("Reload settings file", self._safe(a.reload_settings)),
                    item("Open log folder", self._safe(a.open_logs)),
                ),
            ),
            p.Menu.SEPARATOR,
            item("Quit PawLock", self._safe(a.quit)),
        )

    def _image(self, state: str) -> Any:
        if state not in self._images:
            self._images[state] = tray_icon(state, 64)
        return self._images[state]

    # -- updates (any thread) ---------------------------------------------

    def set_state(self, state: str, tooltip: str) -> None:
        try:
            if state != self._state:
                self._icon.icon = self._image(state)
                self._state = state
            self._icon.title = tooltip[:127]  # Windows tooltip limit.
            self._icon.update_menu()
        except Exception:
            log.debug("Tray update failed", exc_info=True)

    def notify(self, message: str, title: str = "PawLock") -> None:
        try:
            if getattr(self._icon, "HAS_NOTIFICATION", False):
                self._icon.notify(message, title)
        except Exception:
            log.debug("Tray notification failed", exc_info=True)

    # -- running ----------------------------------------------------------

    def _setup(self, icon: Any) -> None:
        icon.visible = True

    def run_in_thread(self) -> threading.Thread:
        """Windows/Linux: the tray gets its own thread."""
        thread = threading.Thread(target=self.run_blocking, name="tray", daemon=True)
        thread.start()
        return thread

    def run_blocking(self) -> None:
        try:
            self._icon.run(setup=self._setup)
        except Exception:
            log.exception("The tray icon stopped working; PawLock keeps running without it")

    def run_detached(self) -> None:
        """macOS with Tk: integrate with the AppKit run loop Tk is driving."""
        self._icon.run_detached()
        self._icon.visible = True

    def stop(self) -> None:
        try:
            self._icon.stop()
        except Exception:
            pass


def show_tray_icon_next_to_clock(executable: str, attempts: int = 20, delay: float = 1.0) -> bool:
    """Windows 11: move PawLock's paw out of the hidden "^" area, next to the clock.

    Windows 11 hides new tray icons by default, and non-technical users
    then can't find PawLock. Explorer records every tray icon under
    ``HKCU\\Control Panel\\NotifyIconSettings\\<id>`` (with the program's
    path) and shows it next to the clock when ``IsPromoted`` is 1. This is
    called once, on the first run, so a user who later hides the icon on
    purpose is never overruled. Returns True if the icon was promoted.
    """
    import os
    import time
    import winreg

    target = os.path.normcase(os.path.abspath(executable))
    base = r"Control Panel\NotifyIconSettings"
    for _ in range(attempts):  # Explorer creates our entry a moment after the icon appears.
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, base) as root:
                index = 0
                while True:
                    try:
                        name = winreg.EnumKey(root, index)
                    except OSError:
                        break
                    index += 1
                    access = winreg.KEY_READ | winreg.KEY_SET_VALUE
                    with winreg.OpenKey(root, name, 0, access) as entry:
                        try:
                            path, _ = winreg.QueryValueEx(entry, "ExecutablePath")
                        except OSError:
                            continue
                        # Paths under well-known folders are stored as "{GUID}\rest".
                        tail = path.split("}\\", 1)[1] if path.startswith("{") and "}\\" in path else path
                        if tail and target.endswith(os.path.normcase(tail)):
                            winreg.SetValueEx(entry, "IsPromoted", 0, winreg.REG_DWORD, 1)
                            log.info("Tray icon moved next to the clock")
                            return True
        except OSError:
            return False  # Not Windows 11 (no such key): nothing to do.
        time.sleep(delay)
    return False
