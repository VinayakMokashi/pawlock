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
import logging
import queue
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import __version__, autostart, paths
from .backends import BackendError, create_backend
from .config import (
    SIMPLE_HOTKEY_PREFIX,
    Config,
    apply_simple_settings,
    load_config,
    simple_settings,
    update_config_file,
)
from .detector import CatDetector
from .engine import (
    REASON_MANUAL,
    REASON_SAFETY,
    REASON_SHUTDOWN,
    REASON_STARTUP,
    LockEngine,
    StateChange,
)
from .feedback import FeedbackHub, describe, is_quiet_lock
from .feedback.sound import SoundPlayer
from .hotkey import Hotkey
from .idle import make_idle_source
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
    away_minutes: Optional[float] = None  # 0 turns away mode off for this run
    first_run: bool = False               # show the welcome window


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
        # Away-mode locks are silent; these drive the banner shown when
        # someone touches the computer while it's quietly locked.
        self._quiet_lock_text: Optional[Tuple[str, str]] = None
        self._quiet_poked_at: Optional[float] = None
        # The PawLock window lives on the Tk (main) thread; other threads
        # queue calls for it here.
        self._ui_root: Any = None
        self._ui_calls: queue.Queue[Callable[[], None]] = queue.Queue()
        self._window: Any = None
        self._window_host = False

        opts = self.options
        if opts.sensitivity:
            config.sensitivity = opts.sensitivity  # In-memory only; never saved.
        if opts.away_minutes is not None:
            config.away_lock = opts.away_minutes > 0  # In-memory only; never saved.
            config.away_lock_minutes = opts.away_minutes or config.away_lock_minutes
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
            away_seconds=config.away_seconds(),
            idle_source=make_idle_source(),
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
            # Started again while running (double-clicked, Start menu...):
            # ask the running PawLock to show its window instead.
            if not _ask_running_instance_to_show():
                show_message("PawLock is already running. Look for the paw near the clock.")
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
        want_overlay = _pick(self.options.overlay, self.config.overlay)
        # The PawLock window uses Tk too. On macOS Tk is only used when the
        # banner is switched on (see docs/TROUBLESHOOTING.md).
        want_window = sys.platform != "darwin" or want_overlay
        root = None
        if want_overlay or want_window:
            try:
                import tkinter as tk

                root = tk.Tk()
                root.withdraw()
                root.title("PawLock")
            except Exception:
                log.warning("Tk unavailable: no banner or window; continuing without them", exc_info=True)
                root = None
        if root is not None and want_overlay:
            try:
                from .feedback.overlay import Overlay

                self.feedback.overlay = Overlay(root, self.config.overlay_position)
            except Exception:
                log.warning("On-screen banner unavailable; continuing without it", exc_info=True)
        self._ui_root = root
        self._window_host = root is not None and want_window

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
        if self.options.first_run:
            self._welcome()
        else:
            self._announce_startup()

        if root is not None:
            root.after(100, self._ui_pump)
            root.mainloop()
        elif tray_owns_main_thread and tray is not None:
            tray.run_blocking()
        else:
            while not self._stopping.wait(0.2):
                pass

    def _ui_pump(self) -> None:
        """Runs on the Tk thread every 100 ms: queued UI calls, and shutdown.

        Also gives Python a chance to run signal handlers while Tk is in C.
        """
        root = self._ui_root
        if self._stopping.is_set():
            root.quit()
            return
        while True:
            try:
                call = self._ui_calls.get_nowait()
            except queue.Empty:
                break
            try:
                call()
            except Exception:
                log.exception("Window action failed")
        root.after(100, self._ui_pump)

    def _welcome(self) -> None:
        """First run: open the window on the "How to use" page."""
        try:
            paths.welcome_marker_path().parent.mkdir(parents=True, exist_ok=True)
            paths.welcome_marker_path().write_text(__version__, encoding="utf-8")
        except OSError:
            pass
        if self._window_host:
            self.open_window("howto", welcome=True)
        else:
            self._announce_startup()
        if sys.platform == "win32" and paths.is_frozen() and self.feedback.tray is not None:
            from .feedback.tray import show_tray_icon_next_to_clock

            threading.Thread(
                target=show_tray_icon_next_to_clock, args=(sys.executable,), name="tray-promote", daemon=True
            ).start()

    def open_window(self, tab: str = "howto", welcome: bool = False) -> None:
        """Show the PawLock window (safe from any thread)."""
        if not self._window_host:
            if tab == "settings":
                self.open_settings()
            else:
                self.open_help()
            return
        self._ui_calls.put(lambda: self._show_window(tab, welcome))

    def _show_window(self, tab: str, welcome: bool) -> None:
        if self._window is None:
            from .feedback.window import build_window

            self._window = build_window(self._ui_root, self)
            if self._window is None:
                self.open_settings()
                return
        self._window.show(tab, welcome)

    def _announce_startup(self) -> None:
        how = f"Lock / unlock: press {self.hotkey.display()}."
        detail = "Cat detection is on." if self.engine.auto_detect else "Cat detection is off."
        if self.engine.away_seconds > 0:
            detail += f" Locks itself after {self.config.away_lock_minutes:g} min away."
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
                self._show_banner_if_touched()
                self._check_show_request()
                self.engine.tick()
            except Exception:
                log.exception("Controller error; releasing the lock to be safe")
                self.engine.force_unlock(REASON_SAFETY, "PawLock hit an internal error")

    def _check_show_request(self) -> None:
        """Another PawLock was started: it left a note asking us to show the window."""
        if not self._window_host:
            return  # Leave the note: the other copy will tell the user we're running.
        request = paths.show_request_path()
        if request.exists():
            try:
                request.unlink()
            except OSError:
                return
            self.open_window()

    def _show_banner_if_touched(self) -> None:
        """During a quiet (away-mode) lock, show the banner when input is blocked."""
        if self._quiet_lock_text is None or not self.engine.locked:
            return
        blocked = self.engine.last_blocked_at
        if blocked is None or (self._quiet_poked_at is not None and blocked - self._quiet_poked_at < 3.0):
            return
        first = self._quiet_poked_at is None
        self._quiet_poked_at = blocked
        self.feedback.poke(*self._quiet_lock_text, first=first)

    def _apply(self, change: StateChange) -> None:
        detail = f": {change.detail}" if change.detail else ""
        self._quiet_poked_at = None
        if change.locked:
            log.info("LOCKED (%s%s)%s", change.reason, detail, " [dry run]" if change.dry_run else "")
            if change.dry_run:
                self._dry_run_release_at = time.monotonic() + DRY_RUN_HOLD_SECONDS
            self._quiet_lock_text = (
                describe(change, self.hotkey.display(), self.engine.unlock_phrase) if is_quiet_lock(change) else None
            )
        else:
            self._quiet_lock_text = None
            log.info("Unlocked (%s%s)%s", change.reason, detail, f" {change.summary}" if change.summary else "")
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

    def away_text(self) -> str:
        return f"Lock when I'm away ({self.config.away_lock_minutes:g} min)"

    def away_lock_enabled(self) -> bool:
        return self.engine.away_seconds > 0

    def set_away_lock(self, enabled: bool) -> None:
        self.config.away_lock = enabled
        self.engine.reconfigure(away_seconds=self.config.away_seconds())
        self._persist("away_lock", enabled)
        log.info("Away mode %s", "enabled" if enabled else "disabled")
        self._refresh_tray()

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

    # -- the PawLock window -------------------------------------------------

    def window_available(self) -> bool:
        return self._window_host

    def open_home(self) -> None:
        self.open_window("howto")

    def open_settings_window(self) -> None:
        self.open_window("settings")

    def open_help(self) -> None:
        import webbrowser

        from .feedback.window import HELP_URL

        webbrowser.open(HELP_URL)

    def shortcut_prefix(self) -> str:
        """``"Ctrl + Alt + Shift"`` (``"Control + Option + Shift"`` on a Mac)."""
        return Hotkey.parse(SIMPLE_HOTKEY_PREFIX + "a").display().rsplit(" + ", 1)[0]

    def current_settings(self) -> Dict[str, Any]:
        values = simple_settings(self.config)
        values["autostart"] = self.autostart_enabled()
        return values

    def save_settings(self, values: Dict[str, Any]) -> List[str]:
        """Apply the Settings tab. Returns friendly error messages ([] on success)."""
        changes, errors = apply_simple_settings(self.config, values)
        if errors:
            return errors
        if changes:
            try:
                update_config_file(self.config_file, changes)
            except (OSError, ValueError) as exc:
                log.error("Could not save settings: %s", exc)
                return [f"Couldn't save the settings file ({exc})."]
            log.info("Settings changed in the window: %s", ", ".join(sorted(changes)))
        wanted = bool(values.get("autostart", self.autostart_enabled()))
        if self.autostart_supported() and wanted != self.autostart_enabled():
            self.set_autostart(wanted)
        self.reload_settings(announce=False)
        return []

    def reload_settings(self, announce: bool = True) -> None:
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
            away_seconds=config.away_seconds(),
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
        if not announce:
            return
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
            update_config_file(self.config_file, {key: value})
            setattr(self.config, key, value)
        except (OSError, ValueError) as exc:
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


def _ask_running_instance_to_show(timeout: float = 2.5) -> bool:
    """Leave a note for the running PawLock to open its window; True if it did."""
    request = paths.show_request_path()
    try:
        request.parent.mkdir(parents=True, exist_ok=True)
        request.write_text("show", encoding="utf-8")
    except OSError:
        return False
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not request.exists():
            return True  # Picked up: the window is opening.
        time.sleep(0.1)
    try:
        request.unlink()
    except OSError:
        pass
    return False


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
