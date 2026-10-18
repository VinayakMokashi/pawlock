"""Synthetic keyboard input: humans typing and cats being cats.

Used by the test suite and by ``scripts/detector_benchmark.py`` to check the
cat detector against realistic input without needing a real cat (Snowy was
unavailable for testing). Every generator is deterministic for a given seed.

An event is a tuple ``(time_seconds, key_name, pressed)``.
"""

from __future__ import annotations

import random
from typing import Iterable, List, Optional, Sequence, Tuple

from .keys import _POSITIONS, are_adjacent, from_char

Event = Tuple[float, str, bool]

#: Keys a paw can land on (everything with a known position, plus space).
PAW_KEYS: List[str] = sorted(k for k in _POSITIONS if len(k) == 1) + ["space"]
_NEIGHBOURS = {k: [n for n in PAW_KEYS if are_adjacent(k, n)] for k in PAW_KEYS}

#: Typical OS auto-repeat: starts after ~0.5 s, then ~30 per second.
REPEAT_DELAY = 0.5
REPEAT_INTERVAL = 0.033


def _sorted(events: Iterable[Event]) -> List[Event]:
    # Releases before presses at the same instant, like real hardware scans.
    return sorted(events, key=lambda e: (e[0], e[2]))


def _with_autorepeat(key: str, down: float, up: float) -> List[Event]:
    events = [(down, key, True)]
    t = down + REPEAT_DELAY
    while t < up:
        events.append((t, key, True))
        t += REPEAT_INTERVAL
    events.append((up, key, False))
    return events


def human_typing(
    text: str,
    wpm: float = 70,
    seed: int = 0,
    start: float = 0.0,
    hold: Tuple[float, float] = (0.06, 0.12),
    jitter: float = 0.35,
) -> List[Event]:
    """A person typing *text*: steady rhythm, short holds, Shift for capitals."""
    rng = random.Random(seed)
    interval = 60.0 / (wpm * 5)  # 1 "word" = 5 keystrokes.
    events: List[Event] = []
    t = start
    for ch in text:
        key = "enter" if ch == "\n" else from_char(ch)
        if key is None:
            continue
        t += interval * rng.uniform(1 - jitter, 1 + jitter)
        held = rng.uniform(*hold)
        shifted = ch.isupper() or (len(ch) == 1 and not ch.isalnum() and from_char(ch) != ch and ch != " ")
        if shifted:
            events += [(t - 0.04, "shift_l", True), (t + held + 0.02, "shift_l", False)]
        events += [(t, key, True), (t + held, key, False)]
    return _sorted(events)


def cat_walk(
    steps: int = 6,
    seed: int = 0,
    start: float = 0.0,
    paw_size: Tuple[int, int] = (2, 4),
    step_gap: Tuple[float, float] = (0.2, 0.45),
    hold: Tuple[float, float] = (0.12, 0.35),
) -> List[Event]:
    """A cat strolling across the keyboard: clusters of neighbouring keys per step."""
    rng = random.Random(seed)
    events: List[Event] = []
    t = start
    centre = rng.choice(PAW_KEYS)
    for _ in range(steps):
        neighbours = _NEIGHBOURS[centre]
        size = min(rng.randint(*paw_size), len(neighbours) + 1)
        cluster = [centre] + rng.sample(neighbours, size - 1)
        for key in cluster:
            down = t + rng.uniform(0.0, 0.02)  # A paw lands all at once.
            events += [(down, key, True), (down + rng.uniform(*hold), key, False)]
        t += rng.uniform(*step_gap)
        # Next paw lands a few keys away (cats walk *across* keyboards).
        centre = rng.choice([k for k in PAW_KEYS if k != centre])
    return _sorted(events)


def cat_sit(
    keys: Optional[Sequence[str]] = None,
    duration: float = 3.0,
    seed: int = 0,
    start: float = 0.0,
) -> List[Event]:
    """A cat sitting down: many keys pressed together and held, last one auto-repeating."""
    rng = random.Random(seed)
    if keys is None:
        centre = rng.choice([k for k in PAW_KEYS if len(_NEIGHBOURS[k]) >= 6])
        keys = [centre] + rng.sample(_NEIGHBOURS[centre], 6)
    events: List[Event] = []
    downs = sorted(start + rng.uniform(0.0, 0.15) for _ in keys)
    for i, (key, down) in enumerate(zip(keys, downs)):
        up = start + duration + rng.uniform(0.0, 0.1)
        if i == len(keys) - 1:
            events += _with_autorepeat(key, down, up)  # OS repeats the last key only.
        else:
            events += [(down, key, True), (up, key, False)]
    return _sorted(events)


def key_held(key: str, duration: float, start: float = 0.0) -> List[Event]:
    """One key held down (with auto-repeat), e.g. a toe bean on "k"."""
    return _with_autorepeat(key, start, start + duration)


def taps(keys: str, rate: float = 8.0, start: float = 0.0, hold: float = 0.05) -> List[Event]:
    """Separate, non-overlapping taps of the given keys at *rate* per second."""
    events: List[Event] = []
    for i, ch in enumerate(keys):
        key = from_char(ch) or ch
        t = start + i / rate
        events += [(t, key, True), (t + hold, key, False)]
    return _sorted(events)


SAMPLE_TEXT = (
    "The quick brown fox jumps over the lazy dog. "
    "My cat Snowy likes to sleep on my laptop when it is warm, "
    "so I wrote a small program to lock the keyboard while she naps. "
    "It should never get in the way of normal typing, even when I type fast.\n"
    "def handle_key(self, key, pressed): return self.engine.locked and not pressed\n"
    "Meeting notes: ship v1.0 on Friday, update the README, thank everyone!"
)
