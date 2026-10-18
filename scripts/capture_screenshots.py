"""Capture the on-screen banner in each of its states, for the docs.

    python scripts/capture_screenshots.py

Only draws the banner: no input hooks are installed and nothing is blocked.
Works on Windows and macOS (Pillow's ImageGrab). Images go to docs/images/.
"""

from __future__ import annotations

import sys
import time
import tkinter as tk
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import ImageGrab  # noqa: E402

from pawlock.app import _enable_dpi_awareness  # noqa: E402
from pawlock.engine import REASON_AUTO, REASON_AWAY, REASON_HOTKEY, StateChange  # noqa: E402
from pawlock.feedback import describe, overlay  # noqa: E402
from pawlock.hotkey import Hotkey  # noqa: E402

overlay.OPACITY = 1.0  # No see-through background in the screenshots.
HOTKEY = Hotkey.parse("ctrl+alt+shift+l").display()

SHOTS = {
    "banner-cat-detected": (
        describe(StateChange(True, REASON_AUTO, "7 keys pressed at once across 3 keyboard rows"), HOTKEY, "unlock"),
        "locked",
    ),
    "banner-locked": (describe(StateChange(True, REASON_HOTKEY), HOTKEY, "unlock"), "locked"),
    "banner-unlocked": (describe(StateChange(False, REASON_HOTKEY), HOTKEY, "unlock"), "unlocked"),
    "banner-away": (
        describe(StateChange(True, REASON_AWAY, "no keyboard or mouse activity for 10 minutes"), HOTKEY, "unlock"),
        "locked",
    ),
    "banner-welcome-back": (
        describe(StateChange(False, REASON_HOTKEY,
                             summary="Blocked 214 key presses, 37 clicks and some scrolling while locked."),
                 HOTKEY, "unlock"),
        "unlocked",
    ),
    "banner-dry-run": (
        describe(StateChange(True, REASON_AUTO, "5 keys pressed at once across 2 keyboard rows", dry_run=True),
                 HOTKEY, "unlock"),
        "dry_run",
    ),
}


def main() -> None:
    _enable_dpi_awareness()
    root = tk.Tk()
    root.withdraw()
    banner = overlay.Overlay(root, "top")
    out = ROOT / "docs" / "images"
    out.mkdir(parents=True, exist_ok=True)

    def pump(seconds: float) -> None:
        end = time.time() + seconds
        while time.time() < end:
            root.update()
            time.sleep(0.02)

    for name, ((title, body), style) in SHOTS.items():
        banner.show_locked(title, body, style)
        pump(0.6)
        size, x, y = banner._geometry().split("+")
        w, h = (int(v) for v in size.split("x"))
        x, y = int(x), int(y)
        ImageGrab.grab(bbox=(x, y, x + w, y + h)).save(out / f"{name}.png")
        print(f"wrote docs/images/{name}.png")
    banner.hide()
    pump(0.2)
    root.destroy()


if __name__ == "__main__":
    main()
