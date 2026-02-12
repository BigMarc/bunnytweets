#!/usr/bin/env python3
"""BunnyTweets – Twitter Multi-Account Automation System.

Usage:
    python main.py              Start the automation (all enabled accounts)
    python main.py --status     Show account status dashboard
    python main.py --test       Run a connectivity test against Dolphin Anty
"""

import argparse
import signal
import sys
import time
from datetime import datetime
from functools import partial
from pathlib import Path

from loguru import logger

from src.core.config_loader import ConfigLoader
from src.core.logger import setup_logging, get_account_logger
from src.core.database import Database
from src.dolphin_anty.api_client import DolphinAntyClient
from src.dolphin_anty.profile_manager import ProfileManager
from src.google_drive.drive_client import DriveClient
from src.google_drive.file_monitor import FileMonitor
from src.google_drive.media_handler import MediaHandler
from src.twitter.automation import TwitterAutomation
from src.twitter.poster import TwitterPoster
from src.twitter.retweeter import TwitterRetweeter
from src.scheduler.job_manager import JobManager
from src.scheduler.queue_handler import QueueHandler, Task


class Application:
    """Main application that wires all components together."""

    def __init__(self):
        self.config = ConfigLoader()
        self.db = Database(str(self.config.resolve_path(self.config.database_path)))

        # Logging
        log_cfg = self.config.logging
        setup_logging(
            level=log_cfg.get("level", "INFO"),
            retention_days=log_cfg.get("retention_days", 30),
            log_dir=str(self.config.resolve_path("data/logs")),
        )

        # Dolphin Anty
        da_cfg = self.config.dolphin_anty
        self.dolphin_client = DolphinAntyClient(
            host=da_cfg.get("host", "localhost"),
            port=da_cfg.get("port", 3001),
            api_token=da_cfg.get("api_token", ""),
        )
        self.profile_manager = ProfileManager(
            self.dolphin_client, self.config.browser
        )

        # Google Drive
        gd_cfg = self.config.google_drive
        creds_path = str(self.config.resolve_path(gd_cfg.get("credentials_file", "")))
        self.drive_client: DriveClient | None = None
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
        self._automations: dict[str, TwitterAutomation] = {}
        self._posters: dict[str, TwitterPoster] = {}
        self._retweeters: dict[str, TwitterRetweeter] = {}

        self._shutdown = False

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------
    def setup_account(self, acct: dict) -> bool:
        """Initialise browser, Selenium, and Twitter components for one account."""
        name = acct["name"]
        profile_id = acct["twitter"]["dolphin_profile_id"]
        acct_logger = get_account_logger(name, str(self.config.resolve_path("data/logs")))

        try:
            driver = self.profile_manager.start_browser(profile_id)
        except Exception as exc:
            logger.error(f"[{name}] Could not start browser: {exc}")
            self.db.update_account_status(name, status="error", error_message=str(exc))
            return False

        automation = TwitterAutomation(driver, self.config.delays)
        self._automations[name] = automation

        # Check login state – Dolphin Anty profiles should already be logged in
        if not automation.is_logged_in():
            logger.warning(
                f"[{name}] Browser is NOT logged in to Twitter. "
                "Please log in manually via Dolphin Anty first."
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

        # Authenticate with Dolphin Anty local API (required before any profile ops)
        if self.dolphin_client.api_token:
            if not self.dolphin_client.authenticate():
                logger.error(
                    "Dolphin Anty authentication failed. "
                    "Check your API token in settings.yaml or DOLPHIN_ANTY_TOKEN env var."
                )
                sys.exit(1)
        else:
            logger.warning(
                "No Dolphin Anty API token configured. "
                "The local API may reject requests with 401."
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
        print("\n  Testing connections...\n")

        # Dolphin Anty – Authentication
        if self.dolphin_client.api_token:
            try:
                ok = self.dolphin_client.authenticate()
                if ok:
                    print("  [OK] Dolphin Anty authentication successful")
                else:
                    print("  [FAIL] Dolphin Anty authentication returned failure")
            except Exception as exc:
                print(f"  [FAIL] Dolphin Anty authentication: {exc}")
        else:
            print("  [WARN] No Dolphin Anty API token configured – skipping auth test")

        # Dolphin Anty – Profile listing
        try:
            profiles = self.dolphin_client.list_profiles()
            count = profiles.get("data", {}).get("total", len(profiles.get("data", [])))
            print(f"  [OK] Dolphin Anty API reachable – {count} profile(s)")
        except Exception as exc:
            print(f"  [FAIL] Dolphin Anty API: {exc}")

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
    parser.add_argument("--status", action="store_true", help="Show account status")
    parser.add_argument("--test", action="store_true", help="Test connections")
    args = parser.parse_args()

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
