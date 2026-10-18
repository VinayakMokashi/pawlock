# Contributing to PawLock

Thanks for helping keep keyboards cat-safe! Bug reports, detector tuning data, docs fixes
and code are all welcome.

## Ground rules

PawLock blocks people's keyboards, so a few rules are non-negotiable:

1. **Fail open.** Any new error path must end with input flowing again. Never add a
   code path that could keep the lock engaged after an exception.
2. **Keep the hook path fast.** Code reached from `LockEngine.handle_*` or a backend's
   filter/intercept must not block, sleep, log at INFO+ per event, or do I/O. Hand slow
   work to the controller thread via the state-change queue.
3. **Never record keystrokes.** No key names in logs, notifications or files. Detection
   messages describe the *shape* of input only.
4. **Tests for behaviour changes.** The suite must keep running without real input
   devices: no pynput imports in tests; use fakes and `pawlock.simulate`.

## Development setup

```bash
git clone https://github.com/VinayakMokashi/pawlock.git
cd pawlock
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
pytest                           # fast, headless, cross-platform
ruff check .
python -m pawlock --dry-run      # try it without blocking anything
```

## Where things live

| Change | File(s) |
|---|---|
| What gets swallowed and when | `pawlock/engine.py` + `tests/test_engine.py` |
| Detection rules / presets | `pawlock/detector.py` + `tests/test_detector.py`; re-run `scripts/detector_benchmark.py` and update `docs/AUTO_DETECTION.md` |
| Platform input glue | `pawlock/backends/*.py` + `tests/test_backends.py` |
| Tray / banner / sounds | `pawlock/feedback/` |
| Watchdog / crash handling | `pawlock/safety.py` + `tests/test_safety.py` |
| Settings | `pawlock/config.py` (add a validator!) + `docs/CONFIGURATION.md` |
| Packaging | `pawlock.spec`, `scripts/build.py`, `docs/PACKAGING.md` |

## Detector changes need numbers

If you change a threshold or signal, include the before/after output of:

```bash
python scripts/detector_benchmark.py --runs 50
```

The default (`medium`) preset must stay at **0% false locks** for every human-typing row.

## Real-cat data

The most valuable contribution of all: run `pawlock --dry-run --log-level DEBUG` while
your cat does its thing and share the `LOCKED (auto: …)` lines (or the lack of them) in an
issue. They contain no keystrokes.

## Pull requests

- One topic per PR, with a short description of *why*.
- `pytest` and `ruff check .` pass (CI runs them on Windows, macOS and Linux).
- Update `CHANGELOG.md` under an *Unreleased* heading.
- If you touched a backend, say which OS you tested it on by hand.

## Releasing (maintainers)

1. Bump `__version__` in `pawlock/__init__.py` and move *Unreleased* notes in
   `CHANGELOG.md` under the new version.
2. `git tag vX.Y.Z && git push origin vX.Y.Z`. The release workflow builds and publishes
   the Windows, macOS and Linux downloads.
