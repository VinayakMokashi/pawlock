"""One shared vocabulary for keys, whatever the operating system says.

Every platform describes a key press differently:

* **pynput** hands us ``Key`` enum members (``Key.ctrl_l``) or ``KeyCode``
  objects carrying a ``char`` and/or a platform-specific ``vk``.
* The **Windows** low-level keyboard hook gives raw virtual-key codes
  (``VK_*``), e.g. ``0x4C`` for the L key.
* The **macOS** event tap gives raw hardware key codes (``kVK_*``),
  e.g. ``0x25`` for the L key on a US layout.

PawLock converts all of those into short lowercase strings such as ``"a"``,
``"7"``, ``";"``, ``"space"``, ``"ctrl_l"`` or ``"f5"``. Everything above this
module (hotkeys, the unlock phrase, the cat detector) only ever sees those
strings. That keeps the clever bits platform-independent and lets the test
suite run on any machine without importing pynput or touching real input
devices.

This module also knows roughly where each key sits on a physical keyboard,
which the cat detector uses to tell "paw-shaped" clusters of keys apart from
normal typing.
"""

from __future__ import annotations

import enum
import math
import sys
from typing import Any, Dict, Optional, Tuple

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

#: Modifier keys keep their side ("ctrl_l" vs "ctrl_r") so that holding both
#: Ctrl keys and releasing one is tracked correctly. ``modifier_base`` folds
#: the side away when we only care about *which* modifier it is.
MODIFIER_KEYS: Dict[str, str] = {
    "ctrl_l": "ctrl",
    "ctrl_r": "ctrl",
    "shift_l": "shift",
    "shift_r": "shift",
    "alt_l": "alt",
    "alt_r": "alt",
    "cmd_l": "cmd",
    "cmd_r": "cmd",
}

#: The four modifier families a hotkey may use.
MODIFIER_BASES = frozenset(MODIFIER_KEYS.values())

LETTERS = "abcdefghijklmnopqrstuvwxyz"
DIGITS = "0123456789"
#: Unshifted punctuation on a US keyboard.
PUNCTUATION = "`-=[]\\;',./"

NAMED_KEYS = frozenset(
    {
        "space", "enter", "tab", "backspace", "esc", "caps_lock", "delete",
        "insert", "home", "end", "page_up", "page_down", "up", "down", "left",
        "right", "print_screen", "scroll_lock", "pause", "num_lock", "menu",
        "fn", "oem_102",
        "num_add", "num_subtract", "num_multiply", "num_divide", "num_decimal",
        "num_enter", "num_equal", "num_separator",
        "media_play_pause", "media_next", "media_previous", "media_stop",
        "media_volume_up", "media_volume_down", "media_volume_mute",
        *(f"f{i}" for i in range(1, 25)),
        *(f"num_{d}" for d in DIGITS),
    }
)

#: Every non-modifier key name a hotkey may use as its trigger.
KNOWN_KEYS = frozenset(LETTERS) | frozenset(DIGITS) | frozenset(PUNCTUATION) | NAMED_KEYS

#: Returned when we cannot identify a key at all.
UNKNOWN = "unknown"

#: Keys that separate words. Real text is full of them; cat input rarely is.
SEPARATOR_KEYS = frozenset({"space", "enter", "tab", "num_enter"})

#: Vowels (including "y") — real words are roughly 40% vowels.
VOWELS = frozenset("aeiouy")


def is_modifier(name: str) -> bool:
    """True for Ctrl/Shift/Alt/Cmd(Win/Super) on either side."""
    return name in MODIFIER_KEYS


def modifier_base(name: str) -> str:
    """``"ctrl_r" -> "ctrl"``; non-modifier names are returned unchanged."""
    return MODIFIER_KEYS.get(name, name)


def is_character_key(name: str) -> bool:
    """True for single-character keys that type something (letters, digits, punctuation)."""
    return len(name) == 1


# ---------------------------------------------------------------------------
# Characters -> names (used for pynput KeyCode objects)
# ---------------------------------------------------------------------------

