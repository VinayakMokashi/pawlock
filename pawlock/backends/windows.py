"""Windows backend: low-level hooks with per-event suppression.

pynput installs ``WH_KEYBOARD_LL`` / ``WH_MOUSE_LL`` hooks and, if we pass a
``win32_event_filter``, calls it for every event *before* doing anything
else. Inside the filter we:

1. translate the raw event (virtual-key code / mouse message),
2. ask the :class:`~pawlock.engine.LockEngine` whether to swallow it,
3. call ``listener.suppress_event()`` to swallow it (pynput implements this
   by raising an exception that makes the hook return 1, so Windows drops
   the event), or return ``False`` to let it continue to the apps.

Returning ``False`` also tells pynput not to bother running its own
callbacks. We've handled the event and don't need them, which keeps the
hook as fast as possible.

Built-in Windows safety nets this backend relies on:

* **Ctrl + Alt + Del** is handled by the kernel and can never be blocked.
  From there, Task Manager can end PawLock.
* If the hook thread ever hangs, Windows skips the hook after a timeout
  (``LowLevelHooksTimeout``) and eventually removes it. Input is never
  blocked by a frozen PawLock.
* When the process exits for any reason, Windows removes its hooks.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from .. import keys
from .base import BackendError, InputBackend, wait_until_ready

log = logging.getLogger(__name__)

# Keyboard messages (wParam of the low-level hook).
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105

# KBDLLHOOKSTRUCT.flags: event synthesised by software (SendInput & co).
LLKHF_LOWER_IL_INJECTED = 0x02
LLKHF_INJECTED = 0x10

# Mouse messages.
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_MBUTTONDOWN = 0x0207
WM_MBUTTONUP = 0x0208
WM_MOUSEWHEEL = 0x020A
WM_XBUTTONDOWN = 0x020B
WM_XBUTTONUP = 0x020C
WM_MOUSEHWHEEL = 0x020E

# MSLLHOOKSTRUCT.flags
LLMHF_INJECTED = 0x01
LLMHF_LOWER_IL_INJECTED = 0x02

_BUTTON_DOWN = {WM_LBUTTONDOWN: "left", WM_RBUTTONDOWN: "right", WM_MBUTTONDOWN: "middle"}
_BUTTON_UP = {WM_LBUTTONUP: "left", WM_RBUTTONUP: "right", WM_MBUTTONUP: "middle"}


class WindowsBackend(InputBackend):
    name = "windows-low-level-hooks"
    selective = True

    def __init__(self, engine) -> None:
        super().__init__(engine)
        self._keyboard: Optional[Any] = None
        self._mouse: Optional[Any] = None

    # -- lifecycle -------------------------------------------------------

    def start(self) -> None:
        try:
            from pynput import keyboard, mouse
        except Exception as exc:  # pragma: no cover - import guard
            raise BackendError(f"Could not load the input library (pynput): {exc}") from exc

        self._keyboard = keyboard.Listener(win32_event_filter=self.keyboard_filter)
        self._mouse = mouse.Listener(win32_event_filter=self.mouse_filter)
        self._keyboard.name = "keyboard-hook"
        self._mouse.name = "mouse-hook"
        self._keyboard.start()
        self._mouse.start()
        wait_until_ready(self._keyboard)
        wait_until_ready(self._mouse)
        if not self.is_healthy():
            self.stop()
            raise BackendError("Windows refused to install the input hooks")
        log.info("Low-level keyboard and mouse hooks installed")

    def stop(self) -> None:
        for listener in (self._keyboard, self._mouse):
            if listener is not None:
                try:
                    listener.stop()
                except Exception:  # pragma: no cover - best effort
                    log.exception("Error while stopping a hook")
        self._keyboard = self._mouse = None

    def is_healthy(self) -> bool:
        return all(
            listener is not None and listener.is_alive() and listener.running
            for listener in (self._keyboard, self._mouse)
        )

    # -- the hook filters (run inside the hook: keep them fast) --------------

    def keyboard_filter(self, msg: int, data: Any) -> bool:
        """``win32_event_filter`` for the keyboard listener."""
        if data.flags & (LLKHF_INJECTED | LLKHF_LOWER_IL_INJECTED):
            # Synthetic input (on-screen keyboards, remote-desktop tools,
            # automation) isn't a cat. Let it through so remote help works.
            return False
        if msg in (WM_KEYDOWN, WM_SYSKEYDOWN):
            pressed = True
        elif msg in (WM_KEYUP, WM_SYSKEYUP):
            pressed = False
        else:
            return False
        if self.engine.handle_key(keys.from_windows_vk(data.vkCode), pressed):
            self._suppress(self._keyboard)
        return False

    def mouse_filter(self, msg: int, data: Any) -> bool:
        """``win32_event_filter`` for the mouse listener (covers trackpads too)."""
        if data.flags & (LLMHF_INJECTED | LLMHF_LOWER_IL_INJECTED):
            return False
        if msg in _BUTTON_DOWN:
            swallow = self.engine.handle_mouse_button(_BUTTON_DOWN[msg], True)
        elif msg in _BUTTON_UP:
            swallow = self.engine.handle_mouse_button(_BUTTON_UP[msg], False)
        elif msg in (WM_XBUTTONDOWN, WM_XBUTTONUP):
            button = f"x{(data.mouseData >> 16) & 0xFFFF}"
            swallow = self.engine.handle_mouse_button(button, msg == WM_XBUTTONDOWN)
        else:
            # Moves, wheel and horizontal wheel (two-finger trackpad scrolls).
            swallow = self.engine.handle_mouse_motion()
        if swallow:
            self._suppress(self._mouse)
        return False

    @staticmethod
    def _suppress(listener: Optional[Any]) -> None:
        if listener is not None:
            listener.suppress_event()  # Raises; pynput turns that into "drop it".
