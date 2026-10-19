"""The PawLock window: a plain-English "how to use" page and simple settings.

This is what non-technical users see. It opens by itself the first time
PawLock runs, when the tray paw is clicked, and when PawLock is started
again while it's already running. Closing it only hides it: PawLock keeps
protecting the computer from the tray.

Everything here runs on the Tk (main) thread. Other threads ask the app to
open it via ``PawLockApp.open_window``.
"""

from __future__ import annotations

import logging
import string
import sys
import webbrowser
from typing import Any, Dict, Optional

from .icons import tray_icon

log = logging.getLogger(__name__)

HELP_URL = "https://github.com/VinayakMokashi/pawlock#readme"

BG = "#FFFFFF"
TEXT = "#1F2328"
MUTED = "#59636E"
GREEN = "#1A7F37"
RED = "#CF222E"
GREY = "#6E7781"
AMBER = "#9A6700"
KEY_BG = "#F6F8FA"
KEY_BORDER = "#D0D7DE"

#: Text width of one column (pixels at 96 DPI; Tk scales fonts, we scale this).
COLUMN_WIDTH = 330

SENSITIVITY_CHOICES = (
    ("low", "Relaxed: fewer false alarms (good for gamers)"),
    ("medium", "Balanced (recommended)"),
    ("high", "Strict: catches cats sooner"),
)


def _platform_tips() -> Dict[str, str]:
    if sys.platform == "darwin":
        return {
            "find": "Look for the paw in the menu bar at the top of the screen.",
            "emergency": "Press Control + Option + Shift + L, or type the unlock word. "
                         "If you set a time limit, PawLock also unlocks by itself.",
        }
    if sys.platform == "win32":
        return {
            "find": "Look for the paw next to the clock (bottom-right). If you can't see it, click the "
                    "small ^ arrow. Click the paw to open this window; right-click it for more options.",
            "emergency": "Press Ctrl + Alt + Delete, choose Task Manager, select PawLock and click "
                         "End task. Your keyboard and mouse come back straight away.",
        }
    return {
        "find": "Look for the paw in your desktop's tray or panel. Click it to open this window.",
        "emergency": "Press Ctrl + Alt + F3, log in, run: pkill -f -i pawlock, then press Ctrl + Alt + F2 "
                     "(or F1/F7) to return.",
    }


