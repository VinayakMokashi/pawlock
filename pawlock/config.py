"""User settings: a small JSON file with forgiving, self-healing validation.

The settings file is created with defaults on first run. When it's edited
by hand, every value is checked on load. An invalid value is replaced by
its default and a warning is logged; it never stops PawLock from starting.
Keys starting with ``_`` are ignored, so you can leave notes in the file.

See ``docs/CONFIGURATION.md`` for a description of every option.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

from .detector import PRESETS, DetectorSettings
from .hotkey import Hotkey, PhraseMatcher

SENSITIVITIES = tuple(PRESETS)
OVERLAY_POSITIONS = ("top", "bottom", "center")
BACKENDS = ("auto", "native", "swap")
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")


@dataclass
class Config:
    # --- Locking ---------------------------------------------------------
    hotkey: str = "ctrl+alt+shift+l"
    unlock_phrase: str = "unlock"
    lock_mouse: bool = True
    start_locked: bool = False
    max_lock_minutes: float = 0.0          # 0 = no limit

    # --- Away mode -------------------------------------------------------
    away_lock: bool = True                 # lock when nobody has used the PC ...
    away_lock_minutes: float = 10.0        # ... for this long

    # --- Cat detection ---------------------------------------------------
    auto_detect: bool = True
    sensitivity: str = "medium"            # low | medium | high
    cooldown_seconds: float = 5.0
    detector_overrides: Dict[str, float] = field(default_factory=dict)

    # --- Feedback --------------------------------------------------------
    tray: bool = True
    # The Tk overlay is off by default on macOS, where Tk and pynput's event
    # tap don't always get along (see docs/TROUBLESHOOTING.md).
    overlay: bool = field(default_factory=lambda: sys.platform != "darwin")
    overlay_position: str = "top"          # top | bottom | center
    sound: bool = True
    notifications: bool = True

    # --- Safety & advanced -----------------------------------------------
    watchdog_seconds: float = 15.0
    stale_key_seconds: float = 10.0
    backend: str = "auto"                  # auto | native | swap
    log_level: str = "INFO"

    # -- derived values ----------------------------------------------------

    def parsed_hotkey(self) -> Hotkey:
        return Hotkey.parse(self.hotkey)

    def detector_settings(self) -> DetectorSettings:
        return PRESETS[self.sensitivity].with_overrides(self.detector_overrides)

    def away_seconds(self) -> float:
        """Away-mode delay in seconds (0 when away mode is off)."""
        return 60.0 * self.away_lock_minutes if self.away_lock else 0.0


# ---------------------------------------------------------------------------
# Validators: take a raw JSON value, return the cleaned value or raise.
# ---------------------------------------------------------------------------

def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    raise ValueError("must be true or false")


def _number(minimum: float, maximum: float = float("inf")) -> Callable[[Any], float]:
    def check(value: Any) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("must be a number")
        if not minimum <= value <= maximum:
            raise ValueError(f"must be between {minimum:g} and {maximum:g}")
        return float(value)

    return check


def _choice(options: Tuple[str, ...], upper: bool = False) -> Callable[[Any], str]:
    def check(value: Any) -> str:
        text = str(value).strip()
        text = text.upper() if upper else text.lower()
        if text not in options:
            raise ValueError("must be one of: " + ", ".join(options))
        return text

    return check


def _hotkey(value: Any) -> str:
    return str(Hotkey.parse(value))


def _overrides(value: Any) -> Dict[str, float]:
    if not isinstance(value, dict):
        raise ValueError("must be an object like {\"chord_keys\": 6}")
    DetectorSettings().with_overrides(value)  # Raises with a helpful message.
    return dict(value)


VALIDATORS: Dict[str, Callable[[Any], Any]] = {
    "hotkey": _hotkey,
    "unlock_phrase": PhraseMatcher.validate,
    "lock_mouse": _bool,
    "start_locked": _bool,
    "max_lock_minutes": _number(0, 24 * 60),
    "away_lock": _bool,
    "away_lock_minutes": _number(0.5, 24 * 60),
    "auto_detect": _bool,
    "sensitivity": _choice(SENSITIVITIES),
    "cooldown_seconds": _number(0, 600),
    "detector_overrides": _overrides,
    "tray": _bool,
    "overlay": _bool,
    "overlay_position": _choice(OVERLAY_POSITIONS),
    "sound": _bool,
    "notifications": _bool,
    "watchdog_seconds": _number(3, 600),
    "stale_key_seconds": _number(0, 3600),
    "backend": _choice(BACKENDS),
    "log_level": _choice(LOG_LEVELS, upper=True),
}

assert set(VALIDATORS) == {f.name for f in fields(Config)}, "every setting needs a validator"

_HEADER = {
    "_readme": (
        "PawLock settings. Edit, save, then choose 'Reload settings' from the tray "
        "menu (or restart PawLock). Every option is explained in docs/CONFIGURATION.md. "
        "Invalid values fall back to their defaults and are reported in the log."
    )
}


def load_config(path: Path) -> Tuple[Config, List[str]]:
    """Load settings from *path*, creating the file with defaults if missing.

    Returns ``(config, warnings)``. Never raises for bad user input.
    """
    if not path.exists():
        config = Config()
        warnings: List[str] = []
        try:
            save_config(config, path)
        except OSError as exc:
            warnings.append(f"Could not create settings file {path}: {exc}")
        return config, warnings

    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(raw, dict):
            raise ValueError("the file must contain a JSON object { ... }")
    except (OSError, ValueError) as exc:
        # Leave the user's file untouched so they can fix it.
        return Config(), [f"Could not read {path} ({exc}); using default settings."]

    return config_from_dict(raw)


def config_from_dict(raw: Dict[str, Any]) -> Tuple[Config, List[str]]:
    config = Config()
    warnings: List[str] = []
    for key, value in raw.items():
        if key.startswith("_"):
            continue
        validator = VALIDATORS.get(key)
        if validator is None:
            warnings.append(f"Unknown setting {key!r} was ignored.")
            continue
        try:
            setattr(config, key, validator(value))
        except (ValueError, TypeError) as exc:
            warnings.append(
                f"Setting {key!r} = {value!r} is invalid ({exc}); "
                f"using the default {getattr(config, key)!r}."
            )
    return config, warnings


# ---------------------------------------------------------------------------
# The simple settings form (PawLock window → Settings tab)
# ---------------------------------------------------------------------------

#: The window offers Ctrl + Alt + Shift + <letter>: safe and easy to explain.
SIMPLE_HOTKEY_PREFIX = "ctrl+alt+shift+"


def simple_settings(config: Config) -> Dict[str, Any]:
    """Current settings as the simple form shows them."""
    rest = config.hotkey[len(SIMPLE_HOTKEY_PREFIX):] if config.hotkey.startswith(SIMPLE_HOTKEY_PREFIX) else ""
    letter = rest if len(rest) == 1 and rest.isalpha() else ""
    return {
        "letter": letter.upper(),
        "custom_hotkey": "" if letter else Hotkey.parse(config.hotkey).display(),
        "unlock_phrase": config.unlock_phrase,
        "auto_detect": config.auto_detect,
        "sensitivity": config.sensitivity,
        "away_lock": config.away_lock,
        "away_lock_minutes": f"{config.away_lock_minutes:g}",
        "lock_mouse": config.lock_mouse,
        "sound": config.sound,
    }


def apply_simple_settings(config: Config, values: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """Validate what the user entered in the form.

    Returns ``(changes, errors)``: ``changes`` maps setting names to new values
    (only settings that actually changed); ``errors`` are friendly sentences.
    """
    current = simple_settings(config)
    changes: Dict[str, Any] = {}
    errors: List[str] = []

    letter = str(values.get("letter", "")).strip().lower()
    if letter and letter != current["letter"].lower():
        if len(letter) == 1 and letter.isalpha():
            changes["hotkey"] = SIMPLE_HOTKEY_PREFIX + letter
        else:
            errors.append("Please choose a letter for the shortcut.")

    try:
        phrase = PhraseMatcher.validate(str(values.get("unlock_phrase", "")))
        if phrase != config.unlock_phrase:
            changes["unlock_phrase"] = phrase
    except ValueError as exc:
        errors.append(f"Unlock word: {exc}.")

    sensitivity = str(values.get("sensitivity", config.sensitivity))
    if sensitivity not in SENSITIVITIES:
        errors.append("Please choose a cat-detection level.")
    elif sensitivity != config.sensitivity:
        changes["sensitivity"] = sensitivity

    try:
        minutes = float(str(values.get("away_lock_minutes", "")).strip())
        if not 1 <= minutes <= 240:
            raise ValueError
        if minutes != config.away_lock_minutes:
            changes["away_lock_minutes"] = minutes
    except ValueError:
        errors.append("Away mode: enter a number of minutes between 1 and 240.")

    for key in ("auto_detect", "away_lock", "lock_mouse", "sound"):
        value = bool(values.get(key, getattr(config, key)))
        if value != getattr(config, key):
            changes[key] = value

    return (changes if not errors else {}), errors


def update_config_file(path: Path, changes: Dict[str, Any]) -> None:
    """Write *changes* into the settings file, keeping everything else (and notes) as is.

    Raises ``OSError``/``ValueError`` if the file can't be read or written.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(raw, dict):
            raise ValueError("the settings file is not a JSON object")
    except FileNotFoundError:
        raw = {**_HEADER, **asdict(Config())}
    raw.update(changes)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def save_config(config: Config, path: Path) -> None:
    """Write settings atomically (a crash mid-write can't corrupt the file)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {**_HEADER, **asdict(config)}
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
