"""Telling a cat from a human by *how* the keyboard is being pressed.

The detector watches key presses while the computer is unlocked and raises a
:class:`Detection` when the input looks like paws. It looks at timing, which
keys go down together and where they sit on the keyboard. It never stores
what you typed: it keeps at most a few seconds of key names in memory, and
nothing is written to disk.

The rules
---------
A cat produces input that is physically awkward for a person:

1. **Paw chord.** Many keys held down *at the same time*, spread over
   several keyboard rows. A paw is 3-4 cm across; a sitting cat covers a
   dozen keys. People almost never hold 5+ ordinary keys at once.

2. **Sitting / lying down.** Several keys held continuously for a while
   (default: 3 keys for 1.5 s). People hold one key (Backspace, an arrow),
   not three random ones.

3. **Long hold.** A single typing key held for a very long time (default
   20 s). Catches a cat that has parked one toe bean on the "k" key.
   Navigation and editing keys are exempt.

4. **Mashing.** A rolling window of the last N key presses is scored
   against five signals (see :func:`mash_signals`):

   * ``paw contact``: several keys went down almost at once (within 35 ms),
     or while three others were still held. **Required**, because a paw always touches
     more than one key, and it keeps fast human typists, vim users and
     password typists out of the danger zone.
   * ``no spaces``: no space, Enter or Tab anywhere in the window.
   * ``no vowels``: mostly letters, but hardly any vowels.
   * ``clustered``: consecutive keys are physically next to each other.
   * ``very fast``: more key presses per second than fast typing.

   The window triggers when ``paw contact`` is present and the total number
   of signals reaches the sensitivity threshold.

5. **Click storm** (off by default). Lots of mouse clicks in a short time,
   for cats that prefer the trackpad.

All thresholds live in :class:`DetectorSettings`, with three presets
(``low``, ``medium``, ``high``) in :data:`PRESETS`.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, fields, replace
from typing import Deque, Dict, List, Optional, Sequence

from .keys import (
    SEPARATOR_KEYS,
    VOWELS,
    are_adjacent,
    is_modifier,
    key_row,
)

#: Keys people legitimately hold for a long time (deleting, scrolling, ...).
HOLD_EXEMPT_KEYS = frozenset(
    {
        "backspace", "delete", "up", "down", "left", "right", "page_up",
        "page_down", "home", "end", "num_2", "num_4", "num_6", "num_8",
        "media_volume_up", "media_volume_down",
    }
)

#: Two presses this close together (seconds) are "simultaneous": one paw.
SIMULTANEOUS_SECONDS = 0.035
#: A press made while this many other keys are already down is paw-like
#: (fast typists roll over 1-2 keys; 3+ is rare for fingers).
CROWDED_KEYS = 3
#: Fraction of presses in the window that must show paw contact.
PAW_CONTACT_RATIO = 0.30
#: Fewer vowels than this, among letters, is not language.
VOWEL_RATIO = 0.25
#: Fraction of consecutive different-key pairs that are physical neighbours.
ADJACENT_RATIO = 0.45
#: Faster than this many presses per second over the window is "very fast".
FAST_KEYS_PER_SECOND = 10.0


@dataclass(frozen=True)
class DetectorSettings:
    """Thresholds for every rule. A value of ``0`` disables that rule."""

    chord_keys: int = 5               # Rule 1: keys held at once ...
    chord_min_rows: int = 2           # ... spread over at least this many rows
    sit_keys: int = 3                 # Rule 2: keys held ...
    sit_seconds: float = 1.5          # ... for at least this long
    long_hold_seconds: float = 20.0   # Rule 3
    mash_window_keys: int = 12        # Rule 4: presses examined together ...
    mash_window_seconds: float = 3.0  # ... and the time span they must fit in
    mash_signals_needed: int = 3      # ... signals needed (paw contact included)
    click_storm_clicks: int = 0       # Rule 5: clicks ... (0 = off)
    click_storm_seconds: float = 2.0  # ... within this many seconds

    def with_overrides(self, overrides: Dict[str, float]) -> DetectorSettings:
        """Copy with some fields replaced (used for the advanced config section)."""
        cleaned = {}
        for name, value in overrides.items():
            if name not in SETTING_NAMES:
                raise ValueError(f"unknown detector setting {name!r}")
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
                raise ValueError(f"detector setting {name!r} must be a number >= 0")
            cleaned[name] = int(value) if name in INT_SETTINGS else float(value)
        return replace(self, **cleaned)


SETTING_NAMES = frozenset(f.name for f in fields(DetectorSettings))
INT_SETTINGS = frozenset(
    {"chord_keys", "chord_min_rows", "sit_keys", "mash_window_keys",
     "mash_signals_needed", "click_storm_clicks"}
)

#: Sensitivity presets. "medium" is the default and suits most people.
PRESETS: Dict[str, DetectorSettings] = {
    "low": DetectorSettings(
        chord_keys=6, chord_min_rows=3, sit_keys=4, sit_seconds=2.5,
        long_hold_seconds=0, mash_window_keys=16, mash_signals_needed=4,
    ),
    "medium": DetectorSettings(),
    "high": DetectorSettings(
        chord_keys=5, chord_min_rows=2, sit_keys=3, sit_seconds=1.0,
        long_hold_seconds=8.0, mash_window_keys=10, mash_signals_needed=2,
        click_storm_clicks=15,
    ),
}


@dataclass(frozen=True)
class Detection:
    """Why the detector thinks a cat is on the keyboard."""

    rule: str    # "chord" | "sit" | "long_hold" | "mash" | "click_storm"
    reason: str  # Human-readable; never contains key names (privacy).


@dataclass(frozen=True)
class KeyPress:
    """One fresh (non-auto-repeat) press of a non-modifier key."""

    key: str
    time: float
    others_held: int  # Non-modifier keys already down at that moment.


def mash_signals(window: Sequence[KeyPress]) -> List[str]:
    """Which "this isn't typing" signals a window of key presses shows.

    Exposed as a function so it can be unit-tested and printed in dry-run
    mode. See the module docstring for what each signal means.
    """
    signals: List[str] = []
    n = len(window)
    if n < 2:
        return signals
    keys = [p.key for p in window]

    # 1. Paw contact: near-simultaneous presses, or 4+ keys down together.
    contact = 0
    for i, press in enumerate(window):
        simultaneous = (
            i > 0
            and press.others_held >= 1
            and press.time - window[i - 1].time <= SIMULTANEOUS_SECONDS
        )
        if press.others_held >= CROWDED_KEYS or simultaneous:
            contact += 1
    if contact / n >= PAW_CONTACT_RATIO:
        signals.append("paw contact")

    # 2. No word breaks at all.
    if not any(k in SEPARATOR_KEYS for k in keys):
        signals.append("no spaces")

    # 3. Mostly letters, hardly any vowels.
    letters = [k for k in keys if len(k) == 1 and k.isalpha()]
    if len(letters) >= n / 2:
        vowel_share = sum(1 for k in letters if k in VOWELS) / len(letters)
        if vowel_share < VOWEL_RATIO:
            signals.append("no vowels")

    # 4. Consecutive keys are physical neighbours (repeats of one key don't count).
    pairs = [(a, b) for a, b in zip(keys, keys[1:]) if a != b]
    if pairs and sum(1 for a, b in pairs if are_adjacent(a, b)) / len(pairs) >= ADJACENT_RATIO:
        signals.append("clustered keys")

    # 5. Faster than fast typing.
    span = window[-1].time - window[0].time
    if span <= 0 or (n - 1) / span >= FAST_KEYS_PER_SECOND:
        signals.append("very fast")

    return signals


class CatDetector:
    """Feeds on key events and decides whether a cat is at work.

    Not thread-safe on its own; :class:`pawlock.engine.LockEngine` serialises
    access. Times are plain floats (``time.monotonic()``) passed in by the
    caller, which makes the detector easy to test with simulated time.
    """

    def __init__(self, settings: Optional[DetectorSettings] = None) -> None:
        self.settings = settings or DetectorSettings()
        self._held: Dict[str, float] = {}  # non-modifier key -> time first pressed
        self._presses: Deque[KeyPress] = deque(maxlen=max(self.settings.mash_window_keys, 1))
        self._clicks: Deque[float] = deque()

    # -- state management ----------------------------------------------------

    def reset(self) -> None:
        """Forget everything (called whenever the lock state changes)."""
        self._held.clear()
        self._presses.clear()
        self._clicks.clear()

    def update_settings(self, settings: DetectorSettings) -> None:
        self.settings = settings
        self._presses = deque(maxlen=max(settings.mash_window_keys, 1))
        self.reset()

    def forget(self, key: str) -> None:
        """Drop a key we assume was released without us seeing it."""
        self._held.pop(key, None)

    # -- events --------------------------------------------------------------

    def on_key(self, key: str, pressed: bool, now: float) -> Optional[Detection]:
        """Feed one key event. Returns a :class:`Detection` if a cat is likely."""
        if is_modifier(key):
            return None  # Ctrl/Shift/... are held legitimately all the time.
        if not pressed:
            self._held.pop(key, None)
            return None
        if key in self._held:
            # OS auto-repeat: the key is still physically down. Only the
            # time-based rules can have changed.
            return self._check_holds(now)
        others = len(self._held)
        self._held[key] = now
        self._presses.append(KeyPress(key, now, others))
        return self._check_chord() or self._check_holds(now) or self._check_mash()

    def on_click(self, now: float) -> Optional[Detection]:
        """Feed one mouse-button press."""
        s = self.settings
        if s.click_storm_clicks <= 0:
            return None
        self._clicks.append(now)
        while self._clicks and now - self._clicks[0] > s.click_storm_seconds:
            self._clicks.popleft()
        if len(self._clicks) >= s.click_storm_clicks:
            self._clicks.clear()
            return Detection(
                "click_storm",
                f"{s.click_storm_clicks}+ clicks within {s.click_storm_seconds:g}s",
            )
        return None

    def tick(self, now: float) -> Optional[Detection]:
        """Re-check the time-based rules when no events arrive (called ~4x/s)."""
        return self._check_holds(now)

    # -- rules ---------------------------------------------------------------

    def _check_chord(self) -> Optional[Detection]:
        s = self.settings
        if s.chord_keys <= 0 or len(self._held) < s.chord_keys:
            return None
        rows = {key_row(k) for k in self._held} - {None}
        if len(rows) < s.chord_min_rows:
            return None
        return Detection(
            "chord", f"{len(self._held)} keys pressed at once across {len(rows)} keyboard rows"
        )

    def _check_holds(self, now: float) -> Optional[Detection]:
        s = self.settings
        if s.sit_keys > 0 and len(self._held) >= s.sit_keys:
            long_held = sum(1 for t in self._held.values() if now - t >= s.sit_seconds)
            if long_held >= s.sit_keys:
                return Detection("sit", f"{long_held} keys held down for over {s.sit_seconds:g}s")
        if s.long_hold_seconds > 0:
            for key, t in self._held.items():
                if key not in HOLD_EXEMPT_KEYS and now - t >= s.long_hold_seconds:
                    return Detection(
                        "long_hold", f"a key held down for over {s.long_hold_seconds:g}s"
                    )
        return None

    def _check_mash(self) -> Optional[Detection]:
        s = self.settings
        if s.mash_window_keys <= 0 or len(self._presses) < s.mash_window_keys:
            return None
        window = list(self._presses)
        if window[-1].time - window[0].time > s.mash_window_seconds:
            return None
        signals = mash_signals(window)
        if "paw contact" in signals and len(signals) >= s.mash_signals_needed:
            self._presses.clear()  # Don't re-fire on the same presses.
            return Detection("mash", "keyboard mashing (" + ", ".join(signals) + ")")
        return None
