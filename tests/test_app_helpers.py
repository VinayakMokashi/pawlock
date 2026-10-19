"""Small app helpers that don't need a running app."""

import sys
import threading
import time
import types

from pawlock import paths
from pawlock.app import _ask_running_instance_to_show
from pawlock.feedback.tray import show_tray_icon_next_to_clock


def test_second_start_asks_the_running_copy_to_show_its_window():
    request = paths.show_request_path()

    def running_pawlock():  # what the controller thread does
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if request.exists():
                request.unlink()
                return
            time.sleep(0.02)

    helper = threading.Thread(target=running_pawlock)
    helper.start()
    assert _ask_running_instance_to_show(timeout=2) is True
    helper.join()


def test_second_start_falls_back_when_nobody_answers():
    assert _ask_running_instance_to_show(timeout=0.2) is False
    assert not paths.show_request_path().exists()  # no stale note left behind


class FakeRegistry:
    """Just enough of winreg for NotifyIconSettings."""

    HKEY_CURRENT_USER = "HKCU"
    KEY_READ, KEY_SET_VALUE, REG_DWORD = 1, 2, 4

    def __init__(self, entries):
        self.entries = entries  # name -> dict of values

    class _Key:
        def __init__(self, values=None):
            self.values = values

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def OpenKey(self, parent, name, *args):  # noqa: N802
        if parent == self.HKEY_CURRENT_USER:
            return self._Key()
        return self._Key(self.entries[name])

    def EnumKey(self, key, index):  # noqa: N802
        names = list(self.entries)
        if index >= len(names):
            raise OSError("no more keys")
        return names[index]

    def QueryValueEx(self, key, name):  # noqa: N802
        if name not in key.values:
            raise OSError(name)
        return key.values[name], 1

    def SetValueEx(self, key, name, _reserved, _type, value):  # noqa: N802
        key.values[name] = value


def test_tray_icon_is_moved_next_to_the_clock(monkeypatch):
    registry = FakeRegistry({
        "1": {"ExecutablePath": r"{F38BF404-1D43-42F2-9305-67DE0B28FC23}\explorer.exe"},
        "2": {"ExecutablePath": r"{5CD7AEE2-2219-4A67-B85D-6C9CE15660CB}\PawLock\PawLock.exe"},
    })
    monkeypatch.setitem(sys.modules, "winreg", types.SimpleNamespace(**{
        name: getattr(registry, name) for name in
        ("HKEY_CURRENT_USER", "KEY_READ", "KEY_SET_VALUE", "REG_DWORD", "OpenKey", "EnumKey", "QueryValueEx",
         "SetValueEx")
    }))
    exe = r"C:\Users\cat\AppData\Local\Programs\PawLock\PawLock.exe"
    assert show_tray_icon_next_to_clock(exe, attempts=1, delay=0) is True
    assert registry.entries["2"]["IsPromoted"] == 1
    assert "IsPromoted" not in registry.entries["1"]
    assert show_tray_icon_next_to_clock(r"C:\Other\App.exe", attempts=1, delay=0) is False
