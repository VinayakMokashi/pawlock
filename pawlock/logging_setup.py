"""Logging to a small rotating file (and the console when there is one).

Privacy note: PawLock logs *state changes* ("locked: cat detected") and
errors. It never logs which keys you pressed.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

_FORMAT = "%(asctime)s %(levelname)-8s [%(threadName)s] %(name)s: %(message)s"


def setup_logging(level: str = "INFO", log_file: Optional[Path] = None, console: bool = True) -> None:
    """Configure the ``pawlock`` logger (and pynput's, so its errors land in our log)."""
    formatter = logging.Formatter(_FORMAT)
    handlers = []

    if log_file is not None:
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(
                log_file, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
            )
            file_handler.setFormatter(formatter)
            handlers.append(file_handler)
        except OSError:
            pass  # A read-only disk must never stop PawLock from protecting you.

    # Windowed (no-console) executables have sys.stderr set to None.
    if console and sys.stderr is not None:
        stream_handler = logging.StreamHandler(sys.stderr)
        stream_handler.setFormatter(formatter)
        handlers.append(stream_handler)

    for name, logger_level in (("pawlock", level), ("pynput", "WARNING")):
        logger = logging.getLogger(name)
        logger.setLevel(logger_level)
        logger.propagate = False
        for old in list(logger.handlers):
            logger.removeHandler(old)
        for handler in handlers:
            logger.addHandler(handler)


def flush_logs() -> None:
    """Flush every handler (used right before an emergency hard exit)."""
    for name in ("pawlock", "pynput"):
        for handler in logging.getLogger(name).handlers:
            try:
                handler.flush()
            except Exception:  # pragma: no cover - best effort
                pass
