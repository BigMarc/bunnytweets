#!/usr/bin/env python3
"""BunnyTweets – Twitter Multi-Account Automation System.

Usage:
    python main.py              Start the automation (all enabled accounts)
    python main.py --web        Launch the web dashboard (http://localhost:8080)
    python main.py --setup      Interactive first-time setup wizard
    python main.py --add-account  Add a new Twitter account interactively
    python main.py --status     Show account status dashboard
    python main.py --test       Run a connectivity test against the browser provider
"""

from __future__ import annotations

import argparse
import signal
import sys
import time
from datetime import datetime
from functools import partial
from pathlib import Path

from loguru import logger


class Application:
    """Main application that wires all components together."""

    def __init__(self):
        # Deferred imports so that --setup/--add-account work without
        # heavy dependencies like selenium being installed.
        from src.core.config_loader import ConfigLoader
        from src.core.logger import setup_logging, get_account_logger
        from src.core.database import Database
        from src.dolphin_anty.profile_manager import ProfileManager
        from src.google_drive.drive_client import DriveClient
        from src.google_drive.file_monitor import FileMonitor
        from src.scheduler.job_manager import JobManager
        from src.scheduler.queue_handler import QueueHandler

        self.config = ConfigLoader()
        self.db = Database(str(self.config.resolve_path(self.config.database_path)))

        # Logging
        log_cfg = self.config.logging
        setup_logging(
            level=log_cfg.get("level", "INFO"),
            retention_days=log_cfg.get("retention_days", 30),
            log_dir=str(self.config.resolve_path("data/logs")),
        )

        # Browser provider (GoLogin or Dolphin Anty)
        self.provider_name = self.config.browser_provider
        self.browser_client = self._create_browser_client()
        self.profile_manager = ProfileManager(
            self.browser_client, self.config.browser
        )

        # Google Drive
        gd_cfg = self.config.google_drive
        creds_path = str(self.config.resolve_path(gd_cfg.get("credentials_file", "")))
        self.drive_client = None
        if Path(creds_path).exists():
            self.drive_client = DriveClient(creds_path)
            self.file_monitor = FileMonitor(
                self.drive_client,
                self.db,
                download_dir=str(
                    self.config.resolve_path(
                        gd_cfg.get("download_dir", "data/downloads")
                    )
                ),
            )
        else:
            self.file_monitor = None
            logger.warning(
                f"Google Drive credentials not found at {creds_path}. "
                "Drive sync will be disabled."
            )

        # Scheduler & Queue
        self.job_manager = JobManager(timezone=self.config.timezone)
        self.queue = QueueHandler()

        # Per-account components (populated during setup)
        self._automations: dict = {}
        self._posters: dict = {}
        self._retweeters: dict = {}

        self._shutdown = False

    # ------------------------------------------------------------------
    # Browser provider factory
    # ------------------------------------------------------------------
    def _create_browser_client(self):
        """Instantiate the browser provider client based on configuration."""
        if self.provider_name == "gologin":
            from src.gologin.api_client import GoLoginClient

            cfg = self.config.gologin
            return GoLoginClient(
                host=cfg.get("host", "localhost"),
                port=cfg.get("port", 36912),
                api_token=cfg.get("api_token", ""),
            )
        elif self.provider_name == "dolphin_anty":
            from src.dolphin_anty.api_client import DolphinAntyClient

            cfg = self.config.dolphin_anty
            return DolphinAntyClient(
                host=cfg.get("host", "localhost"),
                port=cfg.get("port", 3001),
                api_token=cfg.get("api_token", ""),
            )
        else:
            raise ValueError(
                f"Unknown browser_provider '{self.provider_name}'. "
                "Use 'gologin' or 'dolphin_anty' in settings.yaml."
            )

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------
    def setup_account(self, acct: dict) -> bool:
        """Initialise browser, Selenium, and Twitter components for one account."""
        from src.core.logger import get_account_logger
        from src.twitter.automation import TwitterAutomation
        from src.twitter.poster import TwitterPoster
        from src.twitter.retweeter import TwitterRetweeter

        name = acct["name"]
        twitter_cfg = acct["twitter"]
        profile_id = twitter_cfg.get("profile_id") or twitter_cfg.get("dolphin_profile_id")
        acct_logger = get_account_logger(name, str(self.config.resolve_path("data/logs")))

        try:
            driver = self.profile_manager.start_browser(profile_id)
        except Exception as exc:
            logger.error(f"[{name}] Could not start browser: {exc}")
            self.db.update_account_status(name, status="error", error_message=str(exc))
            return False

        automation = TwitterAutomation(driver, self.config.delays)
        self._automations[name] = automation

        # Check login state – profiles should already be logged in
        if not automation.is_logged_in():
            logger.warning(
                f"[{name}] Browser is NOT logged in to Twitter. "
                f"Please log in manually via {self.provider_name} first."
            )
            self.db.update_account_status(
                name, status="error", error_message="Not logged in"
            )
            return False

        # Poster
        if self.file_monitor:
            poster = TwitterPoster(
                automation, self.file_monitor, self.db, name, acct
            )
            self._posters[name] = poster

        # Retweeter
        retweeter = TwitterRetweeter(automation, self.db, name, acct)
        self._retweeters[name] = retweeter

        self.db.update_account_status(name, status="idle", error_message=None)
        logger.info(f"[{name}] Account set up successfully")
        return True

    # ------------------------------------------------------------------
    # Schedule jobs
    # ------------------------------------------------------------------
    def schedule_account(self, acct: dict) -> None:
        name = acct["name"]

        # Posting schedule
        posting_cfg = acct.get("posting", {})
        if posting_cfg.get("enabled") and name in self._posters:
            schedule = posting_cfg.get("schedule", [])
            if schedule:
                self.job_manager.add_posting_jobs(
                    name,
                    schedule,
                    callback=partial(self._enqueue_task, name, "post", self._posters[name].run_posting_cycle),
                )

        # Drive sync interval
        drive_cfg = acct.get("google_drive", {})
        interval = drive_cfg.get("check_interval_minutes", 15)
        if self.file_monitor and name in self._posters:
            self.job_manager.add_drive_sync_job(
                name,
                interval,
                callback=partial(self._enqueue_task, name, "drive_sync", self._posters[name].run_posting_cycle),
            )

        # Retweet schedule
        rt_cfg = acct.get("retweeting", {})
        if rt_cfg.get("enabled") and name in self._retweeters:
            self.job_manager.add_retweet_jobs(
                name,
                daily_limit=rt_cfg.get("daily_limit", 3),
                time_windows=rt_cfg.get("time_windows", []),
                callback=partial(self._enqueue_task, name, "retweet", self._retweeters[name].run_retweet_cycle),
            )

    def _enqueue_task(self, account_name: str, task_type: str, callback) -> None:
        from src.scheduler.queue_handler import Task
        task = Task(account_name=account_name, task_type=task_type, callback=callback)
        self.queue.submit(task)

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------
    def run(self) -> None:
        accounts = self.config.enabled_accounts
        if not accounts:
            logger.error("No enabled accounts found in configuration")
            sys.exit(1)

        logger.info(f"Starting BunnyTweets with {len(accounts)} enabled account(s)")

        # Authenticate with browser provider API (required before any profile ops)
        logger.info(f"Browser provider: {self.provider_name}")
        if self.browser_client.api_token:
            if not self.browser_client.authenticate():
                logger.error(
                    f"{self.provider_name} authentication failed. "
                    "Check your API token in settings.yaml or the corresponding env var."
                )
                sys.exit(1)
        else:
            logger.warning(
                f"No {self.provider_name} API token configured. "
                "The local API may reject requests."
            )

        # Set up each account
        active_accounts = []
        for acct in accounts:
            if self.setup_account(acct):
                self.schedule_account(acct)
                active_accounts.append(acct)

        if not active_accounts:
            logger.error("No accounts could be initialised. Exiting.")
            self.shutdown()
            sys.exit(1)

        logger.info(f"{len(active_accounts)} account(s) active")

        # Health check
        self.job_manager.add_health_check(self._health_check, interval_minutes=5)

        # Start scheduler & queue
        self.queue.start()
        self.job_manager.start()

        self._print_dashboard()

        # Block main thread
        try:
            while not self._shutdown:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Interrupted by user")
        finally:
            self.shutdown()

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------
    def shutdown(self) -> None:
        self._shutdown = True
        logger.info("Shutting down...")
        self.job_manager.shutdown()
        self.queue.stop()
        self.profile_manager.stop_all()
        logger.info("Shutdown complete")

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------
    def _health_check(self) -> None:
        for name, auto in self._automations.items():
            try:
                auto.driver.title  # quick check that the browser is alive
            except Exception as exc:
                logger.error(f"[{name}] Browser health check failed: {exc}")
                self.db.update_account_status(
                    name, status="error", error_message=f"Health check: {exc}"
                )

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------
    def _print_dashboard(self) -> None:
        print("\n" + "=" * 60)
        print("  BunnyTweets – Twitter Multi-Account Automation")
        print("=" * 60)
        for acct in self.config.enabled_accounts:
            name = acct["name"]
            status_obj = self.db.get_account_status(name)
            status = status_obj.status if status_obj else "unknown"
            rt_today = self.db.get_retweets_today(name)
            rt_limit = acct.get("retweeting", {}).get("daily_limit", 3)
            print(f"  [{name}] status={status}  retweets={rt_today}/{rt_limit}")
        print()
        jobs = self.job_manager.get_jobs_summary()
        print(f"  Scheduled jobs: {len(jobs)}")
        for j in jobs[:10]:
            print(f"    {j['id']: <40} next: {j['next_run']}")
        if len(jobs) > 10:
            print(f"    ... and {len(jobs) - 10} more")
        print("=" * 60)
        print("  Press Ctrl+C to stop\n")

    # ------------------------------------------------------------------
    # Status command
    # ------------------------------------------------------------------
    def show_status(self) -> None:
        accounts = self.config.enabled_accounts
        print("\n  Account Status:")
        print("-" * 50)
        for acct in accounts:
            name = acct["name"]
            st = self.db.get_account_status(name)
            if st:
                print(f"  {name}")
                print(f"    Status:        {st.status}")
                print(f"    Last post:     {st.last_post}")
                print(f"    Last retweet:  {st.last_retweet}")
                print(f"    Retweets today:{st.retweets_today}")
                if st.error_message:
                    print(f"    Error:         {st.error_message}")
            else:
                print(f"  {name}: no data yet")
            print()

    # ------------------------------------------------------------------
    # Connection test
    # ------------------------------------------------------------------
    def test_connections(self) -> None:
        provider = self.provider_name
        print(f"\n  Testing connections (browser provider: {provider})...\n")

        # Browser provider – Authentication
        if self.browser_client.api_token:
            try:
                ok = self.browser_client.authenticate()
                if ok:
                    print(f"  [OK] {provider} authentication successful")
                else:
                    print(f"  [FAIL] {provider} authentication returned failure")
            except Exception as exc:
                print(f"  [FAIL] {provider} authentication: {exc}")
        else:
            print(f"  [WARN] No {provider} API token configured – skipping auth test")

        # Browser provider – Profile listing
        try:
            profiles = self.browser_client.list_profiles()
            if isinstance(profiles, dict):
                if "profiles" in profiles:
                    count = len(profiles["profiles"])
                elif isinstance(profiles.get("data"), list):
                    count = len(profiles["data"])
                else:
                    count = "?"
            elif isinstance(profiles, list):
                count = len(profiles)
            else:
                count = "?"
            print(f"  [OK] {provider} API reachable – {count} profile(s)")
        except Exception as exc:
            print(f"  [FAIL] {provider} API: {exc}")

        # Google Drive
        if self.drive_client:
            print("  [OK] Google Drive credentials loaded")
        else:
            print("  [WARN] Google Drive credentials not found")

        # Database
        try:
            self.db.session().close()
            print(f"  [OK] Database at {self.config.database_path}")
        except Exception as exc:
            print(f"  [FAIL] Database: {exc}")

        print()