#: Shifted symbol -> the key that produces it on a US layout. Lets "!" and "1"
#: count as the same physical key.
_UNSHIFT = {
    "~": "`", "!": "1", "@": "2", "#": "3", "$": "4", "%": "5", "^": "6",
    "&": "7", "*": "8", "(": "9", ")": "0", "_": "-", "+": "=", "{": "[",
    "}": "]", "|": "\\", ":": ";", '"': "'", "<": ",", ">": ".", "?": "/",
}


def from_char(char: Optional[str]) -> Optional[str]:
    """Name for a typed character, or ``None`` if it isn't a plain US-ASCII key.

    Handles two quirks of how operating systems report characters:

    * With Ctrl held, letters arrive as ASCII control codes (Ctrl+L is
      ``"\\x0c"``), so codes 1-26 are mapped back to ``a``-``z``.
    * Shifted symbols are folded back onto their base key (``"!" -> "1"``).
    """
    if not char or len(char) != 1:
        return None
    code = ord(char)
    if code < 32:
        return LETTERS[code - 1] if 1 <= code <= 26 else None
    c = _UNSHIFT.get(char, char.lower())
    if c == " ":
        return "space"
    if c in LETTERS or c in DIGITS or c in PUNCTUATION:
        return c
    return None


# ---------------------------------------------------------------------------
# Windows virtual-key codes
# ---------------------------------------------------------------------------

WINDOWS_VK: Dict[int, str] = {
    0x08: "backspace", 0x09: "tab", 0x0D: "enter",
    # Generic modifier codes (the low-level hook normally sends the sided
    # versions below, but other sources may not).
    0x10: "shift_l", 0x11: "ctrl_l", 0x12: "alt_l",
    0x13: "pause", 0x14: "caps_lock", 0x1B: "esc", 0x20: "space",
    0x21: "page_up", 0x22: "page_down", 0x23: "end", 0x24: "home",
    0x25: "left", 0x26: "up", 0x27: "right", 0x28: "down",
    0x2C: "print_screen", 0x2D: "insert", 0x2E: "delete",
    0x5B: "cmd_l", 0x5C: "cmd_r", 0x5D: "menu",
    0x6A: "num_multiply", 0x6B: "num_add", 0x6C: "num_separator",
    0x6D: "num_subtract", 0x6E: "num_decimal", 0x6F: "num_divide",
    0x90: "num_lock", 0x91: "scroll_lock",
    0xA0: "shift_l", 0xA1: "shift_r", 0xA2: "ctrl_l", 0xA3: "ctrl_r",
    0xA4: "alt_l", 0xA5: "alt_r",
    0xAD: "media_volume_mute", 0xAE: "media_volume_down", 0xAF: "media_volume_up",
    0xB0: "media_next", 0xB1: "media_previous", 0xB2: "media_stop",
    0xB3: "media_play_pause",
    # "OEM" punctuation keys (US layout labels).
    0xBA: ";", 0xBB: "=", 0xBC: ",", 0xBD: "-", 0xBE: ".", 0xBF: "/", 0xC0: "`",
    0xDB: "[", 0xDC: "\\", 0xDD: "]", 0xDE: "'", 0xE2: "oem_102",
}
WINDOWS_VK.update({0x30 + i: d for i, d in enumerate(DIGITS)})      # VK_0..VK_9
WINDOWS_VK.update({0x41 + i: c for i, c in enumerate(LETTERS)})     # VK_A..VK_Z
WINDOWS_VK.update({0x60 + i: f"num_{i}" for i in range(10)})        # VK_NUMPAD0..9
WINDOWS_VK.update({0x70 + i: f"f{i + 1}" for i in range(24)})       # VK_F1..VK_F24


def from_windows_vk(vk: int) -> str:
    """Name for a Windows virtual-key code (``VK_*``)."""
    return WINDOWS_VK.get(vk, f"vk_{vk}")


# ---------------------------------------------------------------------------
# macOS hardware key codes (kVK_* from Carbon's Events.h)
# ---------------------------------------------------------------------------
#
# These codes describe *positions* on an ANSI (US) keyboard, so on macOS a
# hotkey letter is matched by where the key is, not by what is printed on it.

