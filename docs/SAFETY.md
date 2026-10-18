# Safety: you can't lock yourself out

Any program that blocks the keyboard must answer one question convincingly: *what if it
goes wrong?* PawLock's answer is **layers**, each independent of the others, all designed
to **fail open** (give input back) rather than fail closed.

- [Design principles](#design-principles)
- [The six layers](#the-six-layers)
- [Emergency exits by operating system](#emergency-exits-by-operating-system)
- [The kill switch](#the-kill-switch)
- [Failure scenarios](#failure-scenarios)
- [What PawLock is not](#what-pawlock-is-not)

## Design principles

1. **Input is blocked only by the hook, and the hook only consults one flag.** There is no
   second place that can "forget" to unlock.
2. **Every error path unlocks.** Exceptions while handling an event, crashes in any thread,
   signals, timeouts and dead hooks all end with `engine.force_unlock()`.
3. **The emergency path needs no locks.** `force_unlock()` is an atomic attribute write, so
   it works even if another thread is stuck holding the engine's mutex.
4. **Process death = input back.** Every OS removes the hooks, taps and grabs of a process
   that exits, however it exits. PawLock never installs anything that outlives it.
5. **The hook never waits.** Hook callbacks do microseconds of bookkeeping; anything slow
   happens elsewhere. A slow hook is how input lag (and OS hook removal) happens.

## The six layers

| # | Layer | Where | Triggers |
|---|---|---|---|
| 1 | **Fail-open engine** | `engine.py` | Any exception inside `handle_key` / `handle_mouse_button` lets the event through and calls `force_unlock()`. pynput also stops a listener whose callback raises, which removes the hook. |
| 2 | **Crash guards** | `safety.install_crash_guards` | `sys.excepthook` and `threading.excepthook` release the lock on any unhandled exception in any thread (tray, banner, controller…). |
| 3 | **Signal handlers** | `safety.install_signal_handlers` | `SIGINT` (Ctrl+C), `SIGTERM` (`kill`, `pawlock --stop`), `SIGBREAK`, `SIGHUP`, `SIGQUIT`: unlock first, then shut down cleanly. `atexit` runs the same cleanup. |
| 4 | **Watchdog** | `safety.Watchdog` | Once a second: (a) unlock when `max_lock_minutes` is exceeded; (b) if the controller thread's heartbeat is older than `watchdog_seconds` while locked, force-unlock and release any device grab; (c) if a hook died (or macOS disabled a tap), force-unlock and re-install it. |
| 5 | **Hard exit** | `safety.hard_exit` | If releasing a grab hangs, or hooks fail 5 times within 60 s, PawLock terminates itself with `os._exit`, and the OS frees the input. |
| 6 | **The OS itself** | — | Windows: `Ctrl+Alt+Del` is unblockable, and LL hooks that time out are skipped and eventually removed. macOS: slow taps are disabled. X11: grabs end with the connection. |

On top of these:

- **Single instance**: two PawLocks can't fight over the keyboard.
- **Injected input is never blocked on Windows/macOS**, so on-screen keyboards and
  remote-desktop tools keep working while locked.
- **Optional time limit**: `max_lock_minutes` (or `--max-lock-minutes`) always unlocks
  eventually. Off by default, because a cat nap can be long.
- **Practice mode**: `--practice` or tray → *Practice lock (30 s)* locks with a 30-second
  limit so you can learn the hotkey without any risk.

## Emergency exits by operating system

Try them in this order:

### Windows

1. `Ctrl + Alt + Shift + L`
2. Type `unlock`
3. `Ctrl + Alt + Del` → **Task Manager** → select **PawLock** → **End task**.
   This sequence is handled by the Windows kernel and can never be blocked.
4. A desktop shortcut to `PawLock.exe --stop`, or `PawLock.exe --stop` from another
   session or remote shell.

### macOS

1. `Control + Option + Shift + L`
2. Type `unlock`
3. Wait for `max_lock_minutes`, if you set one.
4. From another device: `ssh you@your-mac '/Applications/PawLock.app/Contents/MacOS/PawLock --stop'`
   (or `python3 -m pawlock --stop` for source installs).
5. Last resort: hold the power button.

### Linux (X11)

1. `Ctrl + Alt + Shift + L`
2. Type `unlock`
3. `Ctrl + Alt + F3` switches to a text console (VT switching is handled by the X server,
   not by grabbing clients). Log in, run `pkill -f -i pawlock`, then switch back with
   `Ctrl + Alt + F1`, `F2` or `F7` depending on your distribution.
4. From another device: `ssh you@your-pc pkill -f -i pawlock`.

## The kill switch

`pawlock --stop` (`PawLock.exe --stop` for the packaged app):

1. reads the PID file written by the running PawLock (`pawlock.pid` in the settings folder);
2. checks the process with that PID **started at the recorded time**, so a recycled PID
   can never make it kill an unrelated program;
3. sends SIGTERM (macOS/Linux: PawLock unlocks and exits cleanly) or terminates the process
   (Windows: the OS removes its hooks immediately);
4. falls back to a hard kill after 5 seconds.

Make it a one-click button: create a desktop shortcut to `PawLock.exe` and add ` --stop`
to the end of the shortcut's *Target*.

## Failure scenarios

What happens if…

| Scenario | Result |
|---|---|
| A bug raises inside the hook | Event passes, lock released, error logged |
| The tray / banner / sound crashes | Lock released (crash guard); PawLock keeps running without that channel |
| The controller thread hangs while locked | Watchdog force-unlocks within `watchdog_seconds` (15 s) |
| The hook thread hangs | Windows/macOS skip the hook and input flows; the watchdog sees a dead hook, unlocks and re-installs |
| macOS disables the tap for being slow | Input flows immediately; watchdog re-installs the tap |
| PawLock is killed (Task Manager, `kill -9`) | OS removes the hooks: input back instantly |
| The PC sleeps / you log out while locked | Hooks are per-session and die with the process on logout; after sleep the lock is still active, so unlock as usual |
| Keyboard can't register 4 keys at once | Type `unlock` instead |
| Settings file is corrupted | Defaults are used (including the default hotkey); the file is left untouched for you to fix |
| A key's release is lost (e.g. to the Windows secure desktop) | The "ghost" key is forgotten after `stale_key_seconds` (10 s), so the exact-match hotkey works again |

## What PawLock is not

PawLock is a **cat lock**, not a **security lock**. Anyone who knows the hotkey, or who
presses `Ctrl+Alt+Del`, can get past it. To protect your computer from people, use your
operating system's screen lock (`Win + L`, `Ctrl + Cmd + Q`, `Super + L`).
