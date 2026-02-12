"""Shared state between Flask and the automation engine."""

from __future__ import annotations

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
        with self._lock:
            return self._engine_status == "running"

    @property
    def engine_status(self) -> str:
        with self._lock:
            return self._engine_status

    @property
    def startup_error(self) -> str | None:
        with self._lock:
            return self._startup_error

    def start_engine(self) -> tuple[bool, str]:
        with self._lock:
            if self._engine_status in ("running", "starting"):
                return False, "Engine is already running"
            self._engine_status = "starting"
            self._startup_error = None

        def _run():
            try:
                # Import here to avoid loading Selenium at Flask startup
                import sys
                sys.path.insert(0, str(self.base_dir))
                from main import Application

                app = Application()
                with self._lock:
                    self._application = app

                # Watch for the Application._ready event so we only mark
                # "running" after accounts are set up and the scheduler starts.
                def _watch_ready():
                    if app._ready.wait(timeout=300):
                        with self._lock:
                            if self._engine_status == "starting":
                                self._engine_status = "running"

                watcher = threading.Thread(
                    target=_watch_ready, daemon=True, name="engine-ready-watcher"
                )
                watcher.start()

                # This blocks until shutdown
                app.run()
            except Exception as e:
                logger.error(f"Engine startup failed: {e}")
                with self._lock:
                    self._startup_error = str(e)
            finally:
                with self._lock:
                    self._application = None
                    self._engine_status = "stopped"

        self._engine_thread = threading.Thread(
            target=_run, daemon=True, name="automation-engine"
        )
        self._engine_thread.start()

        # Wait briefly for startup or failure
        time.sleep(1)
        return True, "Engine starting..."

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
            self.accounts_path.write_text(content, encoding="utf-8")
        self.reload_config()
