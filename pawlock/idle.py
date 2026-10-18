"""How long has nobody touched the computer, according to the operating system?

Away mode mostly relies on PawLock's own hooks to notice activity, but the OS
sees a few things our hooks can't. On Windows, for example, typing into an
administrator window is invisible to a normal app's hooks. Asking the OS as
well means away mode never locks while you're actually working.

==========  ==================================================================
Windows     ``GetLastInputInfo`` (user32)
macOS       ``CGEventSourceSecondsSinceLastEventType`` (Quartz)
Linux/X11   the MIT-SCREEN-SAVER extension (python-xlib, installed with pynput)
==========  ==================================================================

Every source fails soft: if it isn't available, ``make_idle_source`` returns
``None`` and PawLock falls back to its own measurement.
"""

from __future__ import annotations

import logging
import sys
from typing import Callable, Optional

log = logging.getLogger(__name__)

IdleSource = Callable[[], Optional[float]]


def _windows_source() -> Optional[IdleSource]:
    import ctypes
    from ctypes import wintypes

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    kernel32.GetTickCount.restype = wintypes.DWORD

    def idle() -> Optional[float]:
        info = LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(info)
        if not user32.GetLastInputInfo(ctypes.byref(info)):
            return None
        # Both are 32-bit millisecond counters that wrap every ~49.7 days.
        return ((kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF) / 1000.0

    return idle


def _mac_source() -> Optional[IdleSource]:
    import Quartz  # type: ignore[import-not-found]

    state = Quartz.kCGEventSourceStateHIDSystemState
    any_input = getattr(Quartz, "kCGAnyInputEventType", 0xFFFFFFFF)

    def idle() -> Optional[float]:
        return float(Quartz.CGEventSourceSecondsSinceLastEventType(state, any_input))

    return idle


def _x11_source() -> Optional[IdleSource]:
    from Xlib import display  # type: ignore[import-not-found]
    from Xlib.ext import screensaver  # noqa: F401  # registers screensaver_query_info

    connection = display.Display()
    if not connection.has_extension("MIT-SCREEN-SAVER"):
        connection.close()
        return None
    root = connection.screen().root

    def idle() -> Optional[float]:
        return connection.screensaver_query_info(root).idle / 1000.0

    return idle


def make_idle_source() -> Optional[IdleSource]:
    """The best idle-time source for this OS, or ``None``."""
    try:
        if sys.platform == "win32":
            source = _windows_source()
        elif sys.platform == "darwin":
            source = _mac_source()
        else:
            source = _x11_source()
        if source is not None:
            source()  # Make sure it actually works before relying on it.
        return source
    except Exception as exc:
        log.info("OS idle time unavailable (%s); away mode uses PawLock's own timing", exc)
        return None
