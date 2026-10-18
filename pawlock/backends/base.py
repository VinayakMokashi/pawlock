"""The interface every input backend implements."""

from __future__ import annotations

import abc
import threading
from typing import Any

from ..engine import LockEngine


class BackendError(RuntimeError):
    """Raised when the OS refuses to let us hook input (permissions, Wayland...)."""


def wait_until_ready(listener: Any, timeout: float = 5.0) -> None:
    """``listener.wait()`` with a time limit.

    pynput's own ``wait()`` blocks forever if the hook thread dies before it
    reports ready, which would freeze PawLock's startup. We wait on a helper
    thread instead and give up after *timeout* seconds.
    """
    waiter = threading.Thread(target=listener.wait, name="hook-ready", daemon=True)
    waiter.start()
    waiter.join(timeout)
    if waiter.is_alive():
        raise BackendError(f"the input hook did not start within {timeout:g} seconds")


class InputBackend(abc.ABC):
    """Connects the operating system's input stream to a :class:`LockEngine`.

    A backend installs a global keyboard hook and a global mouse hook, turns
    each OS event into a call to the engine, and swallows the event when the
    engine says so.
    """

    #: Short name shown in logs and ``pawlock --doctor``.
    name = "abstract"

    #: True if the backend can swallow individual events (Windows, macOS).
    #: False if it has to swap whole listeners when the lock state changes.
    selective = True

    def __init__(self, engine: LockEngine) -> None:
        self.engine = engine

    @abc.abstractmethod
    def start(self) -> None:
        """Install the hooks. Raises :class:`BackendError` on failure."""

    @abc.abstractmethod
    def stop(self) -> None:
        """Remove the hooks. Must be idempotent and safe from any thread."""

    @abc.abstractmethod
    def is_healthy(self) -> bool:
        """False if a hook died (the watchdog will restart us)."""

    def on_state_change(self, locked: bool) -> None:  # noqa: B027 - optional hook
        """Called by the controller thread after every lock/unlock (default: nothing to do)."""

    def restart(self) -> None:
        self.stop()
        self.start()
