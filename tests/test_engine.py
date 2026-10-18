"""The lock engine: what gets swallowed, what gets through, and when."""

import threading

from pawlock.engine import (
    REASON_AUTO,
    REASON_HOTKEY,
    REASON_PHRASE,
    REASON_SAFETY,
)
from pawlock.hotkey import Hotkey

from .conftest import hotkey_steps, press_sequence, quiet_detector, tap


def test_unlocked_input_flows_freely(make_engine, clock):
    engine = make_engine()
    assert press_sequence(engine, clock, tap("a") + tap("space")) == [False] * 4
    assert engine.handle_mouse_motion() is False
    assert engine.handle_mouse_button("left", True) is False
    assert engine.handle_mouse_button("left", False) is False


def test_hotkey_locks_and_keeps_the_combo_away_from_apps(make_engine, clock, changes):
    engine = make_engine()
    decisions = press_sequence(engine, clock, hotkey_steps())
    # ctrl, alt, shift down -> delivered; L down/up -> swallowed;
    # modifier releases -> delivered (their presses were delivered).
    assert decisions == [False, False, False, True, True, False, False, False]
    assert engine.locked
    assert [(c.locked, c.reason) for c in changes] == [(True, REASON_HOTKEY)]


def test_everything_is_swallowed_while_locked(make_engine, clock):
    engine = make_engine()
    engine.lock()
    assert press_sequence(engine, clock, tap("a") + tap("enter") + tap("f4")) == [True] * 6
    assert engine.handle_mouse_motion() is True
    assert engine.handle_mouse_button("left", True) is True
    assert engine.handle_mouse_button("left", False) is True
    assert engine.handle_other_key_event() is True


def test_hotkey_unlocks_and_none_of_it_leaks(make_engine, clock, changes):
    engine = make_engine()
    engine.lock()
    decisions = press_sequence(engine, clock, hotkey_steps())
    assert decisions == [True] * 8  # every press was swallowed, so every release is too
    assert not engine.locked
    assert changes[-1].reason == REASON_HOTKEY


def test_cat_lying_on_the_hotkey_plus_more_cannot_unlock(make_engine, clock):
    engine = make_engine()
    engine.lock()
    steps = [("ctrl_l", True), ("alt_l", True), ("shift_l", True), ("space", True), ("l", True)]
    press_sequence(engine, clock, steps)
    assert engine.locked


def test_wrong_order_does_not_unlock(make_engine, clock):
    engine = make_engine()
    engine.lock()
    press_sequence(engine, clock, [("l", True), ("ctrl_l", True), ("alt_l", True), ("shift_l", True)])
    assert engine.locked


def test_unlock_phrase(make_engine, clock, changes):
    engine = make_engine()
    engine.lock()
    steps = []
    for ch in "unlock":
        steps += tap(ch)
    decisions = press_sequence(engine, clock, steps)
    assert all(decisions)  # Nothing typed while locked reaches apps, not even the last "k".
    assert not engine.locked
    assert changes[-1].reason == REASON_PHRASE


def test_phrase_disabled(make_engine, clock):
    engine = make_engine(unlock_phrase="")
    engine.lock()
    for ch in "unlock":
        press_sequence(engine, clock, tap(ch))
    assert engine.locked


def test_balanced_suppression_prevents_stuck_keys(make_engine, clock):
    """A key pressed before the lock must have its release delivered."""
    engine = make_engine()
    assert engine.handle_key("w", True) is False      # delivered
    assert engine.handle_mouse_button("left", True) is False
    engine.lock()
    assert engine.handle_key("w", True) is True        # auto-repeat while locked: swallowed
    assert engine.handle_key("w", False) is False      # release delivered: no stuck key
    assert engine.handle_mouse_button("left", False) is False  # no stuck drag


def test_presses_swallowed_while_locked_stay_swallowed_after_unlock(make_engine, clock):
    engine = make_engine()
    engine.lock()
    assert engine.handle_key("q", True) is True
    assert engine.handle_mouse_button("right", True) is True
    engine.unlock()
    assert engine.handle_key("q", True) is True        # still-held key repeating: swallowed
    assert engine.handle_key("q", False) is True
    assert engine.handle_mouse_button("right", False) is True


def test_release_without_a_known_press_is_delivered(make_engine, clock):
    engine = make_engine()
    engine.lock()
    assert engine.handle_key("x", False) is False  # pressed before PawLock started


