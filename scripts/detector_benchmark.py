"""Measure the cat detector against simulated humans and simulated cats.

    python scripts/detector_benchmark.py            # quick (about 20 s)
    python scripts/detector_benchmark.py --runs 100 # more precise

Prints Markdown tables (pasted into docs/AUTO_DETECTION.md):

* how often each preset wrongly locks while a *person* types (lower is better)
* how often it catches a *cat* walking / sitting (higher is better)

All input comes from pawlock.simulate, so results are reproducible.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pawlock import simulate as sim  # noqa: E402
from pawlock.detector import PRESETS, CatDetector  # noqa: E402

TYPISTS = [
    ("40 WPM", dict(wpm=40)),
    ("70 WPM", dict(wpm=70)),
    ("100 WPM", dict(wpm=100)),
    ("130 WPM, long key holds", dict(wpm=130, hold=(0.06, 0.2))),
    ("160 WPM, long key holds", dict(wpm=160, hold=(0.06, 0.2))),
]
TAPPING = [
    ("password, 12 keys/s", "tr0ub4dor3xyzq1wplm", 12),
    ("vim hjkl, 14 keys/s", "jjjkkkjjjhhhlllkkjjjkk", 14),
    ("card number, 12 keys/s", "4111111111111111", 12),
]
CAT_WALKS = [3, 4, 6, 8]


def detects(events, preset: str) -> bool:
    detector = CatDetector(PRESETS[preset])
    return any(detector.on_key(k, p, t) for t, k, p in events)


def pct(hits: int, runs: int) -> str:
    return f"{100 * hits / runs:.0f}%"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--runs", type=int, default=30, help="random seeds per scenario")
    runs = parser.parse_args().runs
    presets = list(PRESETS)

    print(f"### False locks while a person types ({runs} runs each, lower is better)\n")
    print("| Typing | " + " | ".join(presets) + " |")
    print("|---|" + "---|" * len(presets))
    for label, kwargs in TYPISTS:
        cells = [pct(sum(detects(sim.human_typing(sim.SAMPLE_TEXT, seed=s, **kwargs), p) for s in range(runs)), runs)
                 for p in presets]
        print(f"| {label} | " + " | ".join(cells) + " |")
    for label, keys, rate in TAPPING:
        cells = ["yes" if detects(sim.taps(keys, rate=rate), p) else "no" for p in presets]
        print(f"| {label} | " + " | ".join(cells) + " |")

    print(f"\n### Cats caught ({runs} cats each, higher is better)\n")
    print("| Cat behaviour | " + " | ".join(presets) + " |")
    print("|---|" + "---|" * len(presets))
    for steps in CAT_WALKS:
        cells = [pct(sum(detects(sim.cat_walk(steps=steps, seed=s), p) for s in range(runs)), runs) for p in presets]
        print(f"| walks {steps} steps across the keys | " + " | ".join(cells) + " |")
    cells = [pct(sum(detects(sim.cat_sit(seed=s), p) for s in range(runs)), runs) for p in presets]
    print("| sits / lies down on the keyboard | " + " | ".join(cells) + " |")
    cells = ["yes" if detects(sim.key_held("k", 30), p) else "no" for p in presets]
    print("| parks one paw on a key for 30 s | " + " | ".join(cells) + " |")


if __name__ == "__main__":
    main()
