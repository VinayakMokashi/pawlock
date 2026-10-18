# Changelog

All notable changes to PawLock are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

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

[1.0.0]: https://github.com/VinayakMokashi/pawlock/releases/tag/v1.0.0
