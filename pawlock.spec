# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller recipe for PawLock.

Build with:   python scripts/build.py      (or: pyinstaller pawlock.spec)

* Windows: one-file PawLock.exe, no console window, paw icon.
* macOS:   PawLock.app menu-bar app (LSUIElement: no Dock icon).
* Linux:   one-file PawLock binary.

pynput and pystray pick their platform backend at runtime with importlib,
which PyInstaller can't see, so the right backend modules are listed as
hidden imports for each OS.
"""

import re
import sys
from pathlib import Path

ROOT = Path(SPECPATH)  # noqa: F821 - provided by PyInstaller
VERSION = re.search(r'__version__ = "([^"]+)"', (ROOT / "pawlock" / "__init__.py").read_text()).group(1)

if sys.platform == "win32":
    HIDDEN = ["pynput.keyboard._win32", "pynput.mouse._win32", "pystray._win32"]
    ICON = str(ROOT / "assets" / "pawlock.ico")
elif sys.platform == "darwin":
    HIDDEN = ["pynput.keyboard._darwin", "pynput.mouse._darwin", "pystray._darwin"]
    ICON = str(ROOT / "assets" / "pawlock.png")  # Converted to .icns (Pillow required).
else:
    HIDDEN = [
        "pynput.keyboard._xorg", "pynput.mouse._xorg",
        "pynput.keyboard._uinput", "pynput.mouse._uinput",
        "pystray._xorg", "pystray._appindicator", "pystray._gtk",
    ]
    ICON = None

a = Analysis(  # noqa: F821
    [str(ROOT / "pawlock" / "__main__.py")],
    pathex=[str(ROOT)],
    hiddenimports=HIDDEN,
    excludes=["pytest", "_pytest", "numpy", "IPython", "matplotlib"],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821

if sys.platform == "darwin":
    exe = EXE(  # noqa: F821
        pyz, a.scripts, [],
        exclude_binaries=True,
        name="PawLock",
        console=False,
        icon=ICON,
    )
    coll = COLLECT(exe, a.binaries, a.datas, name="PawLock")  # noqa: F821
    app = BUNDLE(  # noqa: F821
        coll,
        name="PawLock.app",
        icon=ICON,
        bundle_identifier="io.github.pawlock",
        version=VERSION,
        info_plist={
            "CFBundleName": "PawLock",
            "CFBundleDisplayName": "PawLock",
            "CFBundleShortVersionString": VERSION,
            "LSUIElement": True,  # Menu-bar app: no Dock icon.
            "NSHighResolutionCapable": True,
            "NSHumanReadableCopyright": "MIT License",
        },
    )
else:
    exe = EXE(  # noqa: F821
        pyz, a.scripts, a.binaries, a.datas, [],
        name="PawLock",
        console=False,  # No terminal window; messages use dialogs instead.
        icon=ICON,
        upx=False,      # UPX-packed binaries trip antivirus heuristics.
    )
