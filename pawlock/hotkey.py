"""The two deliberate, human-only ways to toggle the lock.

1. **The hotkey** (default ``Ctrl + Alt + Shift + L``) toggles the lock.
2. **The unlock phrase** (default ``unlock``) typed while locked unlocks.

Both are checked inside the input hook itself, *before* PawLock decides
whether to swallow an event. That is how they "bypass" the suppression: the
keys never reach your apps, but PawLock still sees them.

Why a cat can't trigger them
----------------------------
* The hotkey must be matched **exactly**. If anything other than the four
  hotkey keys is held down, it does not count. A cat lying across the
  keyboard is holding a *superset* of the hotkey, so it can never match.
* The non-modifier key (``L``) must be the **last** key pressed, after the
  modifiers, which is the natural human order and an unnatural paw order.
* The unlock phrase must be typed as an exact sequence of separate key
  presses. The odds of a cat typing a specific six-letter word in order are
  about 1 in 300 million per attempt.
"""

from __future__ import annotations

import re
import sys
from collections import deque
from dataclasses import dataclass
from typing import FrozenSet, Iterable, List

from .keys import DIGITS, KNOWN_KEYS, LETTERS, is_modifier, modifier_base

#: Words people use for modifiers -> PawLock's modifier family.
_MODIFIER_ALIASES = {
    "ctrl": "ctrl", "control": "ctrl", "ctl": "ctrl", "strg": "ctrl",
    "alt": "alt", "option": "alt", "opt": "alt", "altgr": "alt",
    "shift": "shift",
    "cmd": "cmd", "command": "cmd", "win": "cmd", "windows": "cmd",
    "super": "cmd", "meta": "cmd",
}

#: Friendly spellings for trigger keys -> canonical key names.
_KEY_ALIASES = {
    "return": "enter", "escape": "esc", "spacebar": "space",
    "pgup": "page_up", "pageup": "page_up", "pgdn": "page_down",
    "pagedown": "page_down", "del": "delete", "ins": "insert",
    "bksp": "backspace", "back": "backspace", "printscreen": "print_screen",
    "prtsc": "print_screen", "capslock": "caps_lock", "scrolllock": "scroll_lock",
    "numlock": "num_lock", "minus": "-", "equals": "=", "equal": "=",
    "comma": ",", "period": ".", "dot": ".", "slash": "/", "backslash": "\\",
    "semicolon": ";", "quote": "'", "apostrophe": "'", "grave": "`",
    "backtick": "`", "tilde": "`", "lbracket": "[", "rbracket": "]",
}

#: Keys that are too big or too central to be a safe trigger.
_PAW_MAGNETS = frozenset({"space", "enter", "backspace", "tab", "caps_lock"})

_MODIFIER_ORDER = ("ctrl", "alt", "shift", "cmd")


def _modifier_label(name: str, platform: str) -> str:
    if platform == "darwin":
        return {"ctrl": "Control", "alt": "Option", "shift": "Shift", "cmd": "Command"}[name]
    if platform == "win32":
        return {"ctrl": "Ctrl", "alt": "Alt", "shift": "Shift", "cmd": "Win"}[name]
    return {"ctrl": "Ctrl", "alt": "Alt", "shift": "Shift", "cmd": "Super"}[name]


def _key_label(name: str) -> str:
    if len(name) == 1:
        return name.upper()
    if name.startswith("f") and name[1:].isdigit():
        return name.upper()
    return name.replace("_", " ").title()