MAC_KEYCODES: Dict[int, str] = {
    0x00: "a", 0x01: "s", 0x02: "d", 0x03: "f", 0x04: "h", 0x05: "g",
    0x06: "z", 0x07: "x", 0x08: "c", 0x09: "v", 0x0A: "oem_102", 0x0B: "b",
    0x0C: "q", 0x0D: "w", 0x0E: "e", 0x0F: "r", 0x10: "y", 0x11: "t",
    0x12: "1", 0x13: "2", 0x14: "3", 0x15: "4", 0x16: "6", 0x17: "5",
    0x18: "=", 0x19: "9", 0x1A: "7", 0x1B: "-", 0x1C: "8", 0x1D: "0",
    0x1E: "]", 0x1F: "o", 0x20: "u", 0x21: "[", 0x22: "i", 0x23: "p",
    0x24: "enter", 0x25: "l", 0x26: "j", 0x27: "'", 0x28: "k", 0x29: ";",
    0x2A: "\\", 0x2B: ",", 0x2C: "/", 0x2D: "n", 0x2E: "m", 0x2F: ".",
    0x30: "tab", 0x31: "space", 0x32: "`", 0x33: "backspace", 0x35: "esc",
    0x36: "cmd_r", 0x37: "cmd_l", 0x38: "shift_l", 0x39: "caps_lock",
    0x3A: "alt_l", 0x3B: "ctrl_l", 0x3C: "shift_r", 0x3D: "alt_r",
    0x3E: "ctrl_r", 0x3F: "fn",
    0x40: "f17", 0x41: "num_decimal", 0x43: "num_multiply", 0x45: "num_add",
    0x47: "num_lock", 0x48: "media_volume_up", 0x49: "media_volume_down",
    0x4A: "media_volume_mute", 0x4B: "num_divide", 0x4C: "num_enter",
    0x4E: "num_subtract", 0x4F: "f18", 0x50: "f19", 0x51: "num_equal",
    0x52: "num_0", 0x53: "num_1", 0x54: "num_2", 0x55: "num_3", 0x56: "num_4",
    0x57: "num_5", 0x58: "num_6", 0x59: "num_7", 0x5A: "f20", 0x5B: "num_8",
    0x5C: "num_9",
    0x60: "f5", 0x61: "f6", 0x62: "f7", 0x63: "f3", 0x64: "f8", 0x65: "f9",
    0x67: "f11", 0x69: "f13", 0x6A: "f16", 0x6B: "f14", 0x6D: "f10",
    0x6F: "f12", 0x71: "f15", 0x72: "insert", 0x73: "home", 0x74: "page_up",
    0x75: "delete", 0x76: "f4", 0x77: "end", 0x78: "f2", 0x79: "page_down",
    0x7A: "f1", 0x7B: "left", 0x7C: "right", 0x7D: "down", 0x7E: "up",
}


def from_mac_keycode(code: int) -> str:
    """Name for a macOS hardware key code (``kVK_*``)."""
    return MAC_KEYCODES.get(code, f"vk_{code}")


# ---------------------------------------------------------------------------
# pynput objects -> names (used by the portable "swap" backend)
# ---------------------------------------------------------------------------

#: pynput's generic modifier names map to the left-hand key.
_PYNPUT_ALIASES = {
    "alt": "alt_l",
    "alt_gr": "alt_r",
    "ctrl": "ctrl_l",
    "shift": "shift_l",
    "cmd": "cmd_l",
}


