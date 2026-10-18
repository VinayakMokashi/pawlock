"""Paw-print icons, drawn in code with Pillow.

Drawing the icons at runtime means there are no image files to lose when
packaging, and the tray icon can change colour with the lock state. The
same drawing is used by ``scripts/make_icons.py`` to produce the
``.ico``/``.png`` files PyInstaller embeds in the executable.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Tuple

from PIL import Image, ImageDraw

RGB = Tuple[int, int, int]

#: Tray colours per state.
STATE_COLOURS: Dict[str, RGB] = {
    "watching": (31, 136, 61),    # green: unlocked, cat detector on
    "paused": (101, 109, 118),    # grey: unlocked, cat detector off
    "locked": (207, 34, 46),      # red: keyboard & mouse blocked
    "dry_run": (191, 135, 0),     # amber: dry run, "would be locked"
}

_SUPERSAMPLE = 4  # Draw big, then shrink: cheap anti-aliasing.


def _draw_paw(draw: ImageDraw.ImageDraw, size: int, fill, inset: float = 0.0) -> None:
    """Draw a paw print (four toe beans + a main pad) inside a size x size box."""
    s = size * (1 - 2 * inset)
    o = size * inset

    def oval(cx: float, cy: float, rx: float, ry: float) -> None:
        draw.ellipse((o + (cx - rx) * s, o + (cy - ry) * s, o + (cx + rx) * s, o + (cy + ry) * s), fill=fill)

    # Main pad: three overlapping ovals make the soft triangular shape.
    oval(0.50, 0.66, 0.19, 0.15)
    oval(0.38, 0.73, 0.11, 0.09)
    oval(0.62, 0.73, 0.11, 0.09)
    # Toe beans, in an arc.
    oval(0.24, 0.43, 0.075, 0.095)
    oval(0.39, 0.29, 0.075, 0.10)
    oval(0.61, 0.29, 0.075, 0.10)
    oval(0.76, 0.43, 0.075, 0.095)


def tray_icon(state: str = "watching", size: int = 64) -> Image.Image:
    """A white paw on a coloured disc, used for the system tray."""
    big = size * _SUPERSAMPLE
    image = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((0, 0, big - 1, big - 1), fill=STATE_COLOURS.get(state, STATE_COLOURS["watching"]) + (255,))
    _draw_paw(draw, big, (255, 255, 255, 255), inset=0.08)
    return image.resize((size, size), Image.LANCZOS)


def paw_glyph(size: int, colour: RGB) -> Image.Image:
    """Just the paw, on a transparent background (used by the on-screen banner)."""
    big = size * _SUPERSAMPLE
    image = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    _draw_paw(ImageDraw.Draw(image), big, colour + (255,))
    return image.resize((size, size), Image.LANCZOS)


def write_app_icons(directory: Path) -> Tuple[Path, Path]:
    """Write ``pawlock.ico`` (Windows) and ``pawlock.png`` (macOS/Linux)."""
    directory.mkdir(parents=True, exist_ok=True)
    master = tray_icon("watching", 512)
    png = directory / "pawlock.png"
    ico = directory / "pawlock.ico"
    master.save(png)
    master.save(ico, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    return ico, png