def test_auto_lock_swallows_the_triggering_press(make_engine, clock, changes):
    engine = make_engine(detector=quiet_detector(chord_keys=5, chord_min_rows=2))
    decisions = press_sequence(engine, clock, [(k, True) for k in "asdfg"], gap=0.005)
    assert decisions == [False, False, False, False, False]
    assert engine.handle_key("t", True) is True  # sixth key, second row: chord!
    assert engine.locked and changes[-1].reason == REASON_AUTO
    assert "keys pressed at once" in changes[-1].detail
    # The keys that got through before detection have their releases delivered.
    assert press_sequence(engine, clock, [(k, False) for k in "asdfg"]) == [False] * 5
    assert engine.handle_key("t", False) is True


def test_cooldown_after_unlock(make_engine, clock):
    engine = make_engine(detector=quiet_detector(chord_keys=3, chord_min_rows=1), cooldown_seconds=5)
    engine.lock()
    engine.unlock()
    press_sequence(engine, clock, [(k, True) for k in "zxc"], gap=0.01)
    assert not engine.locked  # inside the cooldown
    press_sequence(engine, clock, [(k, False) for k in "zxc"], gap=0.01)
    clock.advance(6)
    press_sequence(engine, clock, [(k, True) for k in "zxc"], gap=0.01)
    assert engine.locked


def test_auto_detect_can_be_switched_off(make_engine, clock):
    engine = make_engine(detector=quiet_detector(chord_keys=3, chord_min_rows=1), auto_detect=False)
    press_sequence(engine, clock, [(k, True) for k in "zxcvb"], gap=0.01)
    assert not engine.locked


def test_tick_runs_time_based_rules(make_engine, clock):
    engine = make_engine(detector=quiet_detector(sit_keys=3, sit_seconds=1.5))
    press_sequence(engine, clock, [(k, True) for k in "zxc"], gap=0.01)
    assert not engine.locked
    clock.advance(2)
    engine.tick()
    assert engine.locked


def test_stale_keys_are_forgotten(make_engine, clock):
    engine = make_engine(stale_key_seconds=10)
    engine.handle_key("x", True)  # its release gets lost (e.g. to the secure desktop)
    engine.lock()
    press_sequence(engine, clock, hotkey_steps())
    assert engine.locked  # the ghost "x" spoils the exact match...
    clock.advance(30)
    press_sequence(engine, clock, hotkey_steps())
    assert not engine.locked  # ...until it is forgotten


def test_keyboard_only_lock(make_engine, clock):
    engine = make_engine(lock_mouse=False)
    engine.lock()
    assert engine.handle_mouse_motion() is False
    assert engine.handle_mouse_button("left", True) is False
    assert engine.handle_key("a", True) is True


def test_dry_run_never_swallows(make_engine, clock, changes):
    engine = make_engine(dry_run=True, detector=quiet_detector(chord_keys=3, chord_min_rows=1))
    assert press_sequence(engine, clock, [(k, True) for k in "zxc"], gap=0.01) == [False] * 3
    assert engine.locked  # it *would* be locked...
    assert changes[-1].dry_run
    assert engine.handle_mouse_motion() is False  # ...but nothing is blocked
    assert press_sequence(engine, clock, hotkey_steps()) == [False] * 8


def test_force_unlock_works_even_if_the_mutex_is_stuck(make_engine, clock, changes):
    engine = make_engine()
    engine.lock()
    hold = threading.Event()
    release = threading.Event()

    def wedge():
        with engine._mutex:
            hold.set()
            release.wait(5)

    thread = threading.Thread(target=wedge)
    thread.start()
    hold.wait(5)
    try:
        engine.try_unlock(REASON_SAFETY, timeout=0.1)  # can't get the mutex -> forced
        assert not engine.locked
        assert engine.handle_mouse_motion() is False
        assert changes[-1].reason == REASON_SAFETY
    finally:
        release.set()
        thread.join()


def test_a_broken_listener_cannot_break_the_engine(clock):
    from pawlock.engine import LockEngine

    def explode(_change):
        raise RuntimeError("boom")

    engine = LockEngine(Hotkey.parse("ctrl+alt+shift+l"), on_change=explode, clock=clock)
    engine.lock()
    assert engine.locked
    assert engine.handle_key("a", True) is True


def test_reconfigure_hotkey(make_engine, clock):
    engine = make_engine()
    engine.reconfigure(hotkey=Hotkey.parse("ctrl+alt+k"))
    press_sequence(engine, clock, [("ctrl_l", True), ("alt_l", True), ("k", True)])
    assert engine.locked
