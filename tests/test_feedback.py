from pawlock.engine import (
    REASON_AUTO,
    REASON_HOTKEY,
    REASON_SAFETY,
    REASON_SHUTDOWN,
    REASON_TIMEOUT,
    StateChange,
)
from pawlock.feedback import FeedbackHub, describe, unlock_instructions
from pawlock.feedback.icons import STATE_COLOURS, paw_glyph, tray_icon, write_app_icons

HOTKEY = "Ctrl + Alt + Shift + L"


def test_unlock_instructions():
    assert unlock_instructions(HOTKEY, "unlock") == f"Unlock: press {HOTKEY}  or type “unlock”"
    assert unlock_instructions(HOTKEY, "") == f"Unlock: press {HOTKEY}"


def test_describe_cat_detection():
    title, body = describe(StateChange(True, REASON_AUTO, "6 keys pressed at once"), HOTKEY, "unlock")
    assert "Cat detected" in title
    assert body.startswith("6 keys pressed at once.")
    assert HOTKEY in body


def test_describe_other_states():
    assert describe(StateChange(True, REASON_HOTKEY), HOTKEY, "")[0] == "Locked: paws off!"
    assert "welcome back" in describe(StateChange(False, REASON_HOTKEY), HOTKEY, "")[0]
    assert describe(StateChange(False, REASON_TIMEOUT), HOTKEY, "")[0] == "Unlocked automatically"
    assert describe(StateChange(False, REASON_SAFETY, "hook died"), HOTKEY, "") == ("Unlocked for safety", "hook died")
    assert describe(StateChange(True, REASON_AUTO, "x", dry_run=True), HOTKEY, "")[0].startswith("Dry run")


class Recorder:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        return lambda *args, **kwargs: self.calls.append((name, args))


def test_hub_fans_out_to_every_channel():
    sound, tray, overlay = Recorder(), Recorder(), Recorder()
    hub = FeedbackHub(sound=sound, notifications=True)
    hub.tray, hub.overlay = tray, overlay

    hub.state_changed(StateChange(True, REASON_AUTO, "a cat"), hotkey_text=HOTKEY, phrase="unlock",
                      auto_detect=True, tooltip="PawLock: LOCKED")
    assert ("play", ("cat",)) in sound.calls
    assert ("set_state", ("locked", "PawLock: LOCKED")) in tray.calls
    assert any(name == "notify" for name, _ in tray.calls)
    assert overlay.calls[0][0] == "show_locked"

    hub.state_changed(StateChange(False, REASON_HOTKEY), hotkey_text=HOTKEY, phrase="unlock",
                      auto_detect=False, tooltip="t")
    assert ("play", ("unlock",)) in sound.calls
    assert ("set_state", ("paused", "t")) in tray.calls
    assert overlay.calls[-1][0] == "flash"

    hub.state_changed(StateChange(False, REASON_SHUTDOWN), hotkey_text=HOTKEY, phrase="",
                      auto_detect=True, tooltip="t")
    assert overlay.calls[-1][0] == "hide"


def test_icons(tmp_path):
    images = {state: tray_icon(state, 32) for state in STATE_COLOURS}
    assert all(img.size == (32, 32) for img in images.values())
    assert images["locked"].getpixel((4, 16)) != images["watching"].getpixel((4, 16))
    assert paw_glyph(48, (255, 0, 0)).getpixel((0, 0))[3] == 0  # transparent corner
    ico, png = write_app_icons(tmp_path)
    assert ico.stat().st_size > 1000 and png.stat().st_size > 1000


def test_away_lock_is_quiet_and_shows_the_banner_when_touched():
    from pawlock.engine import REASON_AWAY
    from pawlock.feedback import is_quiet_lock

    change = StateChange(True, REASON_AWAY, "no keyboard or mouse activity for 10 minutes")
    assert is_quiet_lock(change)
    assert not is_quiet_lock(StateChange(True, REASON_AWAY, "x", dry_run=True))
    title, body = describe(change, HOTKEY, "unlock")
    assert title == "Away mode: keyboard & trackpad locked"
    assert body.startswith("No keyboard or mouse activity for 10 minutes.")

    sound, tray, overlay = Recorder(), Recorder(), Recorder()
    hub = FeedbackHub(sound=sound, notifications=True)
    hub.tray, hub.overlay = tray, overlay
    hub.state_changed(change, hotkey_text=HOTKEY, phrase="unlock", auto_detect=True, tooltip="t")
    assert sound.calls == [] and overlay.calls == []           # silent...
    assert ("set_state", ("locked", "t")) in tray.calls        # ...except the red paw
    hub.poke(title, body, first=True)
    assert overlay.calls[-1][0] == "flash"

    hub.overlay = None  # e.g. macOS: no banner -> a single notification
    tray.calls.clear()
    hub.poke(title, body, first=True)
    hub.poke(title, body, first=False)
    assert [name for name, _ in tray.calls] == ["notify"]


def test_unlock_shows_what_was_blocked():
    summary = "Blocked 214 key presses and 37 clicks while locked."
    assert describe(StateChange(False, REASON_HOTKEY, summary=summary), HOTKEY, "")[1] == summary
    overlay = Recorder()
    hub = FeedbackHub(sound=Recorder(), notifications=False)
    hub.overlay = overlay
    hub.state_changed(StateChange(False, REASON_HOTKEY, summary=summary), hotkey_text=HOTKEY, phrase="",
                      auto_detect=True, tooltip="t")
    name, args = overlay.calls[-1]
    assert name == "flash" and args[1] == summary and args[3] == 6000
