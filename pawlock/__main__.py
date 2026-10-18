"""Entry point for ``python -m pawlock`` and for the PyInstaller executable."""

import sys

from pawlock.cli import main

if __name__ == "__main__":
    sys.exit(main())
