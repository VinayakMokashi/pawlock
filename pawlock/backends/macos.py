"""macOS backend: Quartz event taps with per-event suppression.

pynput creates a ``CGEventTap`` for keyboard events and another for mouse
events. When we pass ``darwin_intercept``, the tap is created in *active*
mode and our function decides the fate of every event: return the event to
let it through, or ``None`` to swallow it.

Requirements: the app (or the Terminal running it) must be allowed under
System Settings -> Privacy & Security -> **Accessibility** and **Input
Monitoring**. Without them macOS silently gives us no events.

Built-in macOS safety nets this backend relies on:

* If a tap callback is too slow, macOS disables the tap
  (``kCGEventTapDisabledByTimeout``). Input flows again, and we notice and
  restart the hooks.
* Taps vanish when the process exits.

Known limitation: trackpad *gestures* (pinch, three-finger swipes) are
delivered as gesture events that pynput's taps don't subscribe to, so a cat
can still trigger Mission Control. Clicks, taps, pointer movement and
scrolling are all blocked.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

from .. import keys
from .base import BackendError, InputBackend, wait_until_ready

log = logging.getLogger(__name__)

# CGEventType values (stable since macOS 10.4).
KEY_DOWN = 10
KEY_UP = 11
FLAGS_CHANGED = 12
LEFT_MOUSE_DOWN, LEFT_MOUSE_UP = 1, 2
RIGHT_MOUSE_DOWN, RIGHT_MOUSE_UP = 3, 4
OTHER_MOUSE_DOWN, OTHER_MOUSE_UP = 25, 26
TAP_DISABLED_BY_TIMEOUT = 0xFFFFFFFE
TAP_DISABLED_BY_USER_INPUT = 0xFFFFFFFF

_BUTTON_EVENTS = {
    LEFT_MOUSE_DOWN: ("left", True),
    LEFT_MOUSE_UP: ("left", False),
    RIGHT_MOUSE_DOWN: ("right", True),
    RIGHT_MOUSE_UP: ("right", False),
    OTHER_MOUSE_DOWN: ("middle", True),
    OTHER_MOUSE_UP: ("middle", False),
}

# CGEventFlags bit for each modifier family.
_MODIFIER_MASKS = {
    "shift": 0x00020000,  # kCGEventFlagMaskShift
    "ctrl": 0x00040000,   # kCGEventFlagMaskControl
    "alt": 0x00080000,    # kCGEventFlagMaskAlternate
    "cmd": 0x00100000,    # kCGEventFlagMaskCommand
}

# Event fields.
KEYBOARD_EVENT_KEYCODE = 9        # kCGKeyboardEventKeycode
EVENT_SOURCE_UNIX_PROCESS_ID = 41  # kCGEventSourceUnixProcessID


class MacBackend(InputBackend):
    name = "macos-event-taps"
    selective = True

    def __init__(self, engine, quartz: Optional[Any] = None) -> None:
        super().__init__(engine)
        self._quartz = quartz  # Injectable for tests.
        self._keyboard: Optional[Any] = None
        self._mouse: Optional[Any] = None
        self._tap_disabled = False

    # -- lifecycle -------------------------------------------------------

    def start(self) -> None:
        try:
            if self._quartz is None:
                import Quartz  # type: ignore[import-not-found]

                self._quartz = Quartz
            from pynput import keyboard, mouse
        except Exception as exc:  # pragma: no cover - import guard
            raise BackendError(f"Could not load the input library (pynput/Quartz): {exc}") from exc

        self._tap_disabled = False
        self._keyboard = keyboard.Listener(darwin_intercept=self.keyboard_intercept)
        self._mouse = mouse.Listener(darwin_intercept=self.mouse_intercept)
        self._keyboard.name = "keyboard-tap"
        self._mouse.name = "mouse-tap"
        self._keyboard.start()
        self._mouse.start()
        wait_until_ready(self._keyboard)
        wait_until_ready(self._mouse)
        # Without Input Monitoring permission the tap can't be created: pynput
        # reports "ready" and its thread ends straight away. Give it a moment.
        time.sleep(0.3)
        if not getattr(self._keyboard, "IS_TRUSTED", True) or not self.is_healthy():
            self.stop()
            raise BackendError(
                "macOS has not allowed PawLock to monitor input yet. Open System Settings > "
                "Privacy & Security and enable PawLock (or your Terminal) under both "
                "'Accessibility' and 'Input Monitoring', then start PawLock again."
            )
        log.info("Quartz keyboard and mouse event taps installed")

    def stop(self) -> None:
        for listener in (self._keyboard, self._mouse):
            if listener is not None:
                try:
                    listener.stop()
                except Exception:  # pragma: no cover - best effort
                    log.exception("Error while stopping an event tap")
        self._keyboard = self._mouse = None

    def is_healthy(self) -> bool:
        if self._tap_disabled:
            return False
        return all(
            listener is not None and listener.is_alive() and listener.running
            for listener in (self._keyboard, self._mouse)
        )

    # -- intercepts (run inside the tap: keep them fast) --------------------

    def _injected(self, event: Any) -> bool:
        # Hardware events carry no Unix PID; synthetic ones carry their sender's.
        q = self._quartz
        field = getattr(q, "kCGEventSourceUnixProcessID", EVENT_SOURCE_UNIX_PROCESS_ID)
        return q.CGEventGetIntegerValueField(event, field) != 0

    def keyboard_intercept(self, event_type: int, event: Any) -> Optional[Any]:
        """``darwin_intercept`` for the keyboard tap."""
        if event_type in (TAP_DISABLED_BY_TIMEOUT, TAP_DISABLED_BY_USER_INPUT):
            log.warning("macOS disabled the keyboard event tap; it will be restarted")
            self._tap_disabled = True
            return event
        try:
            if self._injected(event):
                return event
            q = self._quartz
            if event_type not in (KEY_DOWN, KEY_UP, FLAGS_CHANGED):
                # Media/system keys and anything else: blocked only while locked.
                return None if self.engine.handle_other_key_event() else event
            key = keys.from_mac_keycode(
                q.CGEventGetIntegerValueField(
                    event, getattr(q, "kCGKeyboardEventKeycode", KEYBOARD_EVENT_KEYCODE)
                )
            )
            if event_type == KEY_DOWN:
                pressed = True
            elif event_type == KEY_UP:
                pressed = False
            elif key == "caps_lock":
                # macOS only reports caps-lock toggles: fake a press + release.
                swallow = self.engine.handle_key(key, True)
                self.engine.handle_key(key, False)
                return None if swallow else event
            else:
                mask = _MODIFIER_MASKS.get(keys.modifier_base(key))
                if mask is None:
                    return event  # fn and friends: leave alone.
                flag_set = bool(q.CGEventGetFlags(event) & mask)
                # Flag set + key not yet held = press. Anything else is a
                # release (also covers releasing one Shift while the other
                # Shift is still down, which keeps the flag set).
                pressed = flag_set and not self.engine.is_held(key)
        except Exception:
            log.exception("Could not decode a keyboard event; letting it through")
            return event
        return None if self.engine.handle_key(key, pressed) else event

    def mouse_intercept(self, event_type: int, event: Any) -> Optional[Any]:
        """``darwin_intercept`` for the mouse tap (covers the trackpad)."""
        if event_type in (TAP_DISABLED_BY_TIMEOUT, TAP_DISABLED_BY_USER_INPUT):
            log.warning("macOS disabled the mouse event tap; it will be restarted")
            self._tap_disabled = True
            return event
        try:
            if self._injected(event):
                return event
            if event_type in _BUTTON_EVENTS:
                button, pressed = _BUTTON_EVENTS[event_type]
                swallow = self.engine.handle_mouse_button(button, pressed)
            else:
                swallow = self.engine.handle_mouse_motion()  # moves, drags, scrolls
        except Exception:
            log.exception("Could not decode a mouse event; letting it through")
            return event
        return None if swallow else event