def from_pynput(key: Any, platform: str = sys.platform) -> str:
    """Name for a pynput ``Key`` / ``KeyCode`` (duck-typed, so pynput isn't imported).

    The virtual-key code is preferred over the character because the
    character changes with modifiers (Ctrl+L, Option+L and Shift+L all
    produce different characters) while the key code does not.
    """
    if key is None:
        return UNKNOWN
    if isinstance(key, enum.Enum):  # pynput.keyboard.Key.<name>
        return _PYNPUT_ALIASES.get(key.name, key.name)

    vk = getattr(key, "vk", None)
    char = getattr(key, "char", None)
    if vk is not None:
        if platform == "win32":
            name = WINDOWS_VK.get(vk)
        elif platform == "darwin":
            name = MAC_KEYCODES.get(vk)
        else:
            # X11 keysyms coincide with ASCII for printable characters.
            name = from_char(chr(vk)) if 0x20 <= vk <= 0x7E else None
        if name:
            return name
    name = from_char(char)
    if name:
        return name
    return f"vk_{vk}" if vk is not None else UNKNOWN


# ---------------------------------------------------------------------------
# Keyboard geometry (for the cat detector)
# ---------------------------------------------------------------------------
#
# Approximate centre of each key on a standard US keyboard, in "key widths".
# x grows to the right, y grows downwards (0 = number row). Rows are
# staggered the way real keyboards are, so "f" is next to "r", "t", "c" and
# "v" as well as "d" and "g".

_ROW_LAYOUT = (
    # (row y, x of the left edge of the first key, keys)
    (0, 0.0, "`1234567890-="),
    (1, 1.5, "qwertyuiop[]\\"),
    (2, 1.75, "asdfghjkl;'"),
    (3, 2.25, "zxcvbnm,./"),
)

_POSITIONS: Dict[str, Tuple[float, float]] = {}
for _y, _offset, _chars in _ROW_LAYOUT:
    for _i, _ch in enumerate(_chars):
        _POSITIONS[_ch] = (_offset + _i + 0.5, float(_y))

_FUNCTION_ROW_Y = -1.25
_POSITIONS.update(
    {
        "esc": (0.5, _FUNCTION_ROW_Y),
        **{f"f{i}": (1.5 + i, _FUNCTION_ROW_Y) for i in range(1, 5)},
        **{f"f{i}": (2.0 + i, _FUNCTION_ROW_Y) for i in range(5, 9)},
        **{f"f{i}": (2.5 + i, _FUNCTION_ROW_Y) for i in range(9, 13)},
        "backspace": (14.0, 0.0),
        "tab": (0.75, 1.0),
        "caps_lock": (0.9, 2.0),
        "enter": (13.9, 2.0),
    }
)

#: The space bar is wide: model it as a horizontal segment, not a point.
_SPACE_Y = 4.0
_SPACE_X = (4.0, 10.0)

#: Two keys closer than this (in key widths) count as "touching" for a paw.
ADJACENT_DISTANCE = 1.5


def key_position(name: str) -> Optional[Tuple[float, float]]:
    """Approximate (x, y) centre of a key, or ``None`` if it has no fixed spot."""
    if name == "space":
        return ((_SPACE_X[0] + _SPACE_X[1]) / 2, _SPACE_Y)
    return _POSITIONS.get(name)


def key_row(name: str) -> Optional[int]:
    """Keyboard row of a key (-1 = function row, 0 = numbers ... 4 = space)."""
    pos = key_position(name)
    return None if pos is None else int(round(pos[1]))


def key_distance(a: str, b: str) -> Optional[float]:
    """Distance between two keys in key widths, or ``None`` if either is unplaced."""
    if a == "space" and b == "space":
        return 0.0
    if a == "space" or b == "space":
        other = _POSITIONS.get(b if a == "space" else a)
        if other is None:
            return None
        # Distance from a point to the space-bar segment.
        x = min(max(other[0], _SPACE_X[0]), _SPACE_X[1])
        return math.hypot(other[0] - x, other[1] - _SPACE_Y)
    pa, pb = _POSITIONS.get(a), _POSITIONS.get(b)
    if pa is None or pb is None:
        return None
    return math.hypot(pa[0] - pb[0], pa[1] - pb[1])


def are_adjacent(a: str, b: str) -> bool:
    """True if two *different* keys are physically next to each other."""
    if a == b:
        return False
    d = key_distance(a, b)
    return d is not None and d <= ADJACENT_DISTANCE
