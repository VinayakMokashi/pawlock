"""Talking to the user when there may be no console (double-clicked .exe/.app)."""

from __future__ import annotations

import sys

#: Captured at import time, before ``cli.main`` swaps missing streams for
#: ``os.devnull``. False for windowed executables and ``pythonw``.
HAS_CONSOLE = sys.stdout is not None


def show_message(text: str, title: str = "PawLock", error: bool = False) -> None:
    """Print to the console if there is one, otherwise pop up a dialog box."""
    if HAS_CONSOLE:
        stream = sys.stderr if error else sys.stdout
        if stream is not None:
            print(text, file=stream)
            return
    try:
        if sys.platform == "win32":
            import ctypes

            MB_ICONERROR, MB_ICONINFORMATION = 0x10, 0x40
            MB_SETFOREGROUND, MB_TOPMOST = 0x10000, 0x40000
            flags = (MB_ICONERROR if error else MB_ICONINFORMATION) | MB_SETFOREGROUND | MB_TOPMOST
            ctypes.windll.user32.MessageBoxW(None, text, title, flags)
            return
        import tkinter
        from tkinter import messagebox

        root = tkinter.Tk()
        root.withdraw()
        (messagebox.showerror if error else messagebox.showinfo)(title, text, parent=root)
        root.destroy()
    except Exception:  # pragma: no cover - nothing else we can do
        pass