@dataclass(frozen=True)
class Hotkey:
    """A modifier combination such as Ctrl + Alt + Shift + L."""

    modifiers: FrozenSet[str]
    trigger: str

    @classmethod
    def parse(cls, text: str) -> Hotkey:
        """Parse ``"ctrl+alt+shift+l"`` (case and spacing don't matter).

        Raises ``ValueError`` with a human-readable message on bad input.
        """
        if not isinstance(text, str) or not text.strip():
            raise ValueError("the hotkey is empty")
        parts = [p.strip().lower() for p in re.split(r"\+", text.strip())]
        modifiers = set()
        triggers: List[str] = []
        for part in parts:
            if not part:
                raise ValueError(f"{text!r} has an empty key (use '=' instead of '+')")
            if part in _MODIFIER_ALIASES:
                family = _MODIFIER_ALIASES[part]
                if family in modifiers:
                    raise ValueError(f"{text!r} lists {family!r} twice")
                modifiers.add(family)
                continue
            name = _KEY_ALIASES.get(part, part)
            if name not in KNOWN_KEYS:
                raise ValueError(f"{part!r} is not a key PawLock knows")
            triggers.append(name)
        if len(triggers) != 1:
            raise ValueError(
                f"{text!r} needs exactly one non-modifier key (like L), found {len(triggers)}"
            )
        if not modifiers:
            raise ValueError(f"{text!r} needs at least one modifier (Ctrl, Alt, Shift, Cmd/Win)")
        return cls(frozenset(modifiers), triggers[0])

    @property
    def keys(self) -> FrozenSet[str]:
        """Every key in the combination, modifiers by family (``ctrl`` not ``ctrl_l``)."""
        return self.modifiers | {self.trigger}

    def matches(self, held: Iterable[str], pressed: str) -> bool:
        """Did pressing *pressed* just complete this hotkey?

        *held* is every key currently down, including *pressed*. The match is
        exact: one key too many (a paw on the space bar, say) and it fails.
        """
        if pressed != self.trigger:
            return False
        held = list(held)
        if len(held) != len(self.keys):
            return False
        return {modifier_base(k) for k in held} == self.keys

    def warnings(self) -> List[str]:
        """Advice for hotkeys that are easier for a cat to hit by accident."""
        advice = []
        if len(self.modifiers) < 2:
            advice.append(
                "it has fewer than two modifiers, so a paw could press it by accident; "
                "Ctrl+Alt+Shift+<key> is recommended"
            )
        if self.trigger in _PAW_MAGNETS:
            advice.append(f"{_key_label(self.trigger)} is a big key that paws land on often")
        if "cmd" in self.modifiers and sys.platform == "win32":
            advice.append("Windows reserves many Win-key shortcuts (Win+L locks the PC)")
        return advice

    def display(self, platform: str = sys.platform) -> str:
        """Human-friendly label, e.g. ``"Ctrl + Alt + Shift + L"``."""
        labels = [_modifier_label(m, platform) for m in _MODIFIER_ORDER if m in self.modifiers]
        return " + ".join(labels + [_key_label(self.trigger)])

    def __str__(self) -> str:
        ordered = [m for m in _MODIFIER_ORDER if m in self.modifiers]
        return "+".join(ordered + [self.trigger])


class PhraseMatcher:
    """Spots a secret word typed while the computer is locked.

    This is the backup way out, for example on laptop keyboards that can't
    register four keys at once (a hardware limit called "ghosting"). Modifier
    keys are ignored, so typing ``Unlock`` with Shift held still works. Any
    other non-character key (Enter, arrows, space...) starts the sequence over.
    """

    MIN_LENGTH = 4
    MAX_LENGTH = 32

    def __init__(self, phrase: str = "") -> None:
        self.phrase = tuple(self.validate(phrase))
        self._buffer: deque = deque(maxlen=max(len(self.phrase), 1))

    @classmethod
    def validate(cls, phrase: str) -> str:
        """Return the normalised phrase, or raise ``ValueError``. Empty disables it."""
        if not isinstance(phrase, str):
            raise ValueError("the unlock phrase must be text")
        phrase = phrase.strip().lower()
        if not phrase:
            return ""
        if not all(c in LETTERS or c in DIGITS for c in phrase):
            raise ValueError("the unlock phrase may only contain letters a-z and digits")
        if not cls.MIN_LENGTH <= len(phrase) <= cls.MAX_LENGTH:
            raise ValueError(
                f"the unlock phrase must be {cls.MIN_LENGTH}-{cls.MAX_LENGTH} characters long"
            )
        return phrase

    @property
    def enabled(self) -> bool:
        return bool(self.phrase)

    def reset(self) -> None:
        self._buffer.clear()

    def feed(self, key: str) -> bool:
        """Record one fresh key press; True when the phrase has just been completed."""
        if not self.phrase or is_modifier(key):
            return False
        if len(key) == 1 and (key in LETTERS or key in DIGITS):
            self._buffer.append(key)
            return tuple(self._buffer) == self.phrase
        self._buffer.clear()
        return False
