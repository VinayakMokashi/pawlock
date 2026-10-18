"""The watchdog and crash guards: you always get your keyboard back."""

import threading

from pawlock.backends.base import InputBackend
from pawlock.engine import REASON_SAFETY, REASON_TIMEOUT
from pawlock.safety import Watchdog, install_crash_guards, run_with_timeout


class FakeBackend(InputBackend):
    name = "fake"

    def __init__(self, engine, selective=True):
        super().__init__(engine)
        self.selective = selective
        self.healthy = True
        self.restarts = 0
        self.stops = 0

    def start(self):
        self.healthy = True

    def stop(self):
        self.stops += 1

    def is_healthy(self):
        return self.healthy

    def restart(self):
        self.restarts += 1
        self.healthy = True


def make_watchdog(engine, backend, clock, heartbeat=None, **kwargs):
    fatal = []
    dog = Watchdog(
        engine=engine,
        backend=backend,
        heartbeat=heartbeat or clock,
        clock=clock,
        on_fatal=fatal.append,
        **kwargs,
    )
    return dog, fatal


def test_max_lock_duration(make_engine, clock, changes):
    engine = make_engine()
    dog, _ = make_watchdog(engine, FakeBackend(engine), clock, max_lock_seconds=60)
    engine.lock()
    clock.advance(59)
    dog.check()
    assert engine.locked
    clock.advance(2)
    dog.check()
    assert not engine.locked
    assert changes[-1].reason == REASON_TIMEOUT


def test_no_limit_by_default(make_engine, clock):
    engine = make_engine()
    dog, _ = make_watchdog(engine, FakeBackend(engine), clock)
    engine.lock()
    clock.advance(24 * 3600)
    dog.check()
    assert engine.locked


def test_frozen_controller_releases_the_lock(make_engine, clock, changes):
    engine = make_engine()
    backend = FakeBackend(engine, selective=False)
    last_beat = clock.now
    dog, fatal = make_watchdog(engine, backend, clock, heartbeat=lambda: last_beat, controller_timeout=15)
    engine.lock()
    clock.advance(10)
    dog.check()
    assert engine.locked
    clock.advance(10)
    dog.check()
    assert not engine.locked
    assert changes[-1].reason == REASON_SAFETY
    assert backend.stops == 1  # swap backend: the grab is released directly
    assert fatal == []


def test_dead_hook_is_reinstalled_and_lock_released(make_engine, clock):
    engine = make_engine()
    backend = FakeBackend(engine)
    dog, fatal = make_watchdog(engine, backend, clock)
    engine.lock()
    backend.healthy = False
    dog.check()
    assert not engine.locked
    assert backend.restarts == 1
    assert fatal == []


def test_hooks_that_keep_dying_trigger_the_last_resort(make_engine, clock):
    engine = make_engine()
    backend = FakeBackend(engine)
    dog, fatal = make_watchdog(engine, backend, clock, max_restarts=3)
    for _ in range(4):
        backend.healthy = False
        dog.check()
        clock.advance(1)
    assert backend.restarts == 3
    assert len(fatal) == 1


def test_crash_guard_releases_the_lock(make_engine, clock):
    engine = make_engine()
    engine.lock()
    original_hook = threading.excepthook
    try:
        install_crash_guards(lambda reason: engine.force_unlock(REASON_SAFETY, reason))
        thread = threading.Thread(target=lambda: 1 / 0)
        thread.start()
        thread.join()
        assert not engine.locked
    finally:
        threading.excepthook = original_hook
        import sys

        sys.excepthook = sys.__excepthook__


def test_run_with_timeout():
    assert run_with_timeout(lambda: None, 1.0) is True
    gate = threading.Event()
    assert run_with_timeout(lambda: gate.wait(5), 0.05) is False
    gate.set()

    def fail():
        raise RuntimeError("nope")

    assert run_with_timeout(fail, 1.0) is False
