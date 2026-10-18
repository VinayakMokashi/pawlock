"""Build a standalone PawLock app with PyInstaller (no Python needed to run it).

    python scripts/build.py            # build for the current OS
    python scripts/build.py --archive  # ...and pack it for a GitHub release

Output:
    Windows  dist/PawLock.exe            (single file, no console window)
    macOS    dist/PawLock.app            (menu-bar app, no Dock icon)
    Linux    dist/PawLock                (single file)

PyInstaller cannot cross-compile: build on each OS you want to ship for
(the GitHub Actions release workflow does exactly that).
"""

from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pawlock import __version__  # noqa: E402


def machine() -> str:
    arch = platform.machine().lower()
    return {"amd64": "x64", "x86_64": "x64", "aarch64": "arm64"}.get(arch, arch)


def os_name() -> str:
    return {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")


def ensure_icons() -> None:
    if not (ROOT / "assets" / "pawlock.ico").exists() or not (ROOT / "assets" / "pawlock.png").exists():
        subprocess.check_call([sys.executable, str(ROOT / "scripts" / "make_icons.py")])


def run_pyinstaller() -> Path:
    import PyInstaller.__main__

    PyInstaller.__main__.run([str(ROOT / "pawlock.spec"), "--noconfirm", "--clean",
                              "--distpath", str(ROOT / "dist"), "--workpath", str(ROOT / "build")])
    product = {
        "windows": ROOT / "dist" / "PawLock.exe",
        "macos": ROOT / "dist" / "PawLock.app",
        "linux": ROOT / "dist" / "PawLock",
    }[os_name()]
    if not product.exists():
        raise SystemExit(f"Build finished but {product} is missing")
    return product


def archive(product: Path) -> Path:
    base = ROOT / "dist" / f"PawLock-{__version__}-{os_name()}-{machine()}"
    if os_name() == "macos":
        # ditto keeps the app bundle's symlinks and code signature intact.
        # (Not base.with_suffix(): the version's dots would be eaten as a suffix.)
        target = Path(str(base) + ".zip")
        subprocess.check_call(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(product), str(target)])
    elif os_name() == "linux":
        target = Path(str(base) + ".tar.gz")
        with tarfile.open(target, "w:gz") as tar:
            tar.add(product, arcname="PawLock")  # tar preserves the executable bit
    else:
        target = Path(shutil.make_archive(str(base), "zip", root_dir=product.parent, base_dir=product.name))
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--archive", action="store_true", help="also create a .zip/.tar.gz for distribution")
    args = parser.parse_args()

    ensure_icons()
    product = run_pyinstaller()
    print(f"\nBuilt {product}")
    if args.archive:
        print(f"Packed {archive(product)}")


if __name__ == "__main__":
    main()
