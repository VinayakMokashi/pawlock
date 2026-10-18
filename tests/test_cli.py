import json

import pytest

from pawlock import __version__, paths
from pawlock.cli import build_parser, main


def test_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_where(capsys, isolated_home):
    assert main(["--where"]) == 0
    out = capsys.readouterr().out
    assert str(isolated_home) in out


def test_status_and_stop_when_not_running(capsys):
    assert main(["--status"]) == 1
    assert "not running" in capsys.readouterr().out
    assert main(["--stop"]) == 0
    assert "not running" in capsys.readouterr().out


def test_reset_config_keeps_a_backup(capsys):
    path = paths.config_path()
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"hotkey": "ctrl+alt+k"}), encoding="utf-8")
    assert main(["--reset-config"]) == 0
    assert json.loads(path.read_text(encoding="utf-8"))["hotkey"] == "ctrl+alt+shift+l"
    backups = list(path.parent.glob("config.json.*.bak"))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text(encoding="utf-8"))["hotkey"] == "ctrl+alt+k"


def test_parser_options():
    args = build_parser().parse_args(["--practice", "--dry-run", "--sensitivity", "low", "--log-level", "debug"])
    assert args.practice == 30.0
    assert args.dry_run and args.sensitivity == "low" and args.log_level == "DEBUG"
    assert build_parser().parse_args(["--practice", "12"]).practice == 12.0
