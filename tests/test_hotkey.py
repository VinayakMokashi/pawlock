import pytest

from pawlock.hotkey import Hotkey, PhraseMatcher


@pytest.mark.parametrize(
    "text, modifiers, trigger",
    [
        ("ctrl+alt+shift+l", {"ctrl", "alt", "shift"}, "l"),
        ("Ctrl + Alt + Shift + L", {"ctrl", "alt", "shift"}, "l"),
        ("control+option+shift+L", {"ctrl", "alt", "shift"}, "l"),
        ("win+shift+F12", {"cmd", "shift"}, "f12"),
        ("ctrl+alt+pgdn", {"ctrl", "alt"}, "page_down"),
        ("ctrl+alt+equals", {"ctrl", "alt"}, "="),
    ],
)
def test_parse(text, modifiers, trigger):
    hotkey = Hotkey.parse(text)
    assert hotkey.modifiers == frozenset(modifiers)
    assert hotkey.trigger == trigger


@pytest.mark.parametrize(
    "text",
    ["", "   ", "l", "ctrl+alt", "ctrl+alt+k+l", "ctrl+ctrl+l", "ctrl+banana", "ctrl++", None, 42],
)
def test_parse_rejects_bad_hotkeys(text):
    with pytest.raises(ValueError):
        Hotkey.parse(text)


def test_string_form_round_trips():
    hotkey = Hotkey.parse("Shift + Ctrl + L + Alt")
    assert str(hotkey) == "ctrl+alt+shift+l"
    assert Hotkey.parse(str(hotkey)) == hotkey


def test_exact_match_only():
    hotkey = Hotkey.parse("ctrl+alt+shift+l")
    assert hotkey.matches({"ctrl_l", "alt_l", "shift_l", "l"}, "l")
    assert hotkey.matches({"ctrl_r", "alt_r", "shift_r", "l"}, "l")  # either side works
    # A paw also on the space bar: superset -> no match.
    assert not hotkey.matches({"ctrl_l", "alt_l", "shift_l", "l", "space"}, "l")
    # Missing a modifier.
    assert not hotkey.matches({"ctrl_l", "alt_l", "l"}, "l")
    # L pressed first, then a modifier completes the set: wrong order.
    assert not hotkey.matches({"ctrl_l", "alt_l", "shift_l", "l"}, "shift_l")
    # Both Ctrl keys held: one key too many.
    assert not hotkey.matches({"ctrl_l", "ctrl_r", "alt_l", "shift_l", "l"}, "l")


def test_display_uses_platform_names():
    hotkey = Hotkey.parse("ctrl+alt+shift+l")
    assert hotkey.display("win32") == "Ctrl + Alt + Shift + L"
    assert hotkey.display("darwin") == "Control + Option + Shift + L"
    assert Hotkey.parse("super+alt+page_up").display("linux") == "Alt + Super + Page Up"


def test_warnings_for_weak_hotkeys():
    assert Hotkey.parse("ctrl+alt+shift+l").warnings() == []
    assert any("two modifiers" in w for w in Hotkey.parse("ctrl+l").warnings())
    assert any("big key" in w for w in Hotkey.parse("ctrl+alt+space").warnings())


class TestPhrase:
    def test_typing_the_phrase_matches_on_the_last_letter(self):
        matcher = PhraseMatcher("unlock")
        results = [matcher.feed(k) for k in "unlock"]
        assert results == [False] * 5 + [True]

    def test_modifiers_are_ignored(self):
        matcher = PhraseMatcher("unlock")
        sequence = ["shift_l", "u", "n", "l", "shift_r", "o", "c", "k"]
        assert [matcher.feed(k) for k in sequence][-1] is True

    def test_other_keys_restart_the_sequence(self):
        matcher = PhraseMatcher("unlock")
        for key in ["u", "n", "space", "l", "o", "c", "k"]:
            assert matcher.feed(key) is False

    def test_works_after_garbage(self):
        matcher = PhraseMatcher("unlock")
        for key in "jfkdlsunl":
            matcher.feed(key)
        assert [matcher.feed(k) for k in "unlock"][-1] is True

    def test_disabled(self):
        matcher = PhraseMatcher("")
        assert not matcher.enabled
        assert not any(matcher.feed(k) for k in "unlock")

    @pytest.mark.parametrize("phrase", ["abc", "has space", "ünlock", "x" * 33, 7])
    def test_validation(self, phrase):
        with pytest.raises(ValueError):
            PhraseMatcher.validate(phrase)

    def test_validation_normalises(self):
        assert PhraseMatcher.validate("  UnLock ") == "unlock"
