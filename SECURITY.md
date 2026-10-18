# Security & privacy

## What PawLock does with your input

PawLock installs a system-wide keyboard and mouse hook, the same OS facility that
accessibility tools, hotkey managers and, unfortunately, keyloggers use. Because of that,
here is exactly what it does and doesn't do:

- It **inspects** each key/mouse event to decide whether to let it through.
- It keeps **in memory only** the keys currently held and the last ≤ 16 key presses (name +
  timestamp) so the cat detector can judge their *shape*. These are discarded continuously.
- It **never writes keystrokes** to disk, logs, notifications or anywhere else.
- It contains **no network code**: no telemetry, no update checks, no cloud.
- It ignores *injected* (synthetic) input on Windows and macOS.

All of this lives in a few short files you can audit: `pawlock/backends/`,
`pawlock/engine.py`, `pawlock/detector.py`.

## PawLock is not a security boundary

PawLock protects your work from **cats**, not from **people**. Anyone who knows the
hotkey, or presses `Ctrl + Alt + Del` on Windows, can get past it. Use your operating
system's screen lock to keep people out.

## Reporting a vulnerability

If you find a way PawLock could leak keystrokes, be abused to capture input, or leave a
user permanently locked out, please **don't open a public issue**. Use GitHub's
[private vulnerability reporting](https://github.com/VinayakMokashi/pawlock/security/advisories/new)
instead. You'll get a reply within a week.
