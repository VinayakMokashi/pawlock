"""Start-at-login, tested against a temporary home folder and a fake registry."""

import plistlib
import sys
import types
from pathlib import Path

import pytest

from pawlock import autostart


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    return tmp_path


def test_launch_command_from_source():
    command = autostart.launch_command()
    assert command[-2:] == ["-m", "pawlock"]


def test_linux_desktop_entry(fake_home, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert not autostart.is_enabled()
    autostart.set_enabled(True)
    desktop = fake_home / ".config" / "autostart" / "pawlock.desktop"
    text = desktop.read_text(encoding="utf-8")
    assert "Name=PawLock" in text and "Exec=" in text and "-m pawlock" in text
    assert autostart.is_enabled()
    autostart.set_enabled(False)
    assert not desktop.exists() and not autostart.is_enabled()


def test_macos_launch_agent(fake_home, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    autostart.set_enabled(True)
    plist = fake_home / "Library" / "LaunchAgents" / "io.github.pawlock.plist"
    data = plistlib.loads(plist.read_bytes())
    assert data["RunAtLoad"] is True
    assert data["ProgramArguments"][-2:] == ["-m", "pawlock"]
    assert autostart.is_enabled()
    autostart.set_enabled(False)
    assert not plist.exists()


def test_windows_run_key(monkeypatch):
    store = {}

    class Key:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def query(_key, name):
        if name not in store:
            raise FileNotFoundError(name)
        return store[name], 1

    def delete(_key, name):
        if name not in store:
            raise FileNotFoundError(name)
        del store[name]

    fake = types.SimpleNamespace(
        HKEY_CURRENT_USER=object(), KEY_SET_VALUE=2, REG_SZ=1,
        OpenKey=lambda *a, **k: Key(), CreateKeyEx=lambda *a, **k: Key(),
        QueryValueEx=query, DeleteValue=delete,
        SetValueEx=lambda _key, name, _r, _t, value: store.__setitem__(name, value),
    )
    monkeypatch.setitem(sys.modules, "winreg", fake)
    monkeypatch.setattr(sys, "platform", "win32")

    assert not autostart.is_enabled()
    autostart.set_enabled(True)
    assert autostart.is_enabled()
    assert "-m pawlock" in store["PawLock"]
    autostart.set_enabled(False)
    assert store == {}
    autostart.set_enabled(False)  # already off: no error
