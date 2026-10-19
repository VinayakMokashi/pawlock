# Troubleshooting

Start with the built-in health check. It installs nothing permanent and blocks nothing:

```bash
pawlock --doctor          # or PawLock.exe --doctor / python -m pawlock --doctor
```

Then look for your symptom below. The log (tray → *Open log folder*, or
`pawlock --where`) usually says exactly what happened.

- [I'm locked and the hotkey doesn't work](#im-locked-and-the-hotkey-doesnt-work)
- [It locked while I was watching / reading](#it-locked-while-i-was-watching--reading)
- [It locked while I was typing](#it-locked-while-i-was-typing)
- [My cat got through](#my-cat-got-through)
- [Windows](#windows)
- [macOS](#macos)
- [Linux / Wayland](#linux-wayland)
- [Tray icon or banner missing](#tray-icon-or-banner-missing)
- [Reporting a bug](#reporting-a-bug)

## I'm locked and the hotkey doesn't work

1. Press **Ctrl + Alt + Shift**, *then* **L**, with no other key held. Lift the cat first:
   a paw still on the keyboard breaks the exact match on purpose.
2. Type **`unlock`** (or your `unlock_phrase`). Some laptop keyboards can't detect four keys
   at once.
3. Use your OS's emergency exit: [SAFETY.md → Emergency exits](SAFETY.md#emergency-exits-by-operating-system).
   On Windows: **Ctrl + Alt + Del → Task Manager → PawLock → End task**.
4. Afterwards, practise with `pawlock --practice` and consider a different `hotkey`.

## It locked while I was watching / reading

That's **away mode**: nobody touched the keyboard, mouse or trackpad for
`away_lock_minutes` (default 10). The log says `LOCKED (away: no keyboard or mouse activity
for 10 minutes)`. It's silent, so press the hotkey when you need input again. To make it
wait longer, set `"away_lock_minutes": 30`; to turn it off, untick **Lock when I'm away**
in the tray.

## It locked while I was typing

- The log line says which rule fired, e.g.
  `LOCKED (auto: 3 keys held down for over 1.5s)`.
- Gaming or holding several keys on purpose? Untick *Detect cats automatically* in the
  tray, or set `"sensitivity": "low"`.
- Tune with `pawlock --dry-run` (nothing is blocked) and `detector_overrides`; see
  [AUTO_DETECTION.md → Tuning](AUTO_DETECTION.md#tuning).
- Please open an issue with the log line (it contains no keystrokes) so the defaults can
  improve.

## My cat got through

- A cat that walks across in one or two steps types a few characters before there's
  enough evidence. Try `"sensitivity": "high"`.
- Trackpad cat? A cat gently walking over a trackpad looks exactly like you using it, so
  it can't be detected safely. Keep **away mode** on (and shorten `away_lock_minutes`), and
  make the click-storm rule more sensitive: `"detector_overrides": {"click_storm_clicks": 8}`.
- Lock manually before leaving the desk: click the tray paw, or press the hotkey.
- **The cat typed on the Windows/macOS sign-in screen?** When the OS locks itself, its
  sign-in screen takes over the keyboard and PawLock can't (and shouldn't) block it. Let
  PawLock's away mode lock first by giving the OS screen lock a longer timeout.

## Windows

| Symptom | Cause & fix |
|---|---|
| "Windows protected your PC" (installer or app) | The app isn't code-signed. *More info → Run anyway.* |
| I can't find PawLock | Start menu → *PawLock*. If it's already running, that opens its window. The paw lives next to the clock (or behind the **^** arrow). |
| How do I uninstall? | *Settings → Apps → Installed apps → PawLock → Uninstall*. Your settings stay in `%APPDATA%\PawLock` (delete that folder too for a clean slate). |
| Antivirus quarantined PawLock.exe | False positive caused by the global keyboard hook + PyInstaller; see [PACKAGING.md](PACKAGING.md#antivirus-false-positives). Restore it and add an exclusion, or run from source. |
| Keys still reach one particular window | That window runs **as administrator**. Windows hides elevated windows' input from normal apps, so run PawLock as administrator too. |
| `Ctrl+Alt+Del`, `Win+L` still work while locked | By design: Windows doesn't let any app block them. That's your emergency exit. |
| Three-finger touchpad gestures still work | Some precision-touchpad gestures are handled inside Windows below the hook level. Clicks, taps, scrolling and pointer movement are blocked. |
| Text is tiny/blurry in the banner | Report your display scaling in an issue; the banner scales with DPI. |

## macOS

| Symptom | Cause & fix |
|---|---|
| Nothing is blocked, hotkey does nothing | Missing permissions. *System Settings → Privacy & Security* → enable PawLock (or your Terminal / IDE when running from source) under **Accessibility** *and* **Input Monitoring**, then **restart PawLock**. `--doctor` reports this. |
| Permissions are on but still nothing | After updating/rebuilding, macOS treats it as a new app: remove PawLock from both lists with **–**, add it again, restart it. |
| "PawLock can't be opened" | Not notarised: right-click → *Open*, or *Privacy & Security → Open Anyway*. |
| Pinch / swipe gestures still work | Gesture events aren't part of the event taps pynput installs. Clicks, taps, movement and scrolling are blocked. |
| Crash on start when the banner is enabled | Tk and pynput's event tap don't always coexist on recent macOS. The banner (and with it the PawLock window) is off by default on macOS; keep `"overlay": false` and use the menu-bar paw. |
| No PawLock window on a Mac | Same reason as above: on macOS the window is only available with `"overlay": true`. The menu-bar paw has every switch, and *Settings…* opens the settings file. |
| Hotkey letter seems to be "wrong" on a non-US layout | macOS key codes are positional: the hotkey uses the key in the US "L" position. Pick a hotkey based on where the key physically is, or use an F-key. |

<h2 id="linux-wayland">Linux / Wayland</h2>

**Wayland** (the default on recent Ubuntu, Fedora, …) intentionally doesn't let ordinary
apps watch or block global input, so neither PawLock nor any similar tool can work in a
Wayland session. Options:

1. **Log in with Xorg/X11:** on the login screen click the ⚙ gear and choose
   *"Ubuntu on Xorg"* / *"GNOME on Xorg"*.
2. **uinput backend (advanced):** pynput can read devices directly via `evdev`, which
   requires root or membership of the `input` group:
   ```bash
   sudo PYNPUT_BACKEND=uinput python3 -m pawlock --no-tray --no-overlay
   ```
   This is experimental and grabs devices system-wide.

| Symptom | Cause & fix |
|---|---|
| `--doctor` says *No DISPLAY set* | You're on a text console or Wayland-only session. |
| No tray icon on GNOME | Install the *AppIndicator and KStatusNotifierItem Support* extension. |
| No banner | `sudo apt install python3-tk`; transparency needs a compositor. |
| No sound | Install `pulseaudio-utils` (`paplay`) or `gnome-session-canberra`. |

## Tray icon or banner missing

PawLock keeps protecting you even if a feedback channel fails; check the log for
"Tray icon unavailable" or "On-screen banner unavailable". On Windows the icon may be
hidden behind the **^** arrow: drag it onto the taskbar to keep it visible.

## Reporting a bug

Open an issue at <https://github.com/VinayakMokashi/pawlock/issues> with:

1. the output of `pawlock --doctor`,
2. the relevant part of `pawlock.log` (it never contains keystrokes),
3. your OS version, keyboard type (laptop/external), and what the cat was doing.
