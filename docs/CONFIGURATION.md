# Configuration

PawLock stores its settings in a small JSON file, created with defaults the first time it
runs.

| OS | Location |
|---|---|
| Windows | `%APPDATA%\PawLock\config.json` |
| macOS | `~/Library/Application Support/PawLock/config.json` |
| Linux | `$XDG_CONFIG_HOME/pawlock/config.json` (usually `~/.config/pawlock/config.json`) |

`pawlock --where` prints the exact path. Set the `PAWLOCK_HOME` environment variable to
keep settings, logs and the PID file somewhere else (e.g. a USB stick for a portable copy).

**Editing:** tray → *Edit settings…*, save, then tray → *Reload settings*. Changes to
`tray`, `overlay` and `backend` need a restart; everything else applies on reload.

**Mistakes are safe.** Every value is validated. An invalid value is replaced by its
default and reported in the log; it never stops PawLock from starting. If the whole
file is unreadable, the defaults are used and your file is left untouched so you can fix
it. Keys starting with `_` are ignored, so you can leave yourself notes.
`pawlock --reset-config` restores the defaults and keeps a backup.

## All settings

### Locking

| Key | Default | Allowed | Description |
|---|---|---|---|
| `hotkey` | `"ctrl+alt+shift+l"` | 1+ modifiers + exactly 1 key | Toggles the lock. Modifiers: `ctrl`, `alt` (`option`), `shift`, `cmd` (`win`, `super`). Keys: `a`-`z`, `0`-`9`, `f1`-`f24`, punctuation, and names like `page_up`, `insert`, `pause`. Use **at least two modifiers** (PawLock logs a warning otherwise). |
| `unlock_phrase` | `"unlock"` | 4-32 letters/digits, or `""` | Typed while locked, unlocks. Case-insensitive; Shift is ignored. `""` disables it. |
| `lock_mouse` | `true` | bool | Also block mouse/trackpad movement, clicks and scrolling. |
| `start_locked` | `false` | bool | Lock as soon as PawLock starts. |
| `max_lock_minutes` | `0` | 0-1440 | Auto-unlock after this long. `0` = never. |

### Cat detection

| Key | Default | Allowed | Description |
|---|---|---|---|
| `auto_detect` | `true` | bool | Lock automatically when a cat is detected (also a tray checkbox). |
| `sensitivity` | `"medium"` | `low`, `medium`, `high` | Detector preset. See [AUTO_DETECTION.md](AUTO_DETECTION.md#presets). |
| `cooldown_seconds` | `5` | 0-600 | After an unlock, ignore the detector for this long. |
| `detector_overrides` | `{}` | object | Per-threshold overrides on top of the preset (below). |

`detector_overrides` fields (`0` disables a rule):

| Field | medium | Meaning |
|---|---|---|
| `chord_keys` | 5 | Keys held at once for the *paw chord* rule |
| `chord_min_rows` | 2 | …spread over at least this many keyboard rows |
| `sit_keys` | 3 | Keys held for the *sitting* rule |
| `sit_seconds` | 1.5 | …for at least this long |
| `long_hold_seconds` | 20 | One typing key held this long |
| `mash_window_keys` | 12 | Key presses examined together for *mashing* |
| `mash_window_seconds` | 3 | …that must fit in this time span |
| `mash_signals_needed` | 3 | Signals required (paw contact always required) |
| `click_storm_clicks` | 0 | Clicks for the *click storm* rule (0 = off) |
| `click_storm_seconds` | 2 | …within this many seconds |

### Feedback

| Key | Default | Allowed | Description |
|---|---|---|---|
| `tray` | `true` | bool | Tray / menu-bar icon. |
| `overlay` | `true` (`false` on macOS) | bool | Always-on-top banner while locked. |
| `overlay_position` | `"top"` | `top`, `bottom`, `center` | Where the banner appears. |
| `sound` | `true` | bool | Lock/unlock sounds (also a tray checkbox). |
| `notifications` | `true` | bool | Desktop notification on cat detection and safety unlocks. |

### Safety & advanced

| Key | Default | Allowed | Description |
|---|---|---|---|
| `watchdog_seconds` | `15` | 3-600 | Force-unlock if the controller thread is unresponsive this long while locked. |
| `stale_key_seconds` | `10` | 0-3600 | Forget a held key not heard from in this long (lost releases). `0` disables. |
| `backend` | `"auto"` | `auto`, `native`, `swap` | `swap` forces the portable listener-swap backend (debugging only). |
| `log_level` | `"INFO"` | `DEBUG`, `INFO`, `WARNING`, `ERROR` | Log detail. Logs never contain keystrokes. |

## Example configurations

**Defaults** (what a fresh install writes):

```json
{
  "hotkey": "ctrl+alt+shift+l",
  "unlock_phrase": "unlock",
  "lock_mouse": true,
  "start_locked": false,
  "max_lock_minutes": 0,
  "auto_detect": true,
  "sensitivity": "medium",
  "cooldown_seconds": 5.0,
  "detector_overrides": {},
  "tray": true,
  "overlay": true,
  "overlay_position": "top",
  "sound": true,
  "notifications": true,
  "watchdog_seconds": 15.0,
  "stale_key_seconds": 10.0,
  "backend": "auto",
  "log_level": "INFO"
}
```

**Keyboard only.** The cat sleeps on the keyboard but you still want the mouse:

```json
{ "lock_mouse": false }
```

**Gamer.** Fewer false alarms, with a different hotkey:

```json
{
  "hotkey": "ctrl+alt+shift+p",
  "sensitivity": "low",
  "detector_overrides": { "sit_seconds": 4 }
}
```

**Very determined cat.** Quick to lock, but with a safety time limit:

```json
{
  "sensitivity": "high",
  "detector_overrides": { "click_storm_clicks": 10 },
  "max_lock_minutes": 120
}
```

**Personal unlock word:**

```json
{ "unlock_phrase": "snowy" }
```

## Command-line overrides

These apply to one run only and are never saved: `--sensitivity`, `--max-lock-minutes`,
`--no-auto-detect`, `--no-tray`, `--no-overlay`, `--no-sound`, `--lock`, `--log-level`,
`--config FILE`. See `pawlock --help`.

## Logs

`logs/pawlock.log` next to the settings file (tray → *Open log folder*), rotated at 1 MB,
3 files kept. It records start/stop, every lock/unlock with its reason, warnings and
errors. It never contains what you typed.
