"""Shared state between Flask and the automation engine."""

from __future__ import annotations

import atexit
import threading
import time
from pathlib import Path

import yaml
from loguru import logger


class AppState:
    """Holds references to the automation Application instance and config/db."""

    def __init__(self, config, db):
        self.config = config
        self.db = db
        self._application = None
        self._engine_thread = None
        self._lock = threading.Lock()
        self._config_lock = threading.Lock()
        self._engine_status = "stopped"  # stopped | starting | running | stopping
        self._startup_error = None

        self.base_dir = config.base_dir
        self.settings_path = self.base_dir / "config" / "settings.yaml"
        self.accounts_path = self.base_dir / "config" / "accounts.yaml"
        self.log_dir = self.base_dir / "data" / "logs"

    @property
    def application(self):
        with self._lock:
            return self._application

    @property
    def engine_running(self) -> bool:
        return self.engine_status == "running"

    @property
    def engine_status(self) -> str:
        with self._lock:
            # Self-heal: detect _ready signal that the watcher may have missed
            # (race condition, premature timeout, etc.)
            if (
                self._engine_status in ("starting", "stopped")
                and self._application is not None
                and self._application._ready.is_set()
            ):
                self._engine_status = "running"
                self._startup_error = None

            # Detect dead engine thread — status should be "stopped"
            if (
                self._engine_status in ("starting", "running")
                and self._engine_thread is not None
                and not self._engine_thread.is_alive()
                and self._application is None
            ):
                self._engine_status = "stopped"

            return self._engine_status

    @property
    def startup_error(self) -> str | None:
        with self._lock:
            return self._startup_error

    def start_engine(self) -> tuple[bool, str]:
        with self._lock:
            if self._engine_status == "running":
                return False, "Engine is already running"
            if self._engine_status == "starting":
                return False, "Engine is still starting up"
            # Guard: don't spawn a second engine thread if the old one is
            # still alive (e.g. premature watcher timeout set status to
            # "stopped" while app.run() was still executing).
            if self._engine_thread is not None and self._engine_thread.is_alive():
                if self._application is not None:
                    return False, "Engine thread is still active"
            self._engine_status = "starting"
            self._startup_error = None

        def _run():
            try:
                # Import here to avoid loading Selenium at Flask startup
                import sys
                sys.path.insert(0, str(self.base_dir))
                from main import Application

                app = Application(quiet=True)
                with self._lock:
                    self._application = app

                # Watch for the Application._ready event.  Polls every 2s
                # instead of a single blocking wait so we can also detect
                # early thread death (engine crashed before _ready was set).
                def _watch_ready():
                    deadline = time.monotonic() + 660  # setup_timeout(600) + 60s buffer
                    while time.monotonic() < deadline:
                        if app._ready.wait(timeout=2):
                            with self._lock:
                                if self._engine_status == "starting":
                                    self._engine_status = "running"
                            return
                        # Early exit: if the engine thread already died, stop waiting.
                        with self._lock:
                            if self._engine_status == "stopped":
                                return
                    # Timed out — only set error if no other error was recorded.
                    with self._lock:
                        if self._engine_status == "starting":
                            self._engine_status = "stopped"
                            if not self._startup_error:
                                self._startup_error = (
                                    "Engine startup timed out (660s). "
                                    "Check logs for details."
                                )

                watcher = threading.Thread(
                    target=_watch_ready, daemon=True, name="engine-ready-watcher"
                )
                watcher.start()

                # This blocks until shutdown (or raises on failure)
                app.run()
            except Exception as e:
                is_runtime = isinstance(e, RuntimeError)
                label = "Engine startup failed" if is_runtime else "Engine error"
                logger.error(f"{label}: {e}")
                with self._lock:
                    self._startup_error = str(e)
                    self._engine_status = "stopped"
            finally:
                with self._lock:
                    self._application = None
                    if self._engine_status not in ("stopped",):
                        self._engine_status = "stopped"

        self._engine_thread = threading.Thread(
            target=_run, daemon=True, name="automation-engine"
        )
        self._engine_thread.start()

        # Ensure the engine shuts down cleanly when the process exits (Ctrl+C)
        atexit.register(self._atexit_stop)

        # Wait briefly for startup or failure
        time.sleep(1)
        return True, "Engine starting..."

    def _atexit_stop(self) -> None:
        """Called by atexit — stop browser profiles and scheduler on process exit."""
        with self._lock:
            app = self._application
        if app is not None:
            try:
                app.shutdown()
            except Exception:
                pass

    def stop_engine(self) -> tuple[bool, str]:
        with self._lock:
            app = self._application
            if app is None:
                return False, "Engine is not running"
            self._engine_status = "stopping"

        try:
            app.shutdown()
        except Exception as e:
            logger.error(f"Error stopping engine: {e}")

        return True, "Engine stopping..."

    def reload_config(self):
        from src.core.config_loader import ConfigLoader
        with self._config_lock:
            self.config = ConfigLoader()

    def save_settings(self, data: dict):
        with self._config_lock:
            content = "# Twitter Multi-Account Automation - Global Settings\n"
            content += "# Modified via BunnyTweets Dashboard\n\n"
            content += yaml.dump(data, default_flow_style=False, sort_keys=False)
            self.settings_path.write_text(content, encoding="utf-8")
        self.reload_config()

    def save_accounts(self, data: dict):
        with self._config_lock:
            content = "# Twitter Multi-Account Automation - Account Configuration\n"
            content += "# Modified via BunnyTweets Dashboard\n\n"
            content += yaml.dump(data, default_flow_style=False, sort_keys=False)
            self.accounts_path.parent.mkdir(parents=True, exist_ok=True)
            self.accounts_path.write_text(content, encoding="utf-8")
        self.reload_config()
