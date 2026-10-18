"""The cat detector: never bother humans, reliably catch cats."""

from typing import Iterable, Optional

import pytest

from pawlock import simulate as sim
from pawlock.detector import PRESETS, CatDetector, Detection, DetectorSettings, KeyPress, mash_signals

from .conftest import quiet_detector


def feed(detector: CatDetector, events: Iterable[sim.Event]) -> Optional[Detection]:
    for t, key, pressed in events:
        detection = detector.on_key(key, pressed, t)
        if detection is not None:
            return detection
    return None


# ---------------------------------------------------------------------------
# Humans must never be locked out (default "medium" and "low" presets)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("preset", ["low", "medium"])
@pytest.mark.parametrize("wpm", [30, 60, 90, 120, 150])
@pytest.mark.parametrize("seed", range(5))
def test_normal_typing_is_never_flagged(preset, wpm, seed):
    events = sim.human_typing(sim.SAMPLE_TEXT, wpm=wpm, seed=seed)
    assert feed(CatDetector(PRESETS[preset]), events) is None


@pytest.mark.parametrize("seed", range(10))
def test_fast_typist_with_heavy_rollover_is_not_flagged(seed):
    # 140 WPM with long key holds: 2-3 keys are often down at the same time.
    events = sim.human_typing(sim.SAMPLE_TEXT, wpm=140, seed=seed, hold=(0.08, 0.2))
    assert feed(CatDetector(PRESETS["medium"]), events) is None


@pytest.mark.parametrize(
    "keys, rate",
    [
        ("tr0ub4dor3xyzq1wplm", 12),     # a password, typed quickly, no spaces
        ("jjjkkkjjjhhhlllkkjjjkk", 14),  # vim navigation
        ("4111111111111111", 12),        # a card number
        ("qwertyuiopasdfghjkl", 14),     # a keyboard-walk "password"
    ],
)
def test_quick_tapping_without_paw_contact_is_not_flagged(keys, rate):
    assert feed(CatDetector(PRESETS["medium"]), sim.taps(keys, rate=rate)) is None


def test_holding_editing_keys_is_fine():
    detector = CatDetector(PRESETS["high"])
    assert feed(detector, sim.key_held("backspace", 30)) is None
    assert feed(detector, sim.key_held("down", 30, start=40)) is None


def test_modifiers_are_ignored():
    detector = CatDetector(PRESETS["high"])
    events = []
    for key in ("ctrl_l", "shift_l", "alt_l", "cmd_l", "ctrl_r"):
        events += [(0.0, key, True), (60.0, key, False)]
    assert feed(detector, sorted(events)) is None


# ---------------------------------------------------------------------------
# Cats must be caught
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("seed", range(20))
def test_sitting_cat_is_caught_immediately(seed):
    detection = feed(CatDetector(PRESETS["medium"]), sim.cat_sit(seed=seed))
    assert detection is not None
    assert detection.rule == "chord"


@pytest.mark.parametrize("seed", range(20))
def test_walking_cat_is_caught_within_eight_steps(seed):
    detection = feed(CatDetector(PRESETS["medium"]), sim.cat_walk(steps=8, seed=seed))
    assert detection is not None


def test_cat_lying_on_three_keys_is_caught():
    detector = quiet_detector(sit_keys=3, sit_seconds=1.5)
    events = sim.cat_sit(keys=["g", "h", "b"], duration=3.0)
    detection = feed(detector, events)
    assert detection is not None and detection.rule == "sit"


def test_toe_bean_parked_on_one_key_is_caught_eventually():
    detector = CatDetector(PRESETS["medium"])
    detection = feed(detector, sim.key_held("k", 25))
    assert detection is not None and detection.rule == "long_hold"
    assert detection.reason == "a key held down for over 20s"  # Never leak key names.


def test_time_based_rules_also_fire_from_tick():
    detector = quiet_detector(sit_keys=3, sit_seconds=1.0)
    for key in ("x", "c", "v"):
        assert detector.on_key(key, True, 0.0) is None
    assert detector.tick(0.5) is None
    detection = detector.tick(1.2)
    assert detection is not None and detection.rule == "sit"


