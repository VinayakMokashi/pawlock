"""Wires everything together and runs the threads.

Threads
-------
==============  ==============================================================
main            UI: the Tk banner's event loop (or the macOS tray, or a wait)
keyboard hook   OS keyboard hook -> ``engine.handle_key``          (pynput)
mouse hook      OS mouse hook -> ``engine.handle_mouse_*``         (pynput)
controller      applies lock/unlock: listener swap, feedback, logging, ticks
watchdog        independent safety checks, once a second
tray            system tray icon (Windows/Linux)
==============  ==============================================================

The hooks only ever talk to the engine, and the engine only *enqueues*
state changes. Everything slow happens on the controller thread, so a slow
sound card or a busy UI can never stall the input hooks.
"""

from __future__ import annotations

import atexit
import json
import logging
import queue
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from . import __version__, autostart, paths
from .backends import BackendError, create_backend
from .config import Config, load_config
from .detector import CatDetector
from .engine import (
    REASON_MANUAL,
    REASON_SAFETY,
    REASON_SHUTDOWN,
    REASON_STARTUP,
    LockEngine,
    StateChange,
)
from .feedback import FeedbackHub
from .feedback.sound import SoundPlayer
from .instance import InstanceGuard
from .messages import show_message
from .safety import Watchdog, install_crash_guards, install_signal_handlers, run_with_timeout

log = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_ALREADY_RUNNING = 3
EXIT_BACKEND_FAILED = 4

#: How long a dry-run "lock" lasts before PawLock goes back to watching.
DRY_RUN_HOLD_SECONDS = 4.0


@dataclass
class RunOptions:
    """Command-line overrides. ``None`` means "use the settings file"."""

    dry_run: bool = False
    start_locked: Optional[bool] = None
    practice_seconds: float = 0.0
    tray: Optional[bool] = None
    overlay: Optional[bool] = None
    sound: Optional[bool] = None
    auto_detect: Optional[bool] = None
    sensitivity: Optional[str] = None
    max_lock_minutes: Optional[float] = None


def _pick(override: Any, configured: Any) -> Any:
    return configured if override is None else override


