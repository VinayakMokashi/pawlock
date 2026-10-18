## What and why

<!-- What does this change, and why is it needed? Link issues with "Fixes #123". -->

## Checklist

- [ ] `pytest` passes
- [ ] `ruff check .` passes
- [ ] New error paths **fail open** (input flows again)
- [ ] Nothing slow or blocking added to the hook path
- [ ] No keystrokes logged or stored
- [ ] Detector changes: before/after `scripts/detector_benchmark.py --runs 50` attached, `medium` still 0% false locks
- [ ] Docs / `CHANGELOG.md` updated
- [ ] Hand-tested on: <!-- Windows / macOS / Linux X11 -->
