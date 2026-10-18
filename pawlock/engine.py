"""The lock engine: the single place that decides what happens to every event.

The platform backends call :meth:`LockEngine.handle_key` and friends from
inside the operating system's input hook, once per event, and the engine
answers one question: *should this event be swallowed?*

Design rules
------------
**Fast and boring.** These methods run inside a system-wide input hook.
Windows silently removes a low-level hook that takes too long, and macOS
disables a slow event tap. So the engine does O(1)-ish bookkeeping under a
lock and never blocks, sleeps or does I/O. Anything slow (sounds, the
overlay, swapping listeners) is handed to the controller thread via the
``on_change`` callback, which must only enqueue.

**Fail open.** If anything inside the engine raises, the event is let
through and the lock is released. A bug must never leave you without a
keyboard.

**Balanced suppression.** A key release is swallowed *only if* the matching
press was swallowed. Without this, a key that went down while unlocked and
came up while locked would be "stuck" from the OS's point of view (Ctrl
held forever, mouse button still dragging). The same applies to mouse
buttons.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional

from .detector import CatDetector, DetectorSettings
from .hotkey import Hotkey, PhraseMatcher

log = logging.getLogger(__name__)

# Why the lock state changed. Shown in the log and in the overlay.
REASON_HOTKEY = "hotkey"
REASON_PHRASE = "phrase"
REASON_AUTO = "auto"          # the cat detector fired
REASON_MANUAL = "manual"      # tray menu
REASON_STARTUP = "startup"    # start_locked / --lock / --practice
REASON_TIMEOUT = "timeout"    # max_lock_minutes reached
REASON_SAFETY = "safety"      # watchdog / crash guard / internal error
REASON_SHUTDOWN = "shutdown"


@dataclass(frozen=True)
class StateChange:
    """Emitted every time the engine locks or unlocks."""

    locked: bool
    reason: str
    detail: str = ""
    dry_run: bool = False
    at: float = field(default_factory=time.time)


class LockEngine:
    """Thread-safe lock state machine shared by all input hooks.

    Parameters
    ----------
    hotkey:
        The combination that toggles the lock.
    unlock_phrase:
        Word that unlocks when typed while locked ("" disables it).
    detector:
        Optional :class:`~pawlock.detector.CatDetector` for automatic locking.
    lock_mouse:
        Also block mouse / trackpad input while locked.
    stale_key_seconds:
        Forget a held key if we hear nothing from it for this long (its
        release was probably lost, e.g. to the Windows secure desktop).
    cooldown_seconds:
        After an unlock, ignore the detector for this long so the keys you
        were just pressing don't immediately re-lock the machine.
    dry_run:
        Go through all the motions but never actually swallow anything.
    on_change:
        Called with a :class:`StateChange` after every transition. It runs
        inside the input hook, so it must return immediately.
    clock:
        Monotonic clock (injectable for tests).
    """

    def __init__(
        self,
        hotkey: Hotkey,
        *,
        unlock_phrase: str = "",
        detector: Optional[CatDetector] = None,
        auto_detect: bool = True,
        lock_mouse: bool = True,
        stale_key_seconds: float = 10.0,
        cooldown_seconds: float = 5.0,
        dry_run: bool = False,
        on_change: Optional[Callable[[StateChange], None]] = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._mutex = threading.RLock()
        self._clock = clock
        self._on_change = on_change

        self.hotkey = hotkey
        self._phrase = PhraseMatcher(unlock_phrase)
        self._detector = detector
        self.auto_detect = auto_detect
        self.lock_mouse = lock_mouse
        self.stale_key_seconds = stale_key_seconds
        self.cooldown_seconds = cooldown_seconds
        self.dry_run = dry_run

        # Plain attribute reads/writes of a bool are atomic in CPython, which
        # lets the hot mouse-move path and the emergency path skip the mutex.
        self._locked = False
        self._locked_since: Optional[float] = None
        self._cooldown_until = 0.0

        self._held: Dict[str, float] = {}             # key -> last time seen down
        self._key_delivered: Dict[str, bool] = {}     # key -> did its press reach the OS?
        self._button_delivered: Dict[str, bool] = {}  # mouse button -> same question

    # ------------------------------------------------------------------
    # Read-only state
    # ------------------------------------------------------------------

    @property
    def locked(self) -> bool:
        return self._locked

    @property
    def locked_since(self) -> Optional[float]:
        """Monotonic time the current lock began (``None`` while unlocked)."""
        return self._locked_since

    @property
    def unlock_phrase(self) -> str:
        return "".join(self._phrase.phrase)

    def is_held(self, key: str) -> bool:
        with self._mutex:
            return key in self._held

    # ------------------------------------------------------------------
    # Commands (tray menu, CLI, timers, safety net)
    # ------------------------------------------------------------------

    def lock(self, reason: str = REASON_MANUAL, detail: str = "") -> None:
        with self._mutex:
            self._set_locked(True, reason, detail)

    def unlock(self, reason: str = REASON_MANUAL, detail: str = "") -> None:
        with self._mutex:
            self._set_locked(False, reason, detail)

    def try_unlock(self, reason: str, detail: str = "", timeout: float = 1.0) -> None:
        """Unlock politely if possible, forcibly if the mutex is wedged."""
        if self._mutex.acquire(timeout=timeout):
            try:
                self._set_locked(False, reason, detail)
            finally:
                self._mutex.release()
        else:
            self.force_unlock(reason, detail)

    def force_unlock(self, reason: str = REASON_SAFETY, detail: str = "") -> None:
        """Emergency release that works even if another thread holds the mutex.

        Used by the watchdog, crash handlers and signal handlers. It flips the
        flag without locking (an atomic store), so every hook stops swallowing
        events on the very next event.
        """
        was_locked = self._locked
        self._locked = False
        self._locked_since = None
        if was_locked:
            self._notify(StateChange(False, reason, detail, self.dry_run))

    def reconfigure(
        self,
        *,
        hotkey: Optional[Hotkey] = None,
        unlock_phrase: Optional[str] = None,
        lock_mouse: Optional[bool] = None,
        cooldown_seconds: Optional[float] = None,
        stale_key_seconds: Optional[float] = None,
        detector_settings: Optional[DetectorSettings] = None,
    ) -> None:
        """Apply new settings without restarting (tray: "Reload settings")."""
        with self._mutex:
            if detector_settings is not None and self._detector is not None:
                self._detector.update_settings(detector_settings)
            if hotkey is not None:
                self.hotkey = hotkey
            if unlock_phrase is not None:
                self._phrase = PhraseMatcher(unlock_phrase)
            if lock_mouse is not None:
                self.lock_mouse = lock_mouse
            if cooldown_seconds is not None:
                self.cooldown_seconds = cooldown_seconds
            if stale_key_seconds is not None:
                self.stale_key_seconds = stale_key_seconds

    # ------------------------------------------------------------------
    # Event handlers, called from the input hooks
    # ------------------------------------------------------------------

    def handle_key(self, key: str, pressed: bool) -> bool:
        """Process one keyboard event; return True to swallow it."""
        try:
            with self._mutex:
                return self._handle_key(key, pressed)
        except Exception:  # pragma: no cover - defensive
            log.exception("Internal error while handling a key event; failing open")
            self.force_unlock(REASON_SAFETY, "internal error")
            return False

    def handle_mouse_motion(self) -> bool:
        """Mouse move / drag / scroll / trackpad swipe; return True to swallow.

        This is the hottest path (a gaming mouse reports 1000 moves a second),
        so it reads two attributes and nothing else.
        """
        return self._locked and self.lock_mouse and not self.dry_run

    def handle_other_key_event(self) -> bool:
        """Keyboard events that aren't a plain key (media keys, brightness...).

        They can't take part in the hotkey, so simply: swallow while locked.
        """
        return self._locked and not self.dry_run

    def handle_mouse_button(self, button: str, pressed: bool) -> bool:
        """Mouse or trackpad click; return True to swallow."""
        try:
            with self._mutex:
                return self._handle_button(button, pressed)
        except Exception:  # pragma: no cover - defensive
            log.exception("Internal error while handling a click; failing open")
            self.force_unlock(REASON_SAFETY, "internal error")
            return False

    def tick(self) -> None:
        """Periodic housekeeping (time-based detector rules). Called ~4x/second."""
        try:
            with self._mutex:
                now = self._clock()
                self._expire_stale(now)
                if not self._locked and self._detection_active(now):
                    detection = self._detector.tick(now)
                    if detection is not None:
                        self._set_locked(True, REASON_AUTO, detection.reason)
        except Exception:  # pragma: no cover - defensive
            log.exception("Internal error in engine tick")

    # ------------------------------------------------------------------
    # Internals (mutex held)
    # ------------------------------------------------------------------

    def _swallow(self, decision: bool) -> bool:
        return decision and not self.dry_run

    def _detection_active(self, now: float) -> bool:
        return self._detector is not None and self.auto_detect and now >= self._cooldown_until

    def _handle_key(self, key: str, pressed: bool) -> bool:
        now = self._clock()
        self._expire_stale(now)

        if not pressed:
            return self._handle_key_release(key, now)

        repeat = key in self._held
        self._held[key] = now

        if repeat:
            # Operating-system auto-repeat of a key that's already down.
            # Follow the fate of the original press: keep it swallowed if it
            # was swallowed; while locked, swallow everything.
            if not self._locked and self._detection_active(now):
                detection = self._detector.on_key(key, True, now)
                if detection is not None:
                    self._set_locked(True, REASON_AUTO, detection.reason)
            if self._locked:
                return self._swallow(True)
            return self._swallow(not self._key_delivered.get(key, True))

        # A fresh press. First: is it the hotkey? (Checked in both states;
        # this is how the hotkey "bypasses" the suppression.)
        if self.hotkey.matches(self._held, key):
            self._set_locked(not self._locked, REASON_HOTKEY)
            self._key_delivered[key] = False  # Keep the combo away from apps.
            return self._swallow(True)

        if self._locked:
            if self._phrase.feed(key):
                self._set_locked(False, REASON_PHRASE)
            self._key_delivered[key] = False
            return self._swallow(True)

        if self._detection_active(now):
            detection = self._detector.on_key(key, True, now)
            if detection is not None:
                self._set_locked(True, REASON_AUTO, detection.reason)
                self._key_delivered[key] = False
                return self._swallow(True)

        self._key_delivered[key] = True
        return False

    def _handle_key_release(self, key: str, now: float) -> bool:
        self._held.pop(key, None)
        if self._detector is not None:
            self._detector.on_key(key, False, now)
        delivered = self._key_delivered.pop(key, None)
        # Swallow the release only if we swallowed the press. A release we
        # have no record of (pressed before PawLock started) is let through:
        # a stray key-up is harmless, a stuck key is not.
        return self._swallow(delivered is False)

    def _handle_button(self, button: str, pressed: bool) -> bool:
        if not pressed:
            delivered = self._button_delivered.pop(button, None)
            return self._swallow(delivered is False)

        swallow = self._locked and self.lock_mouse
        if not self._locked:
            now = self._clock()
            if self._detection_active(now):
                detection = self._detector.on_click(now)
                if detection is not None:
                    self._set_locked(True, REASON_AUTO, detection.reason)
                    swallow = self.lock_mouse
        self._button_delivered[button] = not swallow
        return self._swallow(swallow)

    def _expire_stale(self, now: float) -> None:
        if self.stale_key_seconds <= 0 or not self._held:
            return
        for key, seen in list(self._held.items()):
            if now - seen > self.stale_key_seconds:
                del self._held[key]
                if self._detector is not None:
                    self._detector.forget(key)

    def _set_locked(self, locked: bool, reason: str, detail: str = "") -> None:
        if locked == self._locked:
            return
        now = self._clock()
        self._locked = locked
        if locked:
            self._locked_since = now
            self._phrase.reset()
        else:
            self._locked_since = None
            self._cooldown_until = now + self.cooldown_seconds
        if self._detector is not None:
            self._detector.reset()
        self._notify(StateChange(locked, reason, detail, self.dry_run))

    def _notify(self, change: StateChange) -> None:
        if self._on_change is None:
            return
        try:
            self._on_change(change)
        except Exception:  # pragma: no cover - defensive
            log.exception("State-change listener failed")
