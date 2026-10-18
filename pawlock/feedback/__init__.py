"""Telling the human what's going on: tray icon, banner, sounds, notifications.

Each channel is optional and independent. If one fails (no tray on this
desktop, no Tk, no speakers) the others carry on. :class:`FeedbackHub`
turns a :class:`~pawlock.engine.StateChange` into the right message for
each channel.
"""

from __future__ import annotations

import logging
from typing import Any, Optional, Tuple

from ..engine import (
    REASON_AUTO,
    REASON_SAFETY,
    REASON_SHUTDOWN,
    REASON_TIMEOUT,
    StateChange,
)
from .sound import SoundPlayer

log = logging.getLogger(__name__)


def unlock_instructions(hotkey_text: str, phrase: str) -> str:
    text = f"Unlock: press {hotkey_text}"
    if phrase:
        text += f"  or type “{phrase}”"
    return text


def describe(change: StateChange, hotkey_text: str, phrase: str) -> Tuple[str, str]:
    """(title, body) for the banner and notifications."""
    how = unlock_instructions(hotkey_text, phrase)
    if change.locked:
        if change.dry_run:
            title = "Dry run: PawLock would lock now"
            body = (change.detail + ". " if change.detail else "") + "Nothing is blocked in dry-run mode."
        elif change.reason == REASON_AUTO:
            title = "Cat detected! Keyboard & trackpad locked"
            body = f"{change.detail[:1].upper()}{change.detail[1:]}.\n{how}"
        else:
            title = "Locked: paws off!"
            body = f"{change.detail}.\n{how}" if change.detail else how
        return title, body
    if change.dry_run:
        return "Dry run: back to watching", "Nothing was blocked."
    if change.reason == REASON_TIMEOUT:
        return "Unlocked automatically", "The maximum lock time was reached."
    if change.reason == REASON_SAFETY:
        return "Unlocked for safety", change.detail or "PawLock released the lock to be safe."
    return "Unlocked: welcome back", "Keyboard and trackpad are working again."


class FeedbackHub:
    def __init__(self, sound: SoundPlayer, notifications: bool = True) -> None:
        self.sound = sound
        self.notifications = notifications
        self.tray: Optional[Any] = None     # TrayIcon, attached by the app
        self.overlay: Optional[Any] = None  # Overlay, attached by the app

    def tray_state(self, locked: bool, dry_run: bool, auto_detect: bool) -> str:
        if locked:
            return "dry_run" if dry_run else "locked"
        return "watching" if auto_detect else "paused"

    def refresh_tray(self, locked: bool, dry_run: bool, auto_detect: bool, tooltip: str) -> None:
        if self.tray is not None:
            self.tray.set_state(self.tray_state(locked, dry_run, auto_detect), tooltip)

    def notify(self, message: str, title: str = "PawLock") -> None:
        if self.notifications and self.tray is not None:
            self.tray.notify(message, title)

    def state_changed(
        self, change: StateChange, *, hotkey_text: str, phrase: str, auto_detect: bool, tooltip: str
    ) -> None:
        """Fan a lock/unlock out to every channel. Runs on the controller thread."""
        title, body = describe(change, hotkey_text, phrase)
        self.refresh_tray(change.locked, change.dry_run, auto_detect, tooltip)

        if self.overlay is not None:
            if change.locked:
                self.overlay.show_locked(title, body, "dry_run" if change.dry_run else "locked")
            elif change.reason == REASON_SHUTDOWN:
                self.overlay.hide()
            else:
                self.overlay.flash(title, body, "unlocked")

        if change.reason != REASON_SHUTDOWN:
            if change.locked:
                self.sound.play("cat" if change.reason == REASON_AUTO else "lock")
            else:
                self.sound.play("unlock")

        if change.locked and change.reason == REASON_AUTO:
            self.notify(f"{title}. {unlock_instructions(hotkey_text, phrase)}")
        elif not change.locked and change.reason in (REASON_SAFETY, REASON_TIMEOUT):
            self.notify(f"{title}. {body}")