class MainWindow:
    """One window with two tabs: "How to use" and "Settings"."""

    def __init__(self, root: Any, app: Any) -> None:
        import tkinter as tk
        from tkinter import font as tkfont
        from tkinter import ttk

        from PIL import ImageTk

        self.tk, self.ttk = tk, ttk
        self.root = root
        self.app = app
        self.vars: Dict[str, Any] = {}

        win = tk.Toplevel(root)
        win.withdraw()
        win.title("PawLock")
        win.configure(bg=BG)
        win.protocol("WM_DELETE_WINDOW", self.hide)
        self.win = win
        self._window_icon = ImageTk.PhotoImage(tray_icon("watching", 64), master=root)
        self._header_icon = ImageTk.PhotoImage(tray_icon("watching", 52), master=root)
        win.iconphoto(False, self._window_icon)

        # Fonts grow on high-DPI screens; text-wrap widths (pixels) must too.
        self.wrap = int(COLUMN_WIDTH * max(1.0, root.winfo_fpixels("1i") / 96.0))

        family = {"win32": "Segoe UI", "darwin": "Helvetica Neue"}.get(sys.platform, "DejaVu Sans")
        self.f_title = tkfont.Font(root=root, family=family, size=18, weight="bold")
        self.f_heading = tkfont.Font(root=root, family=family, size=11, weight="bold")
        self.f_body = tkfont.Font(root=root, family=family, size=10)
        self.f_small = tkfont.Font(root=root, family=family, size=9)
        self.f_key = tkfont.Font(root=root, family=family, size=11, weight="bold")

        style = ttk.Style(win)
        if sys.platform == "win32" and "vista" in style.theme_names():
            style.theme_use("vista")
        for name in ("TFrame", "TLabel", "TCheckbutton", "TRadiobutton", "TNotebook"):
            style.configure(name, background=BG)
        style.configure("TCheckbutton", font=self.f_body)
        style.configure("TRadiobutton", font=self.f_body)
        style.configure("TNotebook.Tab", font=self.f_body, padding=(14, 6))
        style.configure("Big.TButton", font=self.f_body, padding=(12, 6))

        self._build_header()
        notebook = ttk.Notebook(win)
        notebook.pack(fill="both", expand=True, padx=16, pady=(4, 0))
        self.notebook = notebook
        self.howto_tab = tk.Frame(notebook, bg=BG)
        self.settings_tab = tk.Frame(notebook, bg=BG)
        notebook.add(self.howto_tab, text="How to use")
        notebook.add(self.settings_tab, text="Settings")
        self._build_howto()
        self._build_settings()
        self._build_footer()
        win.after(500, self._tick)

    # ------------------------------------------------------------------
    # Showing / hiding
    # ------------------------------------------------------------------

    def show(self, tab: str = "howto", welcome: bool = False) -> None:
        self.welcome_label.configure(
            text=("Welcome! PawLock is now protecting your computer from curious paws. "
                  "Here's everything you need to know. Press “Try it” to practise safely.") if welcome else ""
        )
        if not welcome:
            self.welcome_label.pack_forget()
        else:
            self.welcome_label.pack(fill="x", padx=20, pady=(0, 4), before=self.notebook)
        self.load_settings()
        self.notebook.select(self.settings_tab if tab == "settings" else self.howto_tab)
        self._refresh()
        win = self.win
        win.deiconify()
        win.update_idletasks()
        self._center()
        # Bring to the front even if another app has focus.
        win.lift()
        win.attributes("-topmost", True)
        win.after(300, lambda: win.attributes("-topmost", False))
        win.focus_force()

    def hide(self) -> None:
        self.win.withdraw()

    def _center(self) -> None:
        win = self.win
        w, h = win.winfo_reqwidth(), win.winfo_reqheight()
        x = max(0, (win.winfo_screenwidth() - w) // 2)
        # Keep clear of the taskbar: centre in the screen minus ~60 px at the bottom.
        y = max(0, (win.winfo_screenheight() - 60 - h) // 2)
        win.geometry(f"+{x}+{y}")

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _label(self, parent: Any, text: str = "", font: Any = None, fg: str = TEXT, **kw: Any) -> Any:
        return self.tk.Label(parent, text=text, font=font or self.f_body, fg=fg, bg=BG, justify="left",
                             anchor="w", **kw)

    def _build_header(self) -> None:
        tk, ttk = self.tk, self.ttk
        header = tk.Frame(self.win, bg=BG)
        header.pack(fill="x", padx=20, pady=(14, 6))
        tk.Label(header, image=self._header_icon, bg=BG).pack(side="left")
        text = tk.Frame(header, bg=BG)
        text.pack(side="left", padx=12)
        self._label(text, "PawLock", self.f_title).pack(anchor="w")
        self.status_label = self._label(text, "", self.f_body)
        self.status_label.pack(anchor="w")
        # The two things people want most, always visible.
        ttk.Button(header, text="Lock now", style="Big.TButton", command=self._lock_now).pack(side="right")
        ttk.Button(header, text="Try it (30-second practice)", style="Big.TButton",
                   command=self._practice).pack(side="right", padx=(0, 8))
        self.welcome_label = self._label(self.win, "", self.f_body, wraplength=self.wrap * 2)

    def _card(self, parent: Any, row: int, column: int, title: str) -> Any:
        """A heading plus text, placed in a two-column grid."""
        frame = self.tk.Frame(parent, bg=BG)
        frame.grid(row=row, column=column, sticky="nw", padx=(18, 10), pady=(12, 0))
        self._label(frame, title, self.f_heading).pack(anchor="w")
        return frame

    def _section(self, parent: Any, title: str) -> Any:
        frame = self.tk.Frame(parent, bg=BG)
        frame.pack(fill="x", pady=(10, 0))
        self._label(frame, title, self.f_heading).pack(anchor="w")
        return frame

    def _build_howto(self) -> None:
        tk = self.tk
        tab = self.howto_tab
        tips = _platform_tips()
        wrap = self.wrap

        lock = self._card(tab, 0, 0, "Lock or unlock")
        self.keycaps = tk.Frame(lock, bg=BG)
        self.keycaps.pack(anchor="w", pady=(6, 2))
        self._label(lock, "Hold down the first keys, then press the last one.", fg=MUTED,
                    wraplength=wrap).pack(anchor="w")

        phrase = self._card(tab, 0, 1, "Forgot the shortcut?")
        self.phrase_text = self._label(phrase, "", fg=MUTED, wraplength=wrap)
        self.phrase_text.pack(anchor="w")

        cat = self._card(tab, 1, 0, "Cat on the keyboard?")
        self.cat_text = self._label(cat, "", fg=MUTED, wraplength=wrap)
        self.cat_text.pack(anchor="w")

        away = self._card(tab, 1, 1, "Leaving the room?")
        self.away_text = self._label(away, "", fg=MUTED, wraplength=wrap)
        self.away_text.pack(anchor="w")

        find = self._card(tab, 2, 0, "Where is PawLock?")
        self._label(find, tips["find"], fg=MUTED, wraplength=wrap).pack(anchor="w")

        help_ = self._card(tab, 2, 1, "If something ever goes wrong")
        self._label(help_, tips["emergency"], fg=MUTED, wraplength=wrap).pack(anchor="w")

        tk.Frame(tab, bg=BG, height=14).grid(row=3, column=0)  # bottom padding

    def _build_settings(self) -> None:
        tk, ttk = self.tk, self.ttk
        tab = self.settings_tab
        v = self.vars
        v["letter"] = tk.StringVar()
        v["unlock_phrase"] = tk.StringVar()
        v["auto_detect"] = tk.BooleanVar()
        v["sensitivity"] = tk.StringVar()
        v["away_lock"] = tk.BooleanVar()
        v["away_lock_minutes"] = tk.StringVar()
        v["lock_mouse"] = tk.BooleanVar()
        v["sound"] = tk.BooleanVar()
        v["autostart"] = tk.BooleanVar()

        left = tk.Frame(tab, bg=BG)
        left.grid(row=0, column=0, sticky="nw", padx=(18, 10), pady=(2, 0))
        right = tk.Frame(tab, bg=BG)
        right.grid(row=0, column=1, sticky="nw", padx=(10, 18), pady=(2, 0))

        shortcut = self._section(left, "Lock / unlock shortcut")
        row = tk.Frame(shortcut, bg=BG)
        row.pack(anchor="w", pady=(4, 0))
        self._label(row, self.app.shortcut_prefix() + "  +").pack(side="left")
        ttk.Combobox(row, textvariable=v["letter"], width=4, state="readonly",
                     values=[c.upper() for c in string.ascii_lowercase]).pack(side="left", padx=(6, 0))
        self.custom_hotkey_note = self._label(shortcut, "", self.f_small, fg=AMBER, wraplength=self.wrap)

        phrase = self._section(left, "Unlock word (type it while locked)")
        ttk.Entry(phrase, textvariable=v["unlock_phrase"], width=24, font=self.f_body).pack(anchor="w", pady=(4, 0))
        self._label(phrase, "4-32 letters or numbers. Leave empty to turn it off.", self.f_small,
                    fg=MUTED).pack(anchor="w")

        away = self._section(left, "Away mode")
        ttk.Checkbutton(away, text="Lock when nobody uses the computer", variable=v["away_lock"]).pack(
            anchor="w", pady=(4, 0))
        row = tk.Frame(away, bg=BG)
        row.pack(anchor="w", padx=(22, 0))
        self._label(row, "for").pack(side="left")
        ttk.Spinbox(row, from_=1, to=240, width=5, textvariable=v["away_lock_minutes"], font=self.f_body).pack(
            side="left", padx=6)
        self._label(row, "minutes").pack(side="left")

        cat = self._section(right, "Cat detection")
        ttk.Checkbutton(cat, text="Lock automatically when a cat\nwalks on the keyboard or trackpad",
                        variable=v["auto_detect"]).pack(anchor="w", pady=(4, 2))
        for value, text in SENSITIVITY_CHOICES:
            ttk.Radiobutton(cat, text=text, value=value, variable=v["sensitivity"]).pack(anchor="w", padx=(22, 0))

        other = self._section(right, "More options")
        ttk.Checkbutton(other, text="Also lock the mouse and trackpad",
                        variable=v["lock_mouse"]).pack(anchor="w", pady=(4, 0))
        ttk.Checkbutton(other, text="Play a sound when locking and unlocking", variable=v["sound"]).pack(anchor="w")
        if self.app.autostart_supported():
            ttk.Checkbutton(other, text="Start PawLock automatically when I sign in",
                            variable=v["autostart"]).pack(anchor="w")

        buttons = tk.Frame(tab, bg=BG)
        buttons.grid(row=1, column=0, columnspan=2, sticky="we", padx=18, pady=(16, 14))
        ttk.Button(buttons, text="Save", style="Big.TButton", command=self._save).pack(side="left")
        ttk.Button(buttons, text="Advanced settings file…", command=self._advanced).pack(side="left", padx=(8, 0))
        self.save_message = self._label(buttons, "", self.f_body)
        self.save_message.pack(side="left", padx=(12, 0))

    def _build_footer(self) -> None:
        tk, ttk = self.tk, self.ttk
        footer = tk.Frame(self.win, bg=BG)
        footer.pack(fill="x", padx=16, pady=(8, 14))
        self._label(footer, "Closing this window keeps PawLock running in the background.", self.f_small,
                    fg=MUTED).pack(side="left")
        ttk.Button(footer, text="Close", command=self.hide).pack(side="right")
        ttk.Button(footer, text="Quit PawLock", command=self._quit).pack(side="right", padx=(0, 8))
        ttk.Button(footer, text="Help", command=lambda: webbrowser.open(HELP_URL)).pack(side="right", padx=(0, 8))

    # ------------------------------------------------------------------
    # Live content
    # ------------------------------------------------------------------

    def _tick(self) -> None:
        try:
            if self.win.winfo_viewable():
                self._refresh()
        except Exception:
            log.debug("Window refresh failed", exc_info=True)
        self.win.after(500, self._tick)

    def _refresh(self) -> None:
        app = self.app
        if app.is_locked():
            self.status_label.configure(text="● Locked: keyboard and trackpad are blocked", fg=RED)
        elif app.auto_detect_enabled():
            self.status_label.configure(text="● Protecting your computer", fg=GREEN)
        else:
            self.status_label.configure(text="● Running, cat detection is off", fg=GREY)

        parts = app.hotkey_text().split(" + ")
        if getattr(self, "_shown_keys", None) != parts:
            self._shown_keys = parts
            for child in self.keycaps.winfo_children():
                child.destroy()
            for i, part in enumerate(parts):
                if i:
                    self._label(self.keycaps, " + ", self.f_key, fg=MUTED).pack(side="left")
                self.tk.Label(self.keycaps, text=part, font=self.f_key, fg=TEXT, bg=KEY_BG, padx=10, pady=4,
                              relief="solid", bd=1, highlightbackground=KEY_BORDER).pack(side="left")

        phrase = app.engine.unlock_phrase
        self.phrase_text.configure(
            text=(f"While the computer is locked, just type the word  “{phrase}”  on the keyboard."
                  if phrase else "The backup unlock word is turned off (you can set one in Settings).")
        )
        self.cat_text.configure(
            text=("PawLock notices paws on the keys (or frantic clicking) and locks by itself. "
                  "Nothing the cat types gets through." if app.auto_detect_enabled()
                  else "Automatic cat detection is off. Lock with the shortcut before you leave.")
        )
        self.away_text.configure(
            text=(f"PawLock locks by itself after {app.config.away_lock_minutes:g} minutes without use, "
                  "quietly, so nothing pops up while you watch a video." if app.away_lock_enabled()
                  else "Away mode is off. Press the shortcut before you leave, or turn it on in Settings.")
        )

    # ------------------------------------------------------------------
    # Settings form
    # ------------------------------------------------------------------

    def load_settings(self) -> None:
        values = self.app.current_settings()
        for key, var in self.vars.items():
            var.set(values[key])
        custom = values.get("custom_hotkey")
        if custom:
            self.custom_hotkey_note.configure(
                text=f"You're using a custom shortcut ({custom}). Choosing a letter here replaces it."
            )
            self.custom_hotkey_note.pack(anchor="w")
        else:
            self.custom_hotkey_note.pack_forget()
        self.save_message.configure(text="")

    def _save(self) -> None:
        values = {key: var.get() for key, var in self.vars.items()}
        errors = self.app.save_settings(values)
        if errors:
            self.save_message.configure(text=errors[0], fg=RED)
        else:
            self.save_message.configure(text="✓ Saved", fg=GREEN)
            self.load_settings()
            self.save_message.configure(text="✓ Saved", fg=GREEN)
            self._refresh()

    # ------------------------------------------------------------------
    # Buttons
    # ------------------------------------------------------------------

    def _practice(self) -> None:
        self.app.practice_lock()

    def _lock_now(self) -> None:
        self.app.lock_now()

    def _advanced(self) -> None:
        self.app.open_settings()

    def _quit(self) -> None:
        self.hide()
        self.app.quit()


def build_window(root: Any, app: Any) -> Optional[MainWindow]:
    try:
        return MainWindow(root, app)
    except Exception:
        log.exception("Could not create the PawLock window")
        return None