def test_chord_needs_multiple_rows():
    detector = quiet_detector(chord_keys=5, chord_min_rows=2)
    for key in "asdfg":  # five keys, one row
        assert detector.on_key(key, True, 0.0) is None
    detection = detector.on_key("t", True, 0.01)  # sixth key, second row
    assert detection is not None and detection.rule == "chord"


def clicks(times):
    detector = CatDetector(PRESETS["medium"])
    return next((d for d in (detector.on_click(t) for t in times) if d is not None), None)


def test_normal_clicking_is_not_a_click_storm():
    double_clicks = [t for i in range(40) for t in (i * 0.8, i * 0.8 + 0.15)]
    triple_clicks = [t for i in range(20) for t in (i * 1.5, i * 1.5 + 0.12, i * 1.5 + 0.24)]
    brisk_clicking = [i * 0.25 for i in range(40)]  # 4 clicks/s for 10 s
    for pattern in (double_clicks, triple_clicks, brisk_clicking):
        assert clicks(pattern) is None


def test_click_storm_is_caught():
    detection = clicks([i * 0.14 for i in range(30)])  # ~7 clicks/s: kneading paws
    assert detection is not None and detection.rule == "click_storm"


def test_click_storm_presets():
    assert PRESETS["low"].click_storm_clicks == 0  # off
    assert PRESETS["medium"].click_storm_clicks == 15
    detector = quiet_detector(click_storm_clicks=10, click_storm_seconds=2.0)
    results = [detector.on_click(i * 0.1) for i in range(10)]
    assert results[-1] is not None and all(r is None for r in results[:-1])


def test_auto_repeat_does_not_count_as_new_presses():
    detector = quiet_detector(mash_window_keys=6, mash_signals_needed=1)
    for i in range(40):  # "k" held: one press, then many repeats
        assert detector.on_key("k", True, i * 0.033) is None


def test_reset_and_forget():
    detector = quiet_detector(chord_keys=3, chord_min_rows=1)
    detector.on_key("a", True, 0.0)
    detector.on_key("s", True, 0.0)
    detector.reset()
    assert detector.on_key("d", True, 0.0) is None
    detector.on_key("f", True, 0.0)
    detector.forget("f")
    assert detector.on_key("g", True, 0.0) is None


def test_overrides_are_validated():
    settings = DetectorSettings().with_overrides({"chord_keys": 7, "sit_seconds": 2})
    assert settings.chord_keys == 7 and isinstance(settings.chord_keys, int)
    assert settings.sit_seconds == 2.0
    with pytest.raises(ValueError):
        DetectorSettings().with_overrides({"chord_keyz": 7})
    with pytest.raises(ValueError):
        DetectorSettings().with_overrides({"chord_keys": -1})
    with pytest.raises(ValueError):
        DetectorSettings().with_overrides({"chord_keys": True})


# ---------------------------------------------------------------------------
# The mash signals themselves
# ---------------------------------------------------------------------------

def _window(spec, start=0.0):
    """spec: list of (key, seconds since previous press, others held)."""
    t, presses = start, []
    for key, gap, others in spec:
        t += gap
        presses.append(KeyPress(key, t, others))
    return presses


def test_signals_for_paw_input():
    window = _window([("j", 0.0, 0), ("h", 0.01, 1), ("n", 0.01, 2), ("k", 0.3, 0), ("m", 0.02, 1),
                      ("j", 0.02, 2), ("g", 0.3, 0), ("b", 0.01, 1), ("h", 0.01, 2)])
    signals = mash_signals(window)
    assert {"paw contact", "no spaces", "no vowels", "clustered keys"} <= set(signals)


def test_signals_for_prose():
    window = _window([(k if k != " " else "space", 0.15, 0) for k in "the cat sat on"])
    assert mash_signals(window) == []
