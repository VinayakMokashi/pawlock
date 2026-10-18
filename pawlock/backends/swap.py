"""Portable backend for Linux (X11) and anything else pynput supports.

On X11 pynput cannot drop individual events. Its ``suppress=True`` mode
grabs the *whole* keyboard and pointer. So this backend swaps listeners
whenever the lock state changes:

* **Unlocked:** passive listeners (``suppress=False``) watch the input so
  the hotkey and the cat detector work.
* **Locked:** they are replaced by grabbing listeners (``suppress=True``).
  Apps receive nothing, but our callbacks still see every key, so the
  hotkey and unlock phrase keep working.

The swap happens on the controller thread, never inside a callback. There
is a gap of a few milliseconds while listeners are replaced; a cat's paw is
not that fast.

Safety: X11 releases every grab the moment our connection closes, so if
PawLock crashes or is killed, input comes straight back.

Wayland: global input hooks are deliberately impossible for normal apps
under Wayland. Use an X11 session, or run pynput's ``uinput`` backend as
root (``PYNPUT_BACKEND=uinput``). See docs/TROUBLESHOOTING.md.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Optional

from .. import keys
from .base import BackendError, InputBackend

log = logging.getLogger(__name__)


class SwapBackend(InputBackend):
    name = "listener-swap"
    selective = False

    def __init__(self, engine) -> None:
        super().__init__(engine)
        self._lock = threading.RLock()
        self._keyboard: Optional[Any] = None
        self._mouse: Optional[Any] = None
        self._grabbing = False
        self._expected_running = False

    # -- lifecycle -------------------------------------------------------

    def start(self) -> None:
        with self._lock:
            self._start_listeners(self._want_grab())
            self._expected_running = True

    def stop(self) -> None:
        with self._lock:
            self._expected_running = False
            self._stop_listeners()

    def is_healthy(self) -> bool:
        with self._lock:
            if not self._expected_running:
                return True
            listeners = [self._keyboard] + ([self._mouse] if self._mouse is not None else [])
            return all(
                listener is not None and listener.is_alive() and listener.running
                for listener in listeners
            )

    def on_state_change(self, locked: bool) -> None:
        with self._lock:
            if not self._expected_running:
                return
            want = self._want_grab()
            if want == self._grabbing:
                return
            log.debug("Swapping listeners (grab=%s)", want)
            self._stop_listeners()
            self._start_listeners(want)

    # -- helpers -----------------------------------------------------------

    def _want_grab(self) -> bool:
        return self.engine.locked and not self.engine.dry_run

    def _start_listeners(self, grab: bool) -> None:
        try:
            from pynput import keyboard, mouse
        except Exception as exc:  # pragma: no cover - import guard
            raise BackendError(
                f"Could not load the input library (pynput): {exc}. On Linux PawLock needs "
                "an X11 session (Wayland blocks global input hooks)."
            ) from exc

        self._keyboard = keyboard.Listener(
            on_press=self._on_press, on_release=self._on_release, suppress=grab
        )
        self._keyboard.name = "keyboard-listener"
        self._keyboard.start()
        self._keyboard.wait()

        # The mouse is only grabbed when lock_mouse is on; while unlocked we
        # still listen so the (optional) click-storm rule can work.
        mouse_grab = grab and self.engine.lock_mouse
        self._mouse = mouse.Listener(on_click=self._on_click, suppress=mouse_grab)
        self._mouse.name = "mouse-listener"
        self._mouse.start()
        self._mouse.wait()
        self._grabbing = grab

    def _stop_listeners(self) -> None:
        for listener in (self._keyboard, self._mouse):
            if listener is not None:
                try:
                    listener.stop()
                except Exception:  # pragma: no cover - best effort
                    log.exception("Error while stopping a listener")
        self._keyboard = self._mouse = None
        self._grabbing = False

    # -- callbacks (pynput threads) -----------------------------------------

    def _on_press(self, key: Any, injected: bool = False) -> None:
        if not injected:
            self.engine.handle_key(keys.from_pynput(key), True)

    def _on_release(self, key: Any, injected: bool = False) -> None:
        if not injected:
            self.engine.handle_key(keys.from_pynput(key), False)

    def _on_click(self, x: int, y: int, button: Any, pressed: bool, injected: bool = False) -> None:
        if not injected:
            self.engine.handle_mouse_button(getattr(button, "name", str(button)), pressed)
