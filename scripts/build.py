"""Build a standalone PawLock app with PyInstaller (no Python needed to run it).

    python scripts/build.py              # build for the current OS
    python scripts/build.py --archive    # ...and pack it (.zip / .tar.gz)
    python scripts/build.py --installer  # ...and make the friendly installer

Output:
    Windows  dist/PawLock.exe            (single file, no console window)
             dist/PawLock-Setup-<v>.exe  (--installer: Next-Next-Finish installer;
                                          needs Inno Setup 6, https://jrsoftware.org)
    macOS    dist/PawLock.app            (menu-bar app, no Dock icon)
             dist/PawLock-<v>-macos-<arch>.dmg  (--installer: drag-to-Applications)
    Linux    dist/PawLock                (single file)

PyInstaller cannot cross-compile: build on each OS you want to ship for
(the GitHub Actions release workflow does exactly that).
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import time
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


def find_inno_setup() -> Path:
    """Locate Inno Setup's command-line compiler (ISCC.exe)."""
    found = shutil.which("iscc")
    candidates = [Path(found)] if found else []
    for base in (os.environ.get("PROGRAMFILES(X86)"), os.environ.get("PROGRAMFILES"),
                 os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs")):
        if base:
            candidates.append(Path(base) / "Inno Setup 6" / "ISCC.exe")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise SystemExit(
        "Inno Setup 6 is needed to build the Windows installer.\n"
        "Install it from https://jrsoftware.org/isdl.php (or: winget install JRSoftware.InnoSetup) "
        "and run this again."
    )


def windows_installer() -> Path:
    """Compile packaging/windows/PawLock.iss into dist/PawLock-Setup-<version>.exe."""
    script = ROOT / "packaging" / "windows" / "PawLock.iss"
    subprocess.check_call([str(find_inno_setup()), f"/DMyAppVersion={__version__}", "/Q", str(script)])
    target = ROOT / "dist" / f"PawLock-Setup-{__version__}.exe"
    if not target.exists():
        raise SystemExit(f"Inno Setup finished but {target} is missing")
    return target


def mac_disk_image(product: Path) -> Path:
    """A .dmg showing PawLock next to an Applications shortcut: drag one onto the other."""
    staging = ROOT / "build" / "dmg"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    subprocess.check_call(["ditto", str(product), str(staging / "PawLock.app")])
    (staging / "Applications").symlink_to("/Applications")
    target = ROOT / "dist" / f"PawLock-{__version__}-macos-{machine()}.dmg"
    for attempt in range(3):  # hdiutil is occasionally "busy" on CI machines.
        try:
            subprocess.check_call(["hdiutil", "create", "-volname", "PawLock", "-srcfolder", str(staging),
                                   "-ov", "-format", "UDZO", str(target)])
            break
        except subprocess.CalledProcessError:
            if attempt == 2:
                raise
            time.sleep(5)
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--archive", action="store_true", help="also create a .zip/.tar.gz for distribution")
    parser.add_argument("--installer", action="store_true",
                        help="also create the installer (Windows: setup .exe, macOS: .dmg)")
    args = parser.parse_args()

    ensure_icons()
    product = run_pyinstaller()
    print(f"\nBuilt {product}")
    if args.archive:
        print(f"Packed {archive(product)}")
    if args.installer:
        if os_name() == "windows":
            print(f"Installer {windows_installer()}")
        elif os_name() == "macos":
            print(f"Disk image {mac_disk_image(product)}")
        else:
            print("No installer format for Linux; share the .tar.gz from --archive.")


if __name__ == "__main__":
    main()
