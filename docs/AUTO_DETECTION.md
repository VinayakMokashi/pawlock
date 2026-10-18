# Automatic cat detection

PawLock can lock itself when the input "looks like a cat". This page explains every rule,
the numbers behind the presets, how they were measured, and how to tune them.

- [The idea](#the-idea)
- [Rules](#rules)
- [The mashing score](#the-mashing-score)
- [Presets](#presets)
- [Benchmarks](#benchmarks)
- [Trackpad and mouse](#trackpad-and-mouse)
- [Tuning](#tuning)
- [Known false positives](#known-false-positives)
- [Privacy](#privacy)

## The idea

People type with fingers: one key at a time, in a rhythm, mostly real words separated
by spaces. Cats "type" with paws: a soft pad 3-4 cm wide that lands on **several
neighbouring keys at the same instant**, often **stays there**, and produces strings with
**no spaces and no vowels**.

The detector watches *how* keys go down (timing, overlap, physical position), never
*what* you're writing. It sees each key press while the computer is unlocked and stops
being consulted while locked.

## Rules

Each rule can fire on its own. Values are for the default **medium** preset.

| # | Rule | Fires when | Why it's cat-specific |
|---|---|---|---|
| 1 | **Paw chord** | ≥ 5 non-modifier keys are down at once, spread over ≥ 2 keyboard rows | Fingers rarely hold 5 ordinary keys; a standing cat holds a dozen |
| 2 | **Sitting** | ≥ 3 keys have each been held for ≥ 1.5 s | People hold one key (Backspace, an arrow), not three random ones |
| 3 | **Long hold** | one typing key held ≥ 20 s | A toe bean parked on a key. Editing/arrow keys are exempt |
| 4 | **Mashing** | the last 12 presses fit in 3 s **and** show *paw contact* + at least 2 more signals | Walking cats; see below |
| 5 | **Click storm** | ≥ 15 mouse/trackpad clicks within 2.5 s | Kneading or batting the trackpad / mouse |

Modifiers (Ctrl, Shift, Alt, Cmd/Win) are ignored by every rule.
OS auto-repeat is recognised and never counted as new presses.

## The mashing score

For the last *N* fresh key presses (12 in medium), five signals are computed by
`detector.mash_signals()`:

| Signal | Definition | Human typing | Cat walking |
|---|---|---|---|
| **paw contact** | ≥ 30% of presses landed within 35 ms of the previous one while it was still down, *or* while 3+ other keys were down | almost never | almost always |
| **no spaces** | no Space / Enter / Tab in the window | sometimes (URLs, code) | usually |
| **no vowels** | ≥ half the keys are letters and < 25% of them are vowels | rarely | usually |
| **clustered keys** | ≥ 45% of consecutive different keys are physical neighbours | rarely | usually |
| **very fast** | ≥ 10 presses per second across the window | bursts only | often |

**Paw contact is mandatory.** Without it, quick tapping of passwords, card numbers or vim
`hjkl` movements, which can easily score "no spaces + no vowels + clustered + fast",
would trigger. With it, they never do, while real paws still do.

Key positions come from a model of a US keyboard with staggered rows (`keys.py`), so
`f` neighbours `d`, `g`, `r`, `t`, `c` and `v`.

## Presets

| Setting | low | **medium** | high |
|---|---|---|---|
| `chord_keys` / `chord_min_rows` | 6 / 3 | **5 / 2** | 5 / 2 |
| `sit_keys` / `sit_seconds` | 4 / 2.5 s | **3 / 1.5 s** | 3 / 1.0 s |
| `long_hold_seconds` | off | **20 s** | 8 s |
| `mash_window_keys` / `mash_window_seconds` | 16 / 3 s | **12 / 3 s** | 10 / 3 s |
| `mash_signals_needed` | 4 | **3** | 2 |
| `click_storm_clicks` / `click_storm_seconds` | off | **15 / 2.5 s** | 10 / 2 s |

## Benchmarks

Generated with the reproducible simulator (`pawlock/simulate.py`):

```bash
python scripts/detector_benchmark.py --runs 50
```

### False locks while a person types (50 runs each, lower is better)

The typing sample mixes prose, punctuation, capitals (with Shift) and a line of code.
"Long key holds" means each key stays down for up to 200 ms, so 2-3 keys overlap all the
time, which is the hardest case for a rollover-heavy fast typist.

| Typing | low | medium | high |
|---|---|---|---|
| 40 WPM | 0% | 0% | 0% |
| 70 WPM | 0% | 0% | 0% |
| 100 WPM | 0% | 0% | 0% |
| 130 WPM, long key holds | 0% | 0% | 0% |
| 160 WPM, long key holds | 0% | 0% | 8% |
| password, 12 keys/s | no | no | no |
| vim hjkl, 14 keys/s | no | no | no |
| card number, 12 keys/s | no | no | no |

### Cats caught (50 cats each, higher is better)

A simulated walking cat lands 2-4 neighbouring keys per step within 20 ms, holds them for
120-350 ms and takes a step every 0.2-0.45 s. A sitting cat presses ~7 keys within 150 ms
and holds them, with OS auto-repeat on the last one.

| Cat behaviour | low | medium | high |
|---|---|---|---|
| walks 3 steps across the keys | 14% | 32% | 46% |
| walks 4 steps across the keys | 18% | 56% | 92% |
| walks 6 steps across the keys | 60% | 98% | 100% |
| walks 8 steps across the keys | 72% | 100% | 100% |
| sits / lies down on the keyboard | 100% | 100% | 100% |
| parks one paw on a key for 30 s | no | yes | yes |

These are simulations, not real cats; real paws vary. If yours slips through or you get
false locks, see [Tuning](#tuning) and please open an issue with your `--dry-run` log.

## Trackpad and mouse

While PawLock is locked, the trackpad and mouse are fully blocked: pointer movement,
clicks, taps, drags and scrolling (two-finger scrolls included). Detecting a cat that uses
*only* the trackpad is harder:

| Cat behaviour | What PawLock sees | Detected? |
|---|---|---|
| Kneading / batting the trackpad or mouse | a burst of clicks | ✅ **click storm** (15+ in 2.5 s) |
| Lying across a laptop (keys **and** trackpad) | keys held down | ✅ **paw chord / sitting** |
| Walking over the trackpad | a pointer move and a tap or two | ❌ looks exactly like a person |
| Lying on the trackpad only | usually nothing (the touchpad's palm rejection ignores it), sometimes stray taps | ❌ / partly |

Normal clicking stays well below the click-storm threshold (tested in
`tests/test_detector.py`): double-clicks, triple-clicks to select paragraphs, and brisk
clicking at 4 clicks per second for 10 seconds never trigger it.

For the cases that can't be detected safely, PawLock relies on **away mode**: after 10
minutes with nobody at the computer it locks by itself, so a cat that arrives later finds
it already locked. Away mode measures inactivity with PawLock's own hooks *and* the OS idle
timer (`GetLastInputInfo` on Windows, `CGEventSourceSecondsSinceLastEventType` on macOS,
the X11 screensaver extension on Linux) and only fires when both agree, so it doesn't lock
while you work in windows PawLock's hooks can't see.

## Tuning

1. **Watch first.** Run `pawlock --dry-run`. Nothing is ever blocked; when the detector
   fires you'll see an amber "would lock" banner and a log line with the rule and signals,
   for example:
   `LOCKED (auto: keyboard mashing (paw contact, no spaces, no vowels, clustered keys)) [dry run]`
2. **Change the preset** with `"sensitivity": "low" | "medium" | "high"`, or per run with
   `--sensitivity`.
3. **Fine-tune single thresholds** in `detector_overrides`, applied on top of the preset:

   ```json
   {
     "sensitivity": "medium",
     "detector_overrides": {
       "sit_seconds": 3.0,
       "long_hold_seconds": 0,
       "click_storm_clicks": 12
     }
   }
   ```

   Any field from the presets table works. `0` disables that rule.
4. **Cooldown.** After you unlock, detection pauses for `cooldown_seconds` (default 5 s)
   so the keys you were just pressing don't immediately re-lock the machine.

## Known false positives

| Situation | Rule | Fix |
|---|---|---|
| Games that hold 3+ letter keys (W+A+E) for over 1.5 s | sitting | Untick *Detect cats automatically* while gaming, or `"sit_seconds": 4` |
| Push-to-talk on a letter key, talking > 20 s | long hold | `"long_hold_seconds": 0` or a PTT key like Caps Lock / a mouse button |
| Clicker games, rapid-fire clicking | click storm | `"click_storm_clicks": 0`, or untick detection while playing |
| Watching a video without touching anything for 10 min | away mode (not the detector) | It's silent; press the hotkey when you need input, or raise `away_lock_minutes` |
| Deliberate key-mashing ("asdfjkl;" rage) | mashing | Working as intended 🙂 |
| 160+ WPM typists on `high` | chord / mash | Use `medium` |

## Privacy

The detector keeps, in memory only, the names and timestamps of at most the last 16 key
presses and the keys currently held. Detection messages describe the *shape* of the input
("6 keys pressed at once across 3 keyboard rows"), never which keys. Nothing is written to
disk or sent anywhere.
