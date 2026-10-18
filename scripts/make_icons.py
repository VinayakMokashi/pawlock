"""Regenerate the application icons in assets/ from the code that draws them.

    python scripts/make_icons.py

Writes:
    assets/pawlock.ico   multi-size Windows icon (16-256 px), used by PyInstaller
    assets/pawlock.png   512 px icon, used for macOS/Linux builds and the README
    docs/images/tray-states.png   the four tray-icon colours, for the docs
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from pawlock.feedback.icons import STATE_COLOURS, tray_icon, write_app_icons  # noqa: E402

LABELS = {
    "watching": "Watching",
    "paused": "Detection off",
    "locked": "Locked",
    "dry_run": "Dry run",
}


def tray_states_strip(path: Path) -> None:
    """A labelled strip showing every tray-icon state."""
    icon, pad, label_h = 96, 28, 34
    width = len(STATE_COLOURS) * (icon + pad) + pad
    strip = Image.new("RGBA", (width, icon + label_h + 2 * pad), (255, 255, 255, 0))
    draw = ImageDraw.Draw(strip)
    try:
        font = ImageFont.truetype("segoeui.ttf" if sys.platform == "win32" else "DejaVuSans.ttf", 18)
    except OSError:
        font = ImageFont.load_default()
    for i, state in enumerate(STATE_COLOURS):
        x = pad + i * (icon + pad)
        strip.alpha_composite(tray_icon(state, icon), (x, pad))
        text = LABELS[state]
        text_w = draw.textlength(text, font=font)
        draw.text((x + (icon - text_w) / 2, pad + icon + 8), text, fill=(87, 96, 106, 255), font=font)
    path.parent.mkdir(parents=True, exist_ok=True)
    strip.save(path)


def main() -> None:
    ico, png = write_app_icons(ROOT / "assets")
    strip = ROOT / "docs" / "images" / "tray-states.png"
    tray_states_strip(strip)
    for path in (ico, png, strip):
        print(f"wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
