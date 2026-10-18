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
