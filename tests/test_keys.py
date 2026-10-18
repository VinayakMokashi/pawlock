import enum
from types import SimpleNamespace

import pytest

from pawlock import keys


class FakeKey(enum.Enum):
    """Stands in for pynput.keyboard.Key without importing pynput."""

    ctrl = 1
    ctrl_r = 2
    alt_gr = 3
    shift = 4
    space = 5
    f5 = 6


@pytest.mark.parametrize(
    "vk, name",
    [(0x4C, "l"), (0x41, "a"), (0x30, "0"), (0xA2, "ctrl_l"), (0xA5, "alt_r"),
     (0xA1, "shift_r"), (0x5B, "cmd_l"), (0x70, "f1"), (0x87, "f24"), (0x20, "space"),
     (0xBA, ";"), (0xC0, "`"), (0x60, "num_0"), (0x0D, "enter")],
)
def test_windows_virtual_keys(vk, name):
    assert keys.from_windows_vk(vk) == name


def test_unknown_windows_key_gets_a_stable_name():
    assert keys.from_windows_vk(0xFF) == "vk_255"


@pytest.mark.parametrize(
    "code, name",
    [(0x25, "l"), (0x00, "a"), (0x37, "cmd_l"), (0x36, "cmd_r"), (0x3A, "alt_l"),
     (0x3B, "ctrl_l"), (0x38, "shift_l"), (0x31, "space"), (0x7A, "f1"), (0x12, "1")],
)
def test_mac_keycodes(code, name):
    assert keys.from_mac_keycode(code) == name


@pytest.mark.parametrize(
    "char, name",
    [("a", "a"), ("A", "a"), ("!", "1"), ("?", "/"), (" ", "space"), ("\x0c", "l"),
     ("\x01", "a"), ("é", None), ("", None), (None, None), ("ab", None)],
)
def test_from_char(char, name):
    assert keys.from_char(char) == name


def test_pynput_special_keys_are_folded_to_sided_names():
    assert keys.from_pynput(FakeKey.ctrl) == "ctrl_l"
    assert keys.from_pynput(FakeKey.ctrl_r) == "ctrl_r"
    assert keys.from_pynput(FakeKey.alt_gr) == "alt_r"
    assert keys.from_pynput(FakeKey.shift) == "shift_l"
    assert keys.from_pynput(FakeKey.f5) == "f5"
    assert keys.from_pynput(None) == keys.UNKNOWN


def test_pynput_keycodes_prefer_the_virtual_key():
    # Ctrl+L on Windows: char is a control code, vk is still 'L'.
    assert keys.from_pynput(SimpleNamespace(char="\x0c", vk=0x4C), "win32") == "l"
    # Option+L on macOS types '¬'; the key code says 'l'.
    assert keys.from_pynput(SimpleNamespace(char="¬", vk=0x25), "darwin") == "l"
    # X11 keysym for '!' (Shift+1).
    assert keys.from_pynput(SimpleNamespace(char="!", vk=0x21), "linux") == "1"
    # No vk at all: fall back to the character.
    assert keys.from_pynput(SimpleNamespace(char="K", vk=None), "linux") == "k"
    assert keys.from_pynput(SimpleNamespace(char=None, vk=0xFFB1), "linux") == "vk_65457"


def test_modifier_helpers():
    assert keys.is_modifier("ctrl_r") and not keys.is_modifier("l")
    assert keys.modifier_base("alt_r") == "alt"
    assert keys.modifier_base("l") == "l"


@pytest.mark.parametrize(
    "a, b", [("f", "g"), ("f", "r"), ("f", "t"), ("f", "v"), ("f", "c"), ("j", "u"), ("1", "q"), ("space", "b")],
)
def test_neighbouring_keys_are_adjacent(a, b):
    assert keys.are_adjacent(a, b)
    assert keys.are_adjacent(b, a)


@pytest.mark.parametrize("a, b", [("a", "l"), ("q", "p"), ("f", "b"), ("f", "f"), ("space", "q"), ("a", "up")])
def test_distant_keys_are_not_adjacent(a, b):
    assert not keys.are_adjacent(a, b)


def test_rows():
    assert keys.key_row("1") == 0
    assert keys.key_row("q") == 1
    assert keys.key_row("a") == 2
    assert keys.key_row("z") == 3
    assert keys.key_row("space") == 4
    assert keys.key_row("f1") == -1
    assert keys.key_row("up") is None
