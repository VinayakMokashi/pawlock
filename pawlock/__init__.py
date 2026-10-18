"""PawLock: cat-proof your computer.

PawLock temporarily blocks the keyboard and trackpad/mouse when a cat walks,
sits or sleeps on them, and lets a human unlock with a hotkey that no paw
will ever press by accident.

Package map
-----------
``keys``       one vocabulary of key names for every OS
``hotkey``     the lock/unlock hotkey and the unlock phrase
``detector``   the "is that a cat?" heuristics
``engine``     the lock state machine called for every input event
``backends``   platform glue that hooks the OS input stream (via pynput)
``feedback``   tray icon, on-screen banner and sounds
``safety``     watchdog, crash guards and signal handlers
``app``        wires everything together
``cli``        command-line entry point (``python -m pawlock``)
"""

__version__ = "1.1.0"
APP_NAME = "PawLock"

__all__ = ["APP_NAME", "__version__"]
