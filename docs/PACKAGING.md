# Packaging PawLock as a standalone app

Non-technical cat owners shouldn't need Python. This guide turns PawLock into a
double-clickable app with [PyInstaller](https://pyinstaller.org), and covers releases,
code signing, antivirus false positives, shortcuts and start-at-login.

- [Quick build](#quick-build)
- [The Windows installer](#the-windows-installer)
- [The macOS disk image](#the-macos-disk-image)
- [Step by step, per OS](#step-by-step-per-os)
- [What the spec file does](#what-the-spec-file-does)
- [Automated releases with GitHub Actions](#automated-releases-with-github-actions)
- [Code signing and "unknown publisher" warnings](#code-signing-and-unknown-publisher-warnings)
- [Antivirus false positives](#antivirus-false-positives)
- [Shortcuts for users](#shortcuts-for-users)
- [Troubleshooting builds](#troubleshooting-builds)

## Quick build

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
python scripts/build.py --archive --installer
```

| OS | App | `--archive` | `--installer` (what to give non-technical users) |
|---|---|---|---|
| Windows | `dist/PawLock.exe` | `PawLock-<v>-windows-x64.zip` | **`PawLock-Setup-<v>.exe`** |
| macOS | `dist/PawLock.app` | `PawLock-<v>-macos-arm64.zip` | **`PawLock-<v>-macos-arm64.dmg`** |
| Linux | `dist/PawLock` | `PawLock-<v>-linux-x64.tar.gz` | – |

`scripts/build.py` regenerates the icons if needed, runs `pyinstaller pawlock.spec
--noconfirm --clean`, checks the output exists, then (with `--archive`) packs it in the
right format for each OS and (with `--installer`) builds the installer. PyInstaller
**cannot cross-compile**: build on each OS you want to ship for.

## The Windows installer

[`packaging/windows/PawLock.iss`](../packaging/windows/PawLock.iss) is an
[Inno Setup 6](https://jrsoftware.org/isinfo.php) script. Install Inno Setup
(`winget install JRSoftware.InnoSetup`), then `python scripts/build.py --installer`.
`build.py` finds `ISCC.exe` and passes the version in. The installer is designed so a
non-technical user only clicks *Next* and *Finish*:

| What | How |
|---|---|
| No administrator password | `PrivilegesRequired=lowest`: installs to `%LOCALAPPDATA%\Programs\PawLock` |
| Short wizard | Welcome (explains PawLock and the shortcut) → Options → Finish; no folder or "ready to install" pages |
| Options | **Start PawLock when I sign in** (ticked) and **desktop icon** (unticked) |
| Start menu | *PawLock*, and *Stop PawLock* (`--stop`), the one-click emergency exit |
| Finish page | *Start PawLock now* (ticked) → the welcome window opens |
| Upgrades | the installer runs `PawLock.exe --stop --quiet` first, so a running copy never blocks the update |
| Uninstall | *Settings → Apps → PawLock*; stops PawLock and removes the start-at-login entry, even if it was switched on later from inside PawLock |

Silent install for IT folks: `PawLock-Setup-<v>.exe /VERYSILENT /MERGETASKS="autostart,!desktopicon"`.
The release workflow installs Inno Setup on the Windows build machine with Chocolatey.

## The macOS disk image

On macOS `--installer` creates `PawLock-<v>-macos-<arch>.dmg` with `hdiutil`: a disk image
containing `PawLock.app` next to a shortcut to *Applications*. Users drag one onto the
other, the familiar Mac way.

## Step by step, per OS

### Windows

1. Install Python 3.9+ from [python.org](https://www.python.org/downloads/) (tick *Add python.exe to PATH*).
2. In the project folder:
   ```powershell
   py -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements-dev.txt
   python scripts\build.py --archive
   ```
3. Test it: `dist\PawLock.exe --doctor` (opens a report), then double-click `dist\PawLock.exe`.
4. Share `dist\PawLock-<version>-windows-x64.zip`.

The exe is a single file of about 20 MB with no console window (`console=False`). Messages
for `--stop`/`--status` appear as dialog boxes; `--doctor` and `--where` open a text file.

### macOS

1. Use Python from python.org or Homebrew (`brew install python-tk` for Tk support).
2. ```bash
   python3 -m venv .venv && source .venv/bin/activate
   pip install -r requirements-dev.txt
   python scripts/build.py --archive
   ```
3. Open `dist/PawLock.app` and grant **Accessibility** and **Input Monitoring** to
   *PawLock* (not to Terminal). Permissions are tied to the app's identity, so you
   may need to re-grant them after every rebuild.
4. Share `dist/PawLock-<version>-macos-<arch>.zip`. It's made with `ditto`, which keeps the
   bundle's symlinks and ad-hoc signature intact.

The bundle sets `LSUIElement` so PawLock lives only in the menu bar, with no Dock icon.
An arm64 build runs on Apple Silicon; build on an Intel Mac for an x86_64 version.

### Linux

1. ```bash
   sudo apt install python3-venv python3-tk    # Debian/Ubuntu
   python3 -m venv .venv && source .venv/bin/activate
   pip install -r requirements-dev.txt
   python scripts/build.py --archive
   ```
2. Share `dist/PawLock-<version>-linux-x64.tar.gz` (tar keeps the executable bit).

Build on the **oldest** distribution you want to support: the binary links against the
build machine's glibc. The release workflow uses Ubuntu 22.04 for that reason.

## What the spec file does

[`pawlock.spec`](../pawlock.spec) is plain Python that PyInstaller executes:

- **Entry point:** `pawlock/__main__.py`.
- **Hidden imports.** pynput and pystray choose their platform backend at runtime with
  `importlib`, which PyInstaller's static analysis can't follow, so each OS lists its own:

  | OS | Hidden imports |
  |---|---|
  | Windows | `pynput.keyboard._win32`, `pynput.mouse._win32`, `pystray._win32` |
  | macOS | `pynput.keyboard._darwin`, `pynput.mouse._darwin`, `pystray._darwin` |
  | Linux | `pynput.{keyboard,mouse}._xorg`, `…_uinput`, `pystray._xorg`, `_appindicator`, `_gtk` |

- **Icons:** `assets/pawlock.ico` (Windows) and `assets/pawlock.png` (macOS; PyInstaller
  converts it to `.icns` because Pillow is installed). Regenerate with
  `python scripts/make_icons.py`; the drawing lives in `pawlock/feedback/icons.py`.
- **Windows/Linux:** one-file `EXE`, `console=False`, **no UPX** (UPX-packed executables
  are a classic antivirus trigger).
- **macOS:** one-folder `EXE` + `COLLECT` wrapped in a `BUNDLE` (`PawLock.app`) with an
  `Info.plist` that hides the Dock icon.
- **Excludes** test and science packages that would otherwise bloat the build.

No data files are bundled: icons are drawn at runtime and settings live in the user's
config folder.

## Automated releases with GitHub Actions

[`.github/workflows/release.yml`](../.github/workflows/release.yml) builds all three
platforms and publishes a GitHub Release when a version tag is pushed:

```bash
# bump __version__ in pawlock/__init__.py and update CHANGELOG.md, then:
git tag v1.0.1
git push origin v1.0.1
```

Each runner installs the dev requirements, **runs the test suite**, builds with
`scripts/build.py --archive` and uploads the archive. A final job creates the release and
attaches the three files. You can also run it by hand (*Actions → Release → Run workflow*)
to get the archives as workflow artifacts without publishing a release.

## Code signing and "unknown publisher" warnings

Unsigned apps trigger warnings that can scare non-technical users:

| OS | What users see | Workaround for users | Proper fix |
|---|---|---|---|
| Windows | SmartScreen "Windows protected your PC" | *More info → Run anyway* | Sign with an OV/EV code-signing certificate (`signtool sign /fd sha256 /tr <timestamp-url> /td sha256 dist\PawLock.exe`). SmartScreen reputation builds over time. |
| macOS | "PawLock can't be opened because Apple cannot check it" | Right-click → *Open*, or *System Settings → Privacy & Security → Open Anyway*, or `xattr -dr com.apple.quarantine /Applications/PawLock.app` | Apple Developer ID: `codesign --deep --options runtime --sign "Developer ID Application: …"`, then `xcrun notarytool submit … --wait` and `xcrun stapler staple`. |
| Linux | — | — | — |

## Antivirus false positives

PawLock installs a **global keyboard hook**, the same API keyloggers use, and is packed
by PyInstaller, whose bootloader is shared with plenty of malware. Some heuristic scanners
add those two facts together. To reduce false positives:

- don't use UPX (the spec already disables it);
- prefer signed builds (see above);
- build from source yourself if you're unsure: the code is short and readable;
- report false positives to the vendor (Microsoft:
  <https://www.microsoft.com/wdsi/filesubmission>).

PawLock has no network code and never records keystrokes, so you can check exactly what
the hook does in `pawlock/backends/` and `pawlock/engine.py`.

## Shortcuts for users

The Windows installer already creates *PawLock* and *Stop PawLock* in the Start menu. For
the portable `.exe`, you can make them yourself:

**Emergency stop button (Windows):** right-click the desktop → *New → Shortcut* → browse to
`PawLock.exe` → *Next* → name it "Stop PawLock" → *Finish*. Then right-click the shortcut →
*Properties* → append ` --stop` to *Target*, e.g.
`"C:\Users\you\Documents\PawLock\PawLock.exe" --stop`.

**Practice shortcut:** same, with ` --practice`.

**Start at login:** tray → *Start at login*. PawLock writes the usual per-user entry, no
admin rights needed:

| OS | Entry |
|---|---|
| Windows | `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\PawLock` |
| macOS | `~/Library/LaunchAgents/io.github.pawlock.plist` (`open -a PawLock.app`) |
| Linux | `~/.config/autostart/pawlock.desktop` |

When running from source, autostart launches `pythonw -m pawlock` (Windows) or
`python -m pawlock`, so install the package (`pip install .`) for that to work from any
folder.

## Troubleshooting builds

| Problem | Fix |
|---|---|
| App starts but no tray icon / hooks | Check `--doctor` *from the built app*; if a backend module is missing, add it to `HIDDEN` in `pawlock.spec` |
| `ModuleNotFoundError: tkinter` in the build | Your Python lacks Tk: install `python3-tk` (Linux) or `python-tk` (Homebrew) and rebuild |
| macOS: permissions granted but no input | Permissions belong to the exact binary; remove PawLock from the lists, re-add the new build, restart it |
| Linux: `GLIBC_2.xx not found` on another machine | Build on an older distro (or in a `ubuntu:22.04` container) |
| Huge build | Build in a clean virtualenv containing only `requirements-dev.txt` |
