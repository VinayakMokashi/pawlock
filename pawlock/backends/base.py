"""The interface every input backend implements."""

from __future__ import annotations

import abc

from ..engine import LockEngine


class BackendError(RuntimeError):
    """Raised when the OS refuses to let us hook input (permissions, Wayland...)."""


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
