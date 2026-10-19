import json

from pawlock.config import Config, config_from_dict, load_config, save_config
from pawlock.detector import PRESETS


def test_missing_file_is_created_with_defaults(tmp_path):
    path = tmp_path / "config.json"
    config, warnings = load_config(path)
    assert warnings == []
    assert config == Config()
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["hotkey"] == "ctrl+alt+shift+l"
    assert "_readme" in saved


def test_round_trip(tmp_path):
    path = tmp_path / "config.json"
    original = Config(hotkey="ctrl+alt+k", sensitivity="low", sound=False, max_lock_minutes=30)
    save_config(original, path)
    loaded, warnings = load_config(path)
    assert warnings == []
    assert loaded == original


def test_invalid_values_fall_back_to_defaults_with_warnings():
    config, warnings = config_from_dict(
        {
            "hotkey": "l",                 # no modifiers
            "unlock_phrase": "no",         # too short
            "sensitivity": "extreme",
            "max_lock_minutes": -5,
            "sound": "yes",                # not a bool
            "detector_overrides": {"chord_keyz": 3},
        }
    )
    defaults = Config()
    assert config.hotkey == defaults.hotkey
    assert config.unlock_phrase == defaults.unlock_phrase
    assert config.sensitivity == defaults.sensitivity
    assert config.max_lock_minutes == defaults.max_lock_minutes
    assert config.sound is True
    assert config.detector_overrides == {}
    assert len(warnings) == 6


def test_values_are_normalised():
    config, warnings = config_from_dict(
        {"hotkey": "Shift + Ctrl + Alt + L", "sensitivity": "HIGH", "log_level": "debug", "unlock_phrase": "Snowy1"}
    )
    assert warnings == []
    assert config.hotkey == "ctrl+alt+shift+l"
    assert config.sensitivity == "high"
    assert config.log_level == "DEBUG"
    assert config.unlock_phrase == "snowy1"


def test_unknown_and_comment_keys():
    config, warnings = config_from_dict({"_note": "hello", "colour": "blue"})
    assert config == Config()
    assert warnings == ["Unknown setting 'colour' was ignored."]


def test_broken_json_uses_defaults_and_leaves_the_file_alone(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{ this is not json", encoding="utf-8")
    config, warnings = load_config(path)
    assert config == Config()
    assert len(warnings) == 1 and "Could not read" in warnings[0]
    assert path.read_text(encoding="utf-8") == "{ this is not json"


def test_detector_settings_merge_preset_and_overrides():
    config, _ = config_from_dict({"sensitivity": "low", "detector_overrides": {"chord_keys": 9}})
    settings = config.detector_settings()
    assert settings.chord_keys == 9
    assert settings.sit_keys == PRESETS["low"].sit_keys


def test_away_mode_settings():
    config = Config()
    assert config.away_lock is True and config.away_lock_minutes == 10
    assert config.away_seconds() == 600
    config, warnings = config_from_dict({"away_lock": False, "away_lock_minutes": 3})
    assert warnings == [] and config.away_seconds() == 0
    _, warnings = config_from_dict({"away_lock_minutes": 0})
    assert len(warnings) == 1  # below the 0.5 minute minimum


# ---------------------------------------------------------------------------
# The simple settings form (PawLock window)
# ---------------------------------------------------------------------------

from pawlock.config import apply_simple_settings, simple_settings, update_config_file  # noqa: E402


def form(**overrides):
    values = simple_settings(Config())
    values.update(overrides)
    return values


def test_simple_settings_defaults():
    values = simple_settings(Config())
    assert values["letter"] == "L" and values["custom_hotkey"] == ""
    assert values["away_lock_minutes"] == "10" and values["sensitivity"] == "medium"


def test_custom_hotkey_is_flagged():
    from pawlock.hotkey import Hotkey

    values = simple_settings(Config(hotkey="ctrl+alt+k"))
    assert values["letter"] == ""
    assert values["custom_hotkey"] == Hotkey.parse("ctrl+alt+k").display()  # "Control + Option + K" on a Mac


def test_unchanged_form_changes_nothing():
    assert apply_simple_settings(Config(), form()) == ({}, [])


def test_form_changes_are_validated_and_collected():
    changes, errors = apply_simple_settings(
        Config(), form(letter="K", unlock_phrase="Snowy", sensitivity="low", away_lock_minutes="15",
                       sound=False, away_lock=False)
    )
    assert errors == []
    assert changes == {"hotkey": "ctrl+alt+shift+k", "unlock_phrase": "snowy", "sensitivity": "low",
                       "away_lock_minutes": 15.0, "sound": False, "away_lock": False}


def test_form_errors_are_friendly_and_save_nothing():
    changes, errors = apply_simple_settings(Config(), form(unlock_phrase="no", away_lock_minutes="soon", letter="K"))
    assert changes == {}
    assert errors[0].startswith("Unlock word:")
    assert errors[1].startswith("Away mode:")
    _, errors = apply_simple_settings(Config(), form(away_lock_minutes="0"))
    assert errors and errors[0].startswith("Away mode:")


def test_update_config_file_keeps_notes_and_unknown_keys(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"_note": "mine", "hotkey": "ctrl+alt+shift+l", "future_option": 1}), encoding="utf-8")
    update_config_file(path, {"hotkey": "ctrl+alt+shift+k"})
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved == {"_note": "mine", "hotkey": "ctrl+alt+shift+k", "future_option": 1}
    fresh = tmp_path / "new" / "config.json"
    update_config_file(fresh, {"sound": False})
    assert json.loads(fresh.read_text(encoding="utf-8"))["sound"] is False
