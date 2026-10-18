"""A small always-on-top banner that says "Locked" while input is blocked.

Tk is not thread-safe, so the banner lives on the thread that owns the Tk
root (the main thread) and everyone else talks to it through a queue that
is polled every 100 ms.

On Windows the banner is made *click-through* and *non-activating* with a
few extended window styles. It can never steal keyboard focus from the app
you were using, and it doesn't get in the way of your mouse after you
unlock. It is shown and hidden by changing its opacity rather than mapping
and unmapping the window, which could otherwise activate it.
"""

from __future__ import annotations

import logging
import queue
import sys
from typing import Any, Callable, Optional, Tuple

from .icons import paw_glyph

log = logging.getLogger(__name__)

#: Banner size at 96 DPI (scaled up on high-DPI screens).
WIDTH, HEIGHT = 520, 100
OPACITY = 0.97

_BACKGROUND = "#161B22"
_TEXT = "#F0F6FC"
_SUBTEXT = "#9DA7B3"
_ACCENTS = {"locked": "#CF222E", "unlocked": "#2DA44E", "dry_run": "#BF8700"}


def _hex_to_rgb(colour: str) -> Tuple[int, int, int]:
    return tuple(int(colour[i : i + 2], 16) for i in (1, 3, 5))  # type: ignore[return-value]


class Overlay:
    def __init__(self, root: Any, position: str = "top", on_quit: Optional[Callable[[], None]] = None) -> None:
        import tkinter as tk
        from tkinter import font as tkfont

        from PIL import ImageTk

        self._tk = tk
        self._image_tk = ImageTk
        self._root = root
        self._position = position
        self._on_quit = on_quit
        self._queue: queue.Queue[tuple] = queue.Queue()
        self._visible = False
        self._hide_job: Optional[str] = None
        self._use_alpha = sys.platform == "win32"
        self._paw_images = {}

        # Fonts are sized in points and grow on high-DPI screens, so every
        # pixel measurement is scaled the same way (1.0 at 96 DPI).
        self._scale = max(1.0, root.winfo_fpixels("1i") / 96.0)
        self._w, self._h = self._px(WIDTH), self._px(HEIGHT)

        family = {"win32": "Segoe UI", "darwin": "Helvetica Neue"}.get(sys.platform, "DejaVu Sans")
        self._title_font = tkfont.Font(root=root, family=family, size=14, weight="bold")
        self._body_font = tkfont.Font(root=root, family=family, size=10)

        win = tk.Toplevel(root)
        win.withdraw()
        win.overrideredirect(True)  # No title bar, no taskbar button.
        win.configure(bg=_BACKGROUND)
        win.attributes("-topmost", True)
        win.geometry(self._geometry())
        self._win = win

        px = self._px
        canvas = tk.Canvas(win, width=self._w, height=self._h, bg=_BACKGROUND, highlightthickness=0, bd=0)
        canvas.pack(fill="both", expand=True)
        self._canvas = canvas
        self._accent = canvas.create_rectangle(0, 0, px(6), self._h, fill=_ACCENTS["locked"], width=0)
        self._paw = canvas.create_image(px(46), self._h // 2)
        self._title = canvas.create_text(px(86), px(16), anchor="nw", fill=_TEXT, font=self._title_font, text="")
        self._body = canvas.create_text(
            px(86), px(44), anchor="nw", fill=_SUBTEXT, font=self._body_font, text="", width=self._w - px(100)
        )

        if self._use_alpha:
            # Map the window once, fully transparent, then make it
            # click-through + non-activating. From now on we only change opacity.
            win.attributes("-alpha", 0.0)
            win.deiconify()
            win.update_idletasks()
            _make_click_through(win)

        root.after(100, self._poll)

    # -- thread-safe API ------------------------------------------------------

    def show_locked(self, title: str, body: str, style: str = "locked") -> None:
        self._queue.put(("show", title, body, style, 0))

    def flash(self, title: str, body: str, style: str = "unlocked", millis: int = 1600) -> None:
        self._queue.put(("show", title, body, style, millis))

    def hide(self) -> None:
        self._queue.put(("hide",))

    def close(self) -> None:
        self._queue.put(("quit",))

    # -- Tk thread ------------------------------------------------------------

    def _px(self, value: float) -> int:
        return int(round(value * self._scale))

    def _geometry(self) -> str:
        x = max(0, (self._root.winfo_screenwidth() - self._w) // 2)
        screen_h = self._root.winfo_screenheight()
        if self._position == "bottom":
            y = max(0, screen_h - self._h - self._px(90))
        elif self._position == "center":
            y = max(0, (screen_h - self._h) // 2)
        else:
            y = self._px(28)
        return f"{self._w}x{self._h}+{x}+{y}"

    def _poll(self) -> None:
        try:
            while True:
                command = self._queue.get_nowait()
                if command[0] == "quit":
                    self._root.quit()
                    return
                if command[0] == "hide":
                    self._set_visible(False)
                elif command[0] == "show":
                    self._render(*command[1:])
        except queue.Empty:
            pass
        except Exception:
            log.exception("Overlay error")
        if self._visible:
            # Other "always on top" windows can cover us; reassert.
            try:
                self._win.attributes("-topmost", True)
            except Exception:
                pass
        self._root.after(100, self._poll)

    def _render(self, title: str, body: str, style: str, millis: int) -> None:
        accent = _ACCENTS.get(style, _ACCENTS["locked"])
        if style not in self._paw_images:
            glyph = paw_glyph(self._px(48), _hex_to_rgb(accent))
            self._paw_images[style] = self._image_tk.PhotoImage(glyph, master=self._root)
        self._canvas.itemconfigure(self._accent, fill=accent)
        self._canvas.itemconfigure(self._paw, image=self._paw_images[style])
        self._canvas.itemconfigure(self._title, text=title)
        self._canvas.itemconfigure(self._body, text=body)
        self._set_visible(True)
        if self._hide_job is not None:
            self._root.after_cancel(self._hide_job)
            self._hide_job = None
        if millis:
            self._hide_job = self._root.after(millis, lambda: self._set_visible(False))

    def _set_visible(self, visible: bool) -> None:
        self._visible = visible
        if self._use_alpha:
            self._win.attributes("-alpha", OPACITY if visible else 0.0)
        elif visible:
            self._win.geometry(self._geometry())
            self._win.deiconify()
            self._win.attributes("-topmost", True)
        else:
            self._win.withdraw()


def _make_click_through(win: Any) -> None:
    """Windows only: let clicks fall through the banner and never focus it."""
    try:
        import ctypes

        GWL_EXSTYLE = -20
        WS_EX_LAYERED = 0x00080000
        WS_EX_TRANSPARENT = 0x00000020
        WS_EX_TOOLWINDOW = 0x00000080
        WS_EX_NOACTIVATE = 0x08000000
        user32 = ctypes.windll.user32
        hwnd = user32.GetParent(win.winfo_id()) or win.winfo_id()
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(
            hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
        )
    except Exception:  # pragma: no cover - Windows only
        log.debug("Could not make the overlay click-through", exc_info=True)
