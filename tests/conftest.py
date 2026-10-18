"""Shared test fixtures.

None of the tests import pynput or touch real input devices, so the whole
suite runs headless on any OS (including CI containers without a display).
"""

from __future__ import annotations

from typing import Iterable, List, Optional, Tuple

import pytest

from pawlock.detector import CatDetector, DetectorSettings
from pawlock.engine import LockEngine, StateChange
from pawlock.hotkey import Hotkey


class FakeClock:
    """A monotonic clock the test controls."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Keep every test's settings/logs/PID files in a temporary folder."""
    home = tmp_path / "pawlock-home"
    monkeypatch.setenv("PAWLOCK_HOME", str(home))
    return home


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def changes() -> List[StateChange]:
    return []


@pytest.fixture
def make_engine(clock, changes):
    """Factory for a LockEngine wired to the fake clock and a change recorder."""

    def factory(
        hotkey: str = "ctrl+alt+shift+l",
        detector: Optional[CatDetector] = None,
        **kwargs,
    ) -> LockEngine:
        kwargs.setdefault("unlock_phrase", "unlock")
        kwargs.setdefault("cooldown_seconds", 5.0)
        return LockEngine(
            Hotkey.parse(hotkey),
            detector=detector,
            on_change=changes.append,
            clock=clock,
            **kwargs,
        )

    return factory


def press_sequence(
    engine: LockEngine, clock: FakeClock, steps: Iterable[Tuple[str, bool]], gap: float = 0.05
) -> List[bool]:
    """Feed (key, pressed) pairs to the engine; returns the swallow decisions."""
    decisions = []
    for key, pressed in steps:
        clock.advance(gap)
        decisions.append(engine.handle_key(key, pressed))
    return decisions


def tap(key: str) -> List[Tuple[str, bool]]:
    return [(key, True), (key, False)]


def hotkey_steps() -> List[Tuple[str, bool]]:
    """Ctrl, Alt, Shift down; L down/up; modifiers up: the human way."""
    return [
        ("ctrl_l", True), ("alt_l", True), ("shift_l", True),
        ("l", True), ("l", False),
        ("shift_l", False), ("alt_l", False), ("ctrl_l", False),
    ]


def quiet_detector(**overrides) -> CatDetector:
    """A detector with every rule off except the ones a test switches on."""
    base = dict(
        chord_keys=0, sit_keys=0, long_hold_seconds=0, mash_window_keys=0, click_storm_clicks=0,
    )
    base.update(overrides)
    return CatDetector(DetectorSettings(**base))
