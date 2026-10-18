"""Short audio cues so you can *hear* the lock state change.

* **lock:** three falling tones ("shutting the door")
* **unlock:** three rising tones ("welcome back")
* **cat:** a quick chirp, then the lock tones (the detector fired)

Sounds play on a short-lived background thread so they never delay input
handling. Every failure is swallowed: no speakers is not an error.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
import threading
from pathlib import Path

log = logging.getLogger(__name__)

# (frequency Hz, duration ms) sequences for Windows' winsound.Beep.
_BEEPS = {
    "lock": [(880, 90), (660, 90), (440, 160)],
    "unlock": [(440, 90), (660, 90), (880, 160)],
    "cat": [(1175, 60), (1568, 60), (880, 90), (660, 90), (440, 160)],
}

# System sounds that ship with macOS.
_MAC_SOUNDS = {
    "lock": "/System/Library/Sounds/Funk.aiff",
    "unlock": "/System/Library/Sounds/Glass.aiff",
    "cat": "/System/Library/Sounds/Sosumi.aiff",
}

# freedesktop sound theme (present on most Linux desktops).
_LINUX_SOUNDS = {
    "lock": "device-removed",
    "unlock": "device-added",
    "cat": "dialog-warning",
}
_FREEDESKTOP_DIR = Path("/usr/share/sounds/freedesktop/stereo")


class SoundPlayer:
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled

    def play(self, cue: str) -> None:
        if not self.enabled or cue not in _BEEPS:
            return
        threading.Thread(target=self._play, args=(cue,), name="sound", daemon=True).start()

    @staticmethod
    def _play(cue: str) -> None:
        try:
            if sys.platform == "win32":
                import winsound

                for frequency, duration in _BEEPS[cue]:
                    winsound.Beep(frequency, duration)
            elif sys.platform == "darwin":
                subprocess.run(["afplay", _MAC_SOUNDS[cue]], timeout=5, check=False)  # noqa: S603, S607
            else:
                _play_linux(cue)
        except Exception as exc:  # pragma: no cover - depends on hardware
            log.debug("Could not play sound %r: %s", cue, exc)


def _play_linux(cue: str) -> None:  # pragma: no cover - depends on desktop
    name = _LINUX_SOUNDS[cue]
    sound_file = _FREEDESKTOP_DIR / f"{name}.oga"
    if sound_file.exists():
        for player in ("paplay", "pw-play"):
            if shutil.which(player):
                subprocess.run([player, str(sound_file)], timeout=5, check=False)  # noqa: S603
                return
    if shutil.which("canberra-gtk-play"):
        subprocess.run(["canberra-gtk-play", "-i", name], timeout=5, check=False)  # noqa: S603, S607
        return
    if sys.stdout is not None:
        sys.stdout.write("\a")
        sys.stdout.flush()
