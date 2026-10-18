"""Backend glue, tested with fake OS events (no hooks are installed)."""

from types import SimpleNamespace

import pytest

from pawlock.backends import macos, windows
from pawlock.backends.macos import MacBackend
from pawlock.backends.windows import WindowsBackend

from .conftest import quiet_detector


class Suppressed(Exception):
    """Raised by the fake listener, like pynput's SuppressException."""


class FakeListener:
    def suppress_event(self):
        raise Suppressed


def kbd(vk, flags=0):
    return SimpleNamespace(vkCode=vk, flags=flags)


def mouse(flags=0, mouse_data=0):
    return SimpleNamespace(flags=flags, mouseData=mouse_data)


@pytest.fixture
def win(make_engine):
    backend = WindowsBackend(make_engine())
    backend._keyboard = FakeListener()
    backend._mouse = FakeListener()
    return backend


class TestWindowsFilters:
    def test_unlocked_events_pass(self, win):
        assert win.keyboard_filter(windows.WM_KEYDOWN, kbd(0x41)) is False
        assert win.mouse_filter(windows.WM_MOUSEMOVE, mouse()) is False

    def test_hotkey_toggles_and_locked_events_are_suppressed(self, win):
        for vk in (0xA2, 0xA4, 0xA0):  # LCtrl, LAlt (as a SYSKEY), LShift
            msg = windows.WM_SYSKEYDOWN if vk == 0xA4 else windows.WM_KEYDOWN
            assert win.keyboard_filter(msg, kbd(vk)) is False
        with pytest.raises(Suppressed):
            win.keyboard_filter(windows.WM_SYSKEYDOWN, kbd(0x4C))  # L completes the hotkey
        assert win.engine.locked
        with pytest.raises(Suppressed):
            win.keyboard_filter(windows.WM_KEYDOWN, kbd(0x41))
        with pytest.raises(Suppressed):
            win.mouse_filter(windows.WM_MOUSEMOVE, mouse())
        with pytest.raises(Suppressed):
            win.mouse_filter(windows.WM_MOUSEWHEEL, mouse())
        with pytest.raises(Suppressed):
            win.mouse_filter(windows.WM_LBUTTONDOWN, mouse())

    def test_injected_input_is_never_touched(self, win):
        win.engine.lock()
        assert win.keyboard_filter(windows.WM_KEYDOWN, kbd(0x41, flags=windows.LLKHF_INJECTED)) is False
        assert win.mouse_filter(windows.WM_MOUSEMOVE, mouse(flags=windows.LLMHF_INJECTED)) is False

    def test_x_buttons(self, win):
        win.engine.lock()
        with pytest.raises(Suppressed):
            win.mouse_filter(windows.WM_XBUTTONDOWN, mouse(mouse_data=2 << 16))
        assert "x2" in win.engine._button_delivered

    def test_auto_lock_from_hook(self, make_engine):
        backend = WindowsBackend(make_engine(detector=quiet_detector(chord_keys=3, chord_min_rows=1)))
        backend._keyboard = FakeListener()
        assert backend.keyboard_filter(windows.WM_KEYDOWN, kbd(0x5A)) is False  # Z
        assert backend.keyboard_filter(windows.WM_KEYDOWN, kbd(0x58)) is False  # X
        with pytest.raises(Suppressed):
            backend.keyboard_filter(windows.WM_KEYDOWN, kbd(0x43))  # C -> cat!
        # Releases of keys that got through are delivered (no stuck keys).
        assert backend.keyboard_filter(windows.WM_KEYUP, kbd(0x5A)) is False


class FakeQuartz:
    """Just enough of pyobjc's Quartz for the intercepts."""

    kCGKeyboardEventKeycode = 9
    kCGEventSourceUnixProcessID = 41

    @staticmethod
    def CGEventGetIntegerValueField(event, field):  # noqa: N802
        return event.get(field, 0)

    @staticmethod
    def CGEventGetFlags(event):  # noqa: N802
        return event.get("flags", 0)


def mac_key(code, flags=0, pid=0):
    return {9: code, 41: pid, "flags": flags}


@pytest.fixture
def mac(make_engine):
    return MacBackend(make_engine(), quartz=FakeQuartz())


class TestMacIntercepts:
    CTRL, ALT, SHIFT = 0x40000, 0x80000, 0x20000

    def press_hotkey(self, mac):
        flags = 0
        results = []
        for code, mask in ((0x3B, self.CTRL), (0x3A, self.ALT), (0x38, self.SHIFT)):
            flags |= mask
            results.append(mac.keyboard_intercept(macos.FLAGS_CHANGED, mac_key(code, flags)))
        results.append(mac.keyboard_intercept(macos.KEY_DOWN, mac_key(0x25, flags)))  # L
        return results

    def test_hotkey_via_flags_changed(self, mac):
        results = self.press_hotkey(mac)
        assert all(r is not None for r in results[:3])  # modifiers pass
        assert results[3] is None                       # L swallowed
        assert mac.engine.locked
        event = mac_key(0x00)
        assert mac.keyboard_intercept(macos.KEY_DOWN, event) is None
        assert mac.mouse_intercept(5, {}) is None  # mouse moved

    def test_modifier_release_is_detected(self, mac):
        mac.keyboard_intercept(macos.FLAGS_CHANGED, mac_key(0x3B, self.CTRL))
        assert mac.engine.is_held("ctrl_l")
        mac.keyboard_intercept(macos.FLAGS_CHANGED, mac_key(0x3B, 0))
        assert not mac.engine.is_held("ctrl_l")

    def test_injected_events_pass(self, mac):
        mac.engine.lock()
        event = mac_key(0x00, pid=1234)
        assert mac.keyboard_intercept(macos.KEY_DOWN, event) is event

    def test_media_keys_follow_the_lock(self, mac):
        event = {}
        assert mac.keyboard_intercept(14, event) is event  # NSSystemDefined while unlocked
        mac.engine.lock()
        assert mac.keyboard_intercept(14, event) is None

    def test_tap_timeout_marks_backend_unhealthy(self, mac):
        event = {}
        assert mac.keyboard_intercept(macos.TAP_DISABLED_BY_TIMEOUT, event) is event
        assert mac.is_healthy() is False

    def test_mouse_buttons_are_balanced(self, mac):
        down = mac.mouse_intercept(macos.LEFT_MOUSE_DOWN, {})
        assert down is not None
        mac.engine.lock()
        up = {}
        assert mac.mouse_intercept(macos.LEFT_MOUSE_UP, up) is up
