"""Platform backends that connect the OS input stream to the lock engine.

==========  ======================  ==========================================
Platform    Backend                 How events are blocked
==========  ======================  ==========================================
Windows     ``WindowsBackend``      per event, in the low-level hook filter
macOS       ``MacBackend``          per event, in the Quartz event tap
Linux/X11   ``SwapBackend``         whole-device grab while locked
==========  ======================  ==========================================

pynput is only imported when a backend starts, so the rest of PawLock (and
its tests) works on machines without a display or input permissions.
"""

from __future__ import annotations

import sys

from ..engine import LockEngine
from .base import BackendError, InputBackend


def create_backend(engine: LockEngine, preference: str = "auto") -> InputBackend:
    """Pick the best backend for this OS.

    ``preference`` comes from the ``backend`` setting: ``"auto"`` or
    ``"native"`` use the per-event backend where one exists, ``"swap"``
    forces the portable listener-swap backend (useful for debugging).
    """
    if preference != "swap":
        if sys.platform == "win32":
            from .windows import WindowsBackend

            return WindowsBackend(engine)
        if sys.platform == "darwin":
            from .macos import MacBackend

            return MacBackend(engine)
    from .swap import SwapBackend

    return SwapBackend(engine)


__all__ = ["BackendError", "InputBackend", "create_backend"]
