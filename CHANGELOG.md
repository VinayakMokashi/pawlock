# Changelog

All notable changes to PawLock are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [1.2.0] - 2026-10-19

Made for everyone: no command line, no settings files.

### Added

- **Windows installer** (`PawLock-Setup-<version>.exe`): Next → Finish, no administrator
  password, Start-menu entries for *PawLock* and an emergency *Stop PawLock*, optional
  start-at-login (on by default) and desktop icon, a proper uninstaller in Settings → Apps.
- **macOS disk image** (`.dmg`): drag PawLock into Applications.
- **The PawLock window**: a plain-English *How to use* page (shortcut shown as keys,
  unlock word, cat detection, away mode, where to find the paw, emergency exit) with
  *Try it (30-second practice)* and *Lock now* buttons, and a *Settings* page with
  checkboxes and lists instead of the JSON file. Changes apply immediately.
- **Welcome on first run**: the window opens by itself the first time PawLock starts.
- Clicking the tray paw opens the window; starting PawLock again while it's running
  brings the window forward instead of an "already running" message.
- On Windows 11 the paw is placed next to the clock on first run, instead of hidden
  behind the ^ arrow.
- `--quiet` (no dialogs, for installers/scripts) and `--welcome`.

### Changed

- Simpler tray menu: *Open PawLock*, lock/practice/unlock, the main switches,
  *Settings…*, *How to use*, with technical items moved into an *Advanced* submenu.
- Left-clicking the tray paw no longer locks the computer.

## [1.1.0] - 2026-10-18

Protection for when you're in another room, and for the trackpad.

### Added

- **Away mode** (on by default): locks by itself after 10 minutes with nobody at the
  computer, so a cat that turns up later finds it already locked. Silent (tray icon only);
  the banner appears as soon as someone touches the keyboard or trackpad. Uses the OS idle
  timer (Windows, macOS, X11) as well as PawLock's own hooks so it never locks while you
  work. New settings `away_lock` / `away_lock_minutes`, tray checkbox
  *Lock when I'm away*, and `--away-minutes`.
- **"While you were away" summary** on unlock: e.g. *Blocked 214 key presses, 37 clicks and
  some scrolling while locked.* (counts only, never which keys).
- `--doctor` reports away mode and whether the OS idle timer is available.

### Changed

- The **click storm** rule (trackpad/mouse kneading) is now on by default: 15 clicks within
  2.5 s on `medium`, 10 within 2 s on `high`, off on `low`. Double-clicks, triple-clicks and
  brisk clicking stay well below it.
- Scrolling (mouse wheel and two-finger trackpad scrolls) is reported separately from
  pointer movement on every platform; the Linux backend now also watches pointer movement
  so away mode sees mouse activity there.

## [1.0.0] - 2026-10-18

First public release.

### Added

- Global keyboard **and** mouse/trackpad locking on Windows (low-level hooks), macOS
  (Quartz event taps) and Linux/X11 (device grab), built on pynput.
- Exact-match lock/unlock hotkey, default `Ctrl + Alt + Shift + L`, checked inside the
  hook so it works while locked without ever reaching apps.
- Backup unlock phrase (default `unlock`) for keyboards that can't register four keys.
- Automatic cat detection with five rules (paw chord, sitting, long hold, mashing,
  optional click storm) and `low` / `medium` / `high` presets, benchmarked against
  simulated typists and cats.
- Balanced suppression: releases of keys and buttons pressed before a lock are always
  delivered, so nothing gets stuck.
- Feedback: colour-coded tray icon with menu, click-through always-on-top banner
  (DPI-aware), lock/unlock sounds, desktop notifications.
- Safety: fail-open engine, crash guards, signal handlers, watchdog (time limit,
  heartbeat, hook re-installation), hard-exit last resort, single-instance guard and a
  PID-reuse-safe `--stop` kill switch.
- `--dry-run`, `--practice`, `--doctor`, `--status`, `--where`, `--reset-config`.
- Tray "Practice lock (30 s)" and "Start at login" (Windows Run key, macOS LaunchAgent,
  XDG autostart).
- Self-healing JSON settings with validation and live reload.
- PyInstaller spec and build script; GitHub Actions CI on three OSes and a release
  workflow producing Windows, macOS and Linux downloads.
- Documentation: architecture, detection, safety, configuration, packaging,
  troubleshooting.

[1.2.0]: https://github.com/VinayakMokashi/pawlock/releases/tag/v1.2.0
[1.1.0]: https://github.com/VinayakMokashi/pawlock/releases/tag/v1.1.0
[1.0.0]: https://github.com/VinayakMokashi/pawlock/releases/tag/v1.0.0