def main():
    parser = argparse.ArgumentParser(description="BunnyTweets – Twitter Automation")
    parser.add_argument("--web", action="store_true", help="Launch the web dashboard")
    parser.add_argument("--port", type=int, default=8080, help="Web dashboard port (default: 8080)")
    parser.add_argument("--setup", action="store_true", help="Interactive first-time setup wizard")
    parser.add_argument("--add-account", action="store_true", help="Add a new Twitter account interactively")
    parser.add_argument("--status", action="store_true", help="Show account status")
    parser.add_argument("--test", action="store_true", help="Test connections")
    args = parser.parse_args()

    # Setup commands run before Application() since config files may not exist
    if args.setup:
        from src.core.setup_wizard import run_setup
        run_setup()
        return

    if args.add_account:
        from src.core.setup_wizard import run_add_account
        run_add_account()
        return

    # Web dashboard — lightweight, no Selenium required
    if args.web:
        from src.core.config_loader import ConfigLoader
        from src.core.database import Database
        from src.web import create_app

        config = ConfigLoader()
        db = Database(str(config.resolve_path(config.database_path)))
        flask_app = create_app(config, db)
        print(f"\n  BunnyTweets Dashboard: http://localhost:{args.port}\n")
        flask_app.run(host="0.0.0.0", port=args.port, debug=False)
        return

    app = Application()

    if args.status:
        app.show_status()
    elif args.test:
        app.test_connections()
    else:
        # Handle SIGTERM for Docker graceful shutdown
        signal.signal(signal.SIGTERM, lambda *_: app.shutdown())
        app.run()


if __name__ == "__main__":
    main()