class PawLockApp:
    def __init__(self, config: Config, config_file: Path, options: Optional[RunOptions] = None) -> None:
        self.config = config
        self.config_file = config_file
        self.options = options or RunOptions()

        self._events: queue.Queue[StateChange] = queue.Queue()
        self._stopping = threading.Event()
        self._heartbeat = time.monotonic()
        self._cleanup_lock = threading.Lock()
        self._cleaned_up = False
        self._dry_run_release_at: Optional[float] = None

        opts = self.options
        if opts.sensitivity:
            config.sensitivity = opts.sensitivity  # In-memory only; never saved.
        self.hotkey = config.parsed_hotkey()
        self.detector = CatDetector(config.detector_settings())
        self.engine = LockEngine(
            self.hotkey,
            unlock_phrase=config.unlock_phrase,
            detector=self.detector,
            auto_detect=_pick(opts.auto_detect, config.auto_detect),
            lock_mouse=config.lock_mouse,
            stale_key_seconds=config.stale_key_seconds,
            cooldown_seconds=config.cooldown_seconds,
            dry_run=opts.dry_run,
            on_change=self._events.put,  # Must not block: the hooks call this.
        )
        self.backend = create_backend(self.engine, config.backend)
        self.feedback = FeedbackHub(
            SoundPlayer(_pick(opts.sound, config.sound)), notifications=config.notifications
        )
        self.instance = InstanceGuard(paths.pid_path())
        self.watchdog: Optional[Watchdog] = None
        self._practice_active = opts.practice_seconds > 0

    # ------------------------------------------------------------------
    # Main entry
    # ------------------------------------------------------------------

    def run(self) -> int:
        if not self.instance.acquire():
            show_message("PawLock is already running (look for the paw in your system tray).")
            return EXIT_ALREADY_RUNNING
        try:
            install_crash_guards(self._on_crash)
            install_signal_handlers(self._on_signal)
            atexit.register(self._cleanup)
            _enable_dpi_awareness()

            for advice in self.hotkey.warnings():
                log.warning("Hotkey %s: %s", self.hotkey, advice)

            try:
                self.backend.start()
            except BackendError as exc:
                log.error("Could not start input hooks: %s", exc)
                show_message(f"PawLock could not start.\n\n{exc}", error=True)
                return EXIT_BACKEND_FAILED

            log.info(
                "PawLock %s running (backend=%s, hotkey=%s, auto-detect=%s/%s, dry-run=%s)",
                __version__, self.backend.name, self.hotkey, self.engine.auto_detect,
                self.config.sensitivity, self.engine.dry_run,
            )

            threading.Thread(target=self._controller_loop, name="controller", daemon=True).start()
            self.watchdog = Watchdog(
                engine=self.engine,
                backend=self.backend,
                heartbeat=lambda: self._heartbeat,
                controller_timeout=self.config.watchdog_seconds,
                max_lock_seconds=self._max_lock_seconds(),
            )
            self.watchdog.start()

            if self._practice_active:
                self.engine.lock(
                    REASON_STARTUP,
                    f"Practice mode: you'll be unlocked automatically after "
                    f"{self.options.practice_seconds:.0f} seconds",
                )
            elif _pick(self.options.start_locked, self.config.start_locked):
                self.engine.lock(REASON_STARTUP)

            self._run_ui()
            return EXIT_OK
        finally:
            self._cleanup()

    def _max_lock_seconds(self) -> float:
        if self._practice_active:
            return self.options.practice_seconds
        return 60.0 * _pick(self.options.max_lock_minutes, self.config.max_lock_minutes)

    # ------------------------------------------------------------------
    # UI hosting (main thread)
    # ------------------------------------------------------------------

    def _run_ui(self) -> None:
        root = None
        if _pick(self.options.overlay, self.config.overlay):
            try:
                import tkinter as tk

                from .feedback.overlay import Overlay

                root = tk.Tk()
                root.withdraw()
                root.title("PawLock")
                self.feedback.overlay = Overlay(root, self.config.overlay_position)
            except Exception:
                log.warning("On-screen banner unavailable; continuing without it", exc_info=True)
                root = None

        tray = None
        if _pick(self.options.tray, self.config.tray):
            try:
                from .feedback.tray import TrayIcon

                tray = TrayIcon(self)
                self.feedback.tray = tray
            except Exception:
                log.warning("Tray icon unavailable; continuing without it", exc_info=True)

        tray_owns_main_thread = False
        if tray is not None:
            if sys.platform == "darwin":
                # AppKit insists on the main thread. If Tk is there, share it.
                if root is not None:
                    try:
                        tray.run_detached()
                    except Exception:
                        log.warning("Could not attach the menu-bar icon", exc_info=True)
                else:
                    tray_owns_main_thread = True
            else:
                tray.run_in_thread()

        self._refresh_tray()
        self._announce_startup()

        if root is not None:
            root.after(200, self._watch_for_stop, root)
            root.mainloop()
        elif tray_owns_main_thread and tray is not None:
            tray.run_blocking()
        else:
            while not self._stopping.wait(0.2):
                pass

    def _watch_for_stop(self, root: Any) -> None:
        # Also gives Python a chance to run signal handlers while Tk is in C.
        if self._stopping.is_set():
            root.quit()
        else:
            root.after(200, self._watch_for_stop, root)

    def _announce_startup(self) -> None:
        how = f"Lock / unlock: press {self.hotkey.display()}."
        detail = "Cat detection is on." if self.engine.auto_detect else "Cat detection is off."
        if self.engine.dry_run:
            detail = "DRY RUN: nothing will be blocked. " + detail
        if self.feedback.overlay is not None and not self.engine.locked:
            self.feedback.overlay.flash("PawLock is on guard", f"{how}\n{detail}", "unlocked", 3500)
        else:
            self.feedback.notify(f"PawLock is on guard. {how} {detail}")

    # ------------------------------------------------------------------
    # Controller thread
    # ------------------------------------------------------------------

    def _controller_loop(self) -> None:
        while not self._stopping.is_set():
            self._heartbeat = time.monotonic()
            try:
                change = self._events.get(timeout=0.25)
            except queue.Empty:
                change = None
            try:
                if change is not None:
                    self._apply(change)
                self._release_dry_run_lock()
                self.engine.tick()
            except Exception:
                log.exception("Controller error; releasing the lock to be safe")
                self.engine.force_unlock(REASON_SAFETY, "PawLock hit an internal error")

    def _apply(self, change: StateChange) -> None:
        detail = f": {change.detail}" if change.detail else ""
        if change.locked:
            log.info("LOCKED (%s%s)%s", change.reason, detail, " [dry run]" if change.dry_run else "")
            if change.dry_run:
                self._dry_run_release_at = time.monotonic() + DRY_RUN_HOLD_SECONDS
        else:
            log.info("Unlocked (%s%s)", change.reason, detail)
            if self._practice_active:
                self._practice_active = False
                if self.watchdog is not None:
                    self.watchdog.max_lock_seconds = self._max_lock_seconds()

        self.backend.on_state_change(change.locked)  # Listener swap (Linux).
        self.feedback.state_changed(
            change,
            hotkey_text=self.hotkey.display(),
            phrase=self.engine.unlock_phrase,
            auto_detect=self.engine.auto_detect,
            tooltip=self.status_text(),
        )

    def _release_dry_run_lock(self) -> None:
        if self._dry_run_release_at is not None and time.monotonic() >= self._dry_run_release_at:
            self._dry_run_release_at = None
            if self.engine.locked and self.engine.dry_run:
                self.engine.unlock(REASON_MANUAL, "dry run")

    # ------------------------------------------------------------------
    # Tray actions (called from the tray thread)
    # ------------------------------------------------------------------

    def status_text(self) -> str:
        if self.engine.locked:
            text = "PawLock: LOCKED"
        elif self.engine.auto_detect:
            text = "PawLock: watching for cats"
        else:
            text = "PawLock: unlocked (cat detection off)"
        return text + (" [dry run]" if self.engine.dry_run else "")

    def hotkey_text(self) -> str:
        return self.hotkey.display()

    def is_locked(self) -> bool:
        return self.engine.locked

    def lock_now(self) -> None:
        self.engine.lock(REASON_MANUAL)

    def unlock_now(self) -> None:
        self.engine.unlock(REASON_MANUAL)

    def practice_lock(self, seconds: float = 30.0) -> None:
        """Lock for a short session that releases itself: a safe way to try the hotkey."""
        if self.engine.locked:
            return
        self._practice_active = True
        self.options.practice_seconds = seconds
        if self.watchdog is not None:
            self.watchdog.max_lock_seconds = seconds
        self.engine.lock(
            REASON_MANUAL, f"Practice: you'll be unlocked automatically after {seconds:.0f} seconds"
        )

    def auto_detect_enabled(self) -> bool:
        return self.engine.auto_detect

    def set_auto_detect(self, enabled: bool) -> None:
        self.engine.auto_detect = enabled
        self._persist("auto_detect", enabled)
        log.info("Cat detection %s", "enabled" if enabled else "disabled")
        self._refresh_tray()

    def sound_enabled(self) -> bool:
        return self.feedback.sound.enabled

    def set_sound(self, enabled: bool) -> None:
        self.feedback.sound.enabled = enabled
        self._persist("sound", enabled)
        self._refresh_tray()

    def autostart_supported(self) -> bool:
        return autostart.is_supported()

    def autostart_enabled(self) -> bool:
        try:
            return autostart.is_enabled()
        except OSError:
            return False

    def set_autostart(self, enabled: bool) -> None:
        try:
            autostart.set_enabled(enabled)
            log.info("Start at login %s", "enabled" if enabled else "disabled")
        except OSError as exc:
            log.error("Could not change start-at-login: %s", exc)
            self.feedback.notify(f"Could not change start-at-login: {exc}")
        self._refresh_tray()

    def open_settings(self) -> None:
        if not self.config_file.exists():
            from .config import save_config

            save_config(self.config, self.config_file)
        paths.open_in_default_app(self.config_file)

    def open_logs(self) -> None:
        paths.log_dir().mkdir(parents=True, exist_ok=True)
        paths.open_in_default_app(paths.log_dir())

    def reload_settings(self) -> None:
        config, warnings = load_config(self.config_file)
        for warning in warnings:
            log.warning("Settings: %s", warning)
        self.config = config
        self.hotkey = config.parsed_hotkey()
        self.engine.reconfigure(
            hotkey=self.hotkey,
            unlock_phrase=config.unlock_phrase,
            lock_mouse=config.lock_mouse,
            cooldown_seconds=config.cooldown_seconds,
            stale_key_seconds=config.stale_key_seconds,
            detector_settings=config.detector_settings(),
        )
        self.engine.auto_detect = config.auto_detect
        self.feedback.sound.enabled = config.sound
        self.feedback.notifications = config.notifications
        if self.watchdog is not None:
            self.watchdog.controller_timeout = config.watchdog_seconds
            if not self._practice_active:
                self.watchdog.max_lock_seconds = 60.0 * config.max_lock_minutes
        logging.getLogger("pawlock").setLevel(config.log_level)
        for advice in self.hotkey.warnings():
            log.warning("Hotkey %s: %s", self.hotkey, advice)
        log.info("Settings reloaded (hotkey=%s, sensitivity=%s)", self.hotkey, config.sensitivity)
        self._refresh_tray()
        message = "Settings reloaded."
        if warnings:
            message += f" {len(warnings)} problem(s) found; defaults were used (see the log)."
        message += " Tray, banner and backend changes apply after a restart."
        if self.feedback.overlay is not None:
            self.feedback.overlay.flash("Settings reloaded", message, "unlocked", 3000)
        else:
            self.feedback.notify(message)

    def quit(self) -> None:
        self.request_shutdown("tray menu")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _refresh_tray(self) -> None:
        self.feedback.refresh_tray(
            self.engine.locked, self.engine.dry_run, self.engine.auto_detect, self.status_text()
        )

    def _persist(self, key: str, value: Any) -> None:
        """Save one setting the user changed from the tray, leaving the rest of the file alone."""
        try:
            raw = json.loads(self.config_file.read_text(encoding="utf-8-sig"))
            if not isinstance(raw, dict):
                raise ValueError("not a JSON object")
        except FileNotFoundError:
            raw = {}
        except (OSError, ValueError) as exc:
            log.warning("Not saving %s: the settings file can't be read (%s)", key, exc)
            return
        raw[key] = value
        try:
            tmp = self.config_file.with_name(self.config_file.name + ".tmp")
            tmp.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
            tmp.replace(self.config_file)
            setattr(self.config, key, value)
        except OSError as exc:
            log.warning("Could not save %s: %s", key, exc)

    # ------------------------------------------------------------------
    # Shutdown & safety callbacks
    # ------------------------------------------------------------------

    def request_shutdown(self, reason: str) -> None:
        """Ask PawLock to exit. Safe from any thread and from signal handlers."""
        if self._stopping.is_set():
            return
        log.info("Shutting down (%s)", reason)
        self.engine.force_unlock(REASON_SHUTDOWN)  # Input back *first*.
        self._stopping.set()
        if self.feedback.overlay is not None:
            self.feedback.overlay.close()
        if self.feedback.tray is not None:
            self.feedback.tray.stop()

    def _on_signal(self, name: str) -> None:
        self.request_shutdown(f"signal {name}")

    def _on_crash(self, reason: str) -> None:
        self.engine.force_unlock(REASON_SAFETY, f"PawLock hit an unexpected error ({reason})")

    def _cleanup(self) -> None:
        with self._cleanup_lock:
            if self._cleaned_up:
                return
            self._cleaned_up = True
        self._stopping.set()
        self.engine.force_unlock(REASON_SHUTDOWN)
        if self.watchdog is not None:
            self.watchdog.stop()
        if not run_with_timeout(self.backend.stop, 3.0, "stop-hooks"):
            log.error("Input hooks did not stop cleanly (they die with the process anyway)")
        if self.feedback.tray is not None:
            self.feedback.tray.stop()
        self.instance.release()
        log.info("PawLock stopped")


def _enable_dpi_awareness() -> None:
    """Crisp banner text on high-DPI Windows displays."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # Per-monitor aware.
        except (AttributeError, OSError):
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:  # pragma: no cover - cosmetic only
        pass
