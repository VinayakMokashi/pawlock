"""Layers of protection against being locked out of your own computer.

PawLock's promise is simple: **whatever goes wrong, you get your keyboard
back.** These are the layers, from gentlest to most drastic:

1. **Fail-open engine.** Any error while handling an event lets that event
   through and releases the lock (see ``engine.py``).
2. **Crash guards.** Unhandled exceptions on any thread release the lock
   (``install_crash_guards``).
3. **Signal handlers.** Ctrl+C, ``kill``, logoff and ``pawlock --stop`` all
   release the lock and shut down cleanly (``install_signal_handlers``).
4. **Watchdog thread.** Independently checks, once a second, that:

   * the lock hasn't exceeded ``max_lock_minutes`` (if set),
   * the controller thread is still alive (heartbeat),
   * the OS hooks are still installed (otherwise re-installs them).

5. **Hard exit.** If releasing the hooks itself hangs, the process kills
   itself with ``os._exit``. The OS removes every hook and grab owned by a
   dead process, so input always comes back.
6. **The operating system.** Ctrl+Alt+Del on Windows can never be blocked.
   Windows/macOS also drop hooks that stop responding.
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import threading
import time
from collections import deque
from typing import Callable, Deque, Optional

from .backends.base import InputBackend
from .engine import REASON_SAFETY, REASON_TIMEOUT, LockEngine
from .logging_setup import flush_logs

log = logging.getLogger(__name__)

#: Exit code used for the emergency self-termination.
EXIT_EMERGENCY = 70


def run_with_timeout(fn: Callable[[], None], timeout: float, name: str = "safety-task") -> bool:
    """Run *fn* on a helper thread; True if it finished within *timeout* seconds."""
    errors = []

    def target() -> None:
        try:
            fn()
        except Exception as exc:  # pragma: no cover - logged
            errors.append(exc)
            log.exception("%s failed", name)

    worker = threading.Thread(target=target, name=name, daemon=True)
    worker.start()
    worker.join(timeout)
    return not worker.is_alive() and not errors


def hard_exit(reason: str, code: int = EXIT_EMERGENCY) -> None:  # pragma: no cover - exits
    """Last resort: terminate immediately. The OS releases all input hooks."""
    log.critical("Emergency exit: %s", reason)
    flush_logs()
    os._exit(code)


class Watchdog:
    """Background thread that keeps an eye on the lock, the controller and the hooks."""

    def __init__(
        self,
        *,
        engine: LockEngine,
        backend: InputBackend,
        heartbeat: Callable[[], float],
        controller_timeout: float = 15.0,
        max_lock_seconds: float = 0.0,
        on_fatal: Callable[[str], None] = hard_exit,
        clock: Callable[[], float] = time.monotonic,
        interval: float = 1.0,
        max_restarts: int = 5,
        restart_window: float = 60.0,
    ) -> None:
        self.engine = engine
        self.backend = backend
        self.heartbeat = heartbeat
        self.controller_timeout = controller_timeout
        self.max_lock_seconds = max_lock_seconds
        self.on_fatal = on_fatal
        self.clock = clock
        self.interval = interval
        self.max_restarts = max_restarts
        self.restart_window = restart_window
        self._restarts: Deque[float] = deque()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.paused = False  # Set while the app deliberately restarts the backend.

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="watchdog", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.check()
            except Exception:  # pragma: no cover - the watchdog must not die
                log.exception("Watchdog check failed")

    def check(self) -> None:
        """One round of checks (public so tests can drive it step by step)."""
        if self.paused:
            return
        now = self.clock()

        # 1. Maximum lock duration.
        since = self.engine.locked_since
        limit = self.max_lock_seconds
        if limit > 0 and self.engine.locked and since is not None and now - since >= limit:
            log.warning("Maximum lock time (%.0fs) reached; unlocking", limit)
            self.engine.try_unlock(REASON_TIMEOUT)

        # 2. Controller heartbeat. Only matters while locked: in swap mode the
        #    controller is what releases the grab, so it must be alive.
        if self.engine.locked and now - self.heartbeat() > self.controller_timeout:
            log.critical("Controller thread stopped responding while locked")
            self.engine.force_unlock(REASON_SAFETY, "PawLock stopped responding, so it unlocked to be safe")
            if not self.backend.selective and not run_with_timeout(self.backend.stop, 3.0, "release-grab"):
                self.on_fatal("could not release the input grab")

        # 3. Hook health.
        if not self.backend.is_healthy():
            self._recover_backend(now)

    def _recover_backend(self, now: float) -> None:
        while self._restarts and now - self._restarts[0] > self.restart_window:
            self._restarts.popleft()
        if len(self._restarts) >= self.max_restarts:
            self.on_fatal(f"input hooks failed {len(self._restarts)} times in {self.restart_window:.0f}s")
            return
        self._restarts.append(now)
        log.error("An input hook stopped unexpectedly; unlocking and re-installing it")
        self.engine.force_unlock(REASON_SAFETY, "an input hook stopped unexpectedly")
        if not run_with_timeout(self.backend.restart, 5.0, "restart-hooks"):
            log.error("Could not re-install the input hooks (will retry)")


def install_crash_guards(on_crash: Callable[[str], None]) -> None:
    """Release the lock on any unhandled exception, in any thread."""
    previous_hook = sys.excepthook

    def excepthook(exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
        log.critical("Unhandled exception; releasing input", exc_info=(exc_type, exc, tb))
        _call_quietly(on_crash, f"crash: {exc_type.__name__}")
        previous_hook(exc_type, exc, tb)

    def thread_hook(args: threading.ExceptHookArgs) -> None:
        if args.exc_type is SystemExit:
            return
        name = args.thread.name if args.thread is not None else "?"
        log.critical(
            "Unhandled exception in thread %s; releasing input",
            name,
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )
        _call_quietly(on_crash, f"crash in thread {name}")

    sys.excepthook = excepthook
    threading.excepthook = thread_hook


def install_signal_handlers(on_signal: Callable[[str], None]) -> None:
    """Shut down cleanly on Ctrl+C, SIGTERM (``kill``/``pawlock --stop``), logoff..."""
    if threading.current_thread() is not threading.main_thread():
        return
    for name in ("SIGINT", "SIGTERM", "SIGBREAK", "SIGHUP", "SIGQUIT"):
        signum = getattr(signal, name, None)
        if signum is None:
            continue
        try:
            signal.signal(signum, lambda _s, _f, n=name: on_signal(n))
        except (OSError, ValueError, RuntimeError):  # pragma: no cover - platform specific
            pass


def _call_quietly(fn: Callable[[str], None], arg: str) -> None:
    try:
        fn(arg)
    except Exception:  # pragma: no cover
        log.exception("Safety callback failed")
