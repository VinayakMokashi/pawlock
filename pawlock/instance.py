"""One PawLock at a time, and a reliable way to stop the running one.

The running instance writes a tiny JSON "PID file" with its process ID *and*
its start time. ``pawlock --stop`` only terminates a process if both match.
Process IDs get recycled, and we never want to kill some unrelated program
that happens to have inherited an old PID.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

import psutil

from . import __version__


def _read(path: Path) -> Optional[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def find_running(path: Path) -> Optional[psutil.Process]:
    """The live PawLock process recorded in *path*, if there is one (other than us)."""
    data = _read(path)
    if not data:
        return None
    try:
        process = psutil.Process(int(data["pid"]))
        if process.pid == os.getpid():
            return None
        if abs(process.create_time() - float(data["created"])) > 1.0:
            return None  # The PID now belongs to a different program.
        return process if process.is_running() else None
    except (psutil.Error, KeyError, TypeError, ValueError):
        return None


class InstanceGuard:
    """Owns the PID file for the lifetime of the app."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._owned = False

    def acquire(self) -> bool:
        """Claim the PID file. False if another PawLock is already running."""
        if find_running(self.path) is not None:
            return False
        me = psutil.Process()
        payload = {"pid": me.pid, "created": me.create_time(), "version": __version__}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp, self.path)
        self._owned = True
        return True

    def release(self) -> None:
        if not self._owned:
            return
        self._owned = False
        data = _read(self.path)
        if data and data.get("pid") == os.getpid():
            try:
                self.path.unlink()
            except OSError:
                pass


def stop_running(path: Path, timeout: float = 5.0) -> str:
    """Stop the running PawLock. Returns ``"stopped"``, ``"not-running"`` or ``"failed"``.

    On macOS/Linux this sends SIGTERM, which PawLock handles by unlocking and
    exiting cleanly. On Windows it terminates the process outright. Windows
    removes the hooks of a terminated process, so input comes back either way.
    """
    process = find_running(path)
    if process is None:
        return "not-running"
    try:
        process.terminate()
        try:
            process.wait(timeout)
        except psutil.TimeoutExpired:
            process.kill()
            process.wait(timeout)
    except psutil.NoSuchProcess:
        pass
    except psutil.Error:
        return "failed"
    try:
        path.unlink()
    except OSError:
        pass
    return "stopped"
