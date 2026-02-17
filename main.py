#!/usr/bin/env python3
"""BunnyTweets – Twitter Multi-Account Automation System.

Usage:
    python main.py              Start the automation (all enabled accounts)
    python main.py --web        Launch the web dashboard (http://localhost:8080)
    python main.py --desktop    Launch desktop app (dashboard + system tray)
    python main.py --setup      Interactive first-time setup wizard
    python main.py --add-account  Add a new Twitter account interactively
    python main.py --status     Show account status dashboard
    python main.py --test       Run a connectivity test against the browser provider
"""

from __future__ import annotations

import argparse
import signal
import sys
import threading
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
        from src.core.notifier import DiscordNotifier
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
            per_account_logs=log_cfg.get("per_account_logs", True),
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

        # Discord notifier
        self.notifier = DiscordNotifier.from_config(self.config.discord)

        # Scheduler & Queue (persist jobs to SQLite so they survive restarts)
        db_path = str(self.config.resolve_path(self.config.database_path))
        self.job_manager = JobManager(
            timezone=self.config.timezone,
            db_url=f"sqlite:///{db_path}",
        )
        self.queue = QueueHandler(
            error_handling=self.config.error_handling,
            db=self.db,
            notifier=self.notifier,
        )

        # Per-account components (populated during setup)
        self._automations: dict = {}
        self._posters: dict = {}
        self._retweeters: dict = {}
        self._simulators: dict = {}
        self._repliers: dict = {}

        self._shutdown = False
        self._ready = threading.Event()

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
    # Platform factory helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _get_platform(acct: dict) -> str:
        """Return the platform for an account config ('twitter' or 'threads')."""
        return acct.get("platform", "twitter")

    @staticmethod
    def _get_platform_cfg(acct: dict) -> dict:
        """Return the platform-specific credentials block (twitter or threads)."""
        platform = acct.get("platform", "twitter")
        return acct.get(platform, acct.get("twitter", {}))

    def _create_platform_components(self, acct: dict, driver):
        """Instantiate the correct Automation/Poster/Retweeter/Simulator/Replier
        classes based on the account's ``platform`` field.

        Returns (automation, poster_or_None, retweeter, simulator, replier).
        """
        platform = self._get_platform(acct)
        name = acct["name"]

        if platform == "threads":
            from src.platforms.threads.automation import ThreadsAutomation
            from src.platforms.threads.poster import ThreadsPoster
            from src.platforms.threads.reposter import ThreadsReposter
            from src.platforms.threads.replier import ThreadsReplier
            from src.platforms.threads.human_simulator import ThreadsHumanSimulator

            automation = ThreadsAutomation(driver, self.config.delays)
            poster = (
                ThreadsPoster(
                    automation, self.file_monitor, self.db, name, acct,
                    notifier=self.notifier,
                )
                if self.file_monitor
                else None
            )
            retweeter = ThreadsReposter(
                automation, self.db, name, acct, notifier=self.notifier
            )
            simulator = ThreadsHumanSimulator(automation, self.db, name, acct)
            replier = ThreadsReplier(
                automation, self.db, name, acct, notifier=self.notifier
            )
        else:
            # Default: Twitter
            from src.twitter.automation import TwitterAutomation
            from src.twitter.poster import TwitterPoster
            from src.twitter.retweeter import TwitterRetweeter
            from src.twitter.human_simulator import HumanSimulator
            from src.twitter.replier import TwitterReplier

            automation = TwitterAutomation(driver, self.config.delays)
            poster = (
                TwitterPoster(
                    automation, self.file_monitor, self.db, name, acct,
                    notifier=self.notifier,
                )
                if self.file_monitor
                else None
            )
            retweeter = TwitterRetweeter(
                automation, self.db, name, acct, notifier=self.notifier
            )
            simulator = HumanSimulator(automation, self.db, name, acct)
            replier = TwitterReplier(
                automation, self.db, name, acct, notifier=self.notifier
            )

        return automation, poster, retweeter, simulator, replier

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------
    def setup_account(self, acct: dict) -> bool:
        """Initialise browser, Selenium, and platform components for one account."""
        from src.core.logger import get_account_logger

        name = acct["name"]
        platform = self._get_platform(acct)
        platform_cfg = self._get_platform_cfg(acct)
        profile_id = platform_cfg.get("profile_id") or platform_cfg.get("dolphin_profile_id")
        get_account_logger(name, str(self.config.resolve_path("data/logs")))

        try:
            driver = self.profile_manager.start_browser(profile_id)
        except Exception as exc:
            logger.error(f"[{name}] Could not start browser: {exc}")
            self.db.update_account_status(name, status="error", error_message=str(exc))
            self.notifier.alert_browser_failed(name, str(exc))
            return False

        automation, poster, retweeter, simulator, replier = (
            self._create_platform_components(acct, driver)
        )
        self._automations[name] = automation

        # Check login state – profiles should already be logged in
        platform_label = "Threads" if platform == "threads" else "Twitter"
        if not automation.is_logged_in():
            logger.warning(
                f"[{name}] Browser is NOT logged in to {platform_label}. "
                f"Please log in manually via {self.provider_name} first."
            )
            self.db.update_account_status(
                name, status="error", error_message="Not logged in"
            )
            self.notifier.alert_not_logged_in(name)
            return False

        if poster:
            self._posters[name] = poster
        self._retweeters[name] = retweeter
        self._simulators[name] = simulator
        self._repliers[name] = replier

        self.db.update_account_status(name, status="idle", error_message=None)
        logger.info(f"[{name}] {platform_label} account set up successfully")
        return True

    # ------------------------------------------------------------------
    # Schedule jobs
    # ------------------------------------------------------------------
    def schedule_account(self, acct: dict) -> None:
        name = acct["name"]
        platform = self._get_platform(acct)

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

        # Retweet / Repost schedule
        # Twitter uses "retweeting", Threads uses "reposting"
        if platform == "threads":
            rt_cfg = acct.get("reposting", {})
            daily_limit = rt_cfg.get("max_per_day", 5)
        else:
            rt_cfg = acct.get("retweeting", {})
            daily_limit = rt_cfg.get("daily_limit", 3)

        if rt_cfg.get("enabled") and name in self._retweeters:
            self.job_manager.add_retweet_jobs(
                name,
                daily_limit=daily_limit,
                time_windows=rt_cfg.get("time_windows", []),
                callback=partial(self._enqueue_task, name, "retweet", self._retweeters[name].run_retweet_cycle),
            )

        # Human simulation schedule
        sim_cfg = acct.get("human_simulation", {})
        if sim_cfg.get("enabled") and name in self._simulators:
            self.job_manager.add_simulation_jobs(
                name,
                daily_sessions=sim_cfg.get("daily_sessions_limit", 2),
                time_windows=sim_cfg.get("time_windows", []),
                callback=partial(self._enqueue_task, name, "simulation", self._simulators[name].run_session),
            )

        # Reply schedule
        reply_cfg = acct.get("reply_to_replies", {})
        if reply_cfg.get("enabled") and name in self._repliers:
            self.job_manager.add_reply_jobs(
                name,
                daily_limit=reply_cfg.get("daily_limit", 10),
                time_windows=reply_cfg.get("time_windows", []),
                callback=partial(self._enqueue_task, name, "reply", self._repliers[name].run_reply_cycle),
            )

    def _enqueue_task(self, account_name: str, task_type: str, callback) -> None:
        from src.scheduler.queue_handler import Task
        max_retries = self.config.error_handling.get("max_retries", 3)
        task = Task(account_name=account_name, task_type=task_type,
                    callback=callback, max_retries=max_retries)
        self.queue.submit(task)

    def _check_cta_pending(self) -> None:
        """Check all accounts for pending CTA comments (posted >55 min ago)."""
        for name, poster in self._posters.items():
            status = self.db.get_account_status(name)
            if not status or not status.cta_pending:
                continue
            # Only fire CTA if last post was at least 55 minutes ago
            if status.last_post:
                elapsed = (datetime.utcnow() - status.last_post).total_seconds()
                if elapsed < 55 * 60:
                    continue
            logger.info(f"[{name}] CTA comment is due — enqueueing")
            self.db.update_account_status(name, cta_pending=0)
            self._enqueue_task(name, "cta_comment", poster.run_cta_comment)

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

        # CTA comment check (looks for pending CTAs every 5 min)
        self.job_manager.add_cta_check_job(self._check_cta_pending, interval_minutes=5)

        # Start scheduler & queue
        self.queue.start()
        self.job_manager.start()

        # Signal that the engine is fully ready
        self._ready.set()

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
        if getattr(self, '_shutdown_complete', False):
            return
        self._shutdown = True
        self._shutdown_complete = True
        logger.info("Shutting down...")
        self.job_manager.shutdown()
        self.queue.stop()
        self.profile_manager.stop_all()
        logger.info("Shutdown complete")

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------
    def _health_check(self) -> None:
        for name, auto in list(self._automations.items()):
            try:
                auto.driver.title  # quick check that the browser is alive
            except Exception as exc:
                error_str = str(exc).split("\n")[0]  # first line only
                logger.error(f"[{name}] Browser health check failed: {error_str}")
                self.db.update_account_status(
                    name, status="error", error_message=f"Health check: {error_str}"
                )
                self.notifier.alert_health_check_failed(name, error_str)

                # Attempt auto-recovery by restarting the browser
                self._try_recover_browser(name)

    def _try_recover_browser(self, name: str) -> None:
        """Attempt to restart a crashed browser profile and re-wire components."""
        acct = None
        for a in self.config.enabled_accounts:
            if a.get("name") == name:
                acct = a
                break
        if not acct:
            return

        platform_cfg = self._get_platform_cfg(acct)
        profile_id = platform_cfg.get("profile_id") or platform_cfg.get("dolphin_profile_id")
        platform_label = "Threads" if self._get_platform(acct) == "threads" else "Twitter"

        logger.info(f"[{name}] Attempting auto-recovery — restarting browser...")
        try:
            try:
                self.profile_manager.stop_browser(profile_id)
            except Exception:
                pass

            time.sleep(3)
            driver = self.profile_manager.start_browser(profile_id)
        except Exception as exc:
            logger.error(f"[{name}] Auto-recovery failed: {exc}")
            self.notifier.alert_generic(name, "Auto-Recovery Failed", str(exc))
            return

        automation, poster, retweeter, simulator, replier = (
            self._create_platform_components(acct, driver)
        )
        self._automations[name] = automation

        if not automation.is_logged_in():
            logger.warning(f"[{name}] Recovered browser but not logged in to {platform_label}")
            self.db.update_account_status(name, status="error", error_message="Not logged in after recovery")
            self.notifier.alert_not_logged_in(name)
            return

        if poster:
            self._posters[name] = poster
        self._retweeters[name] = retweeter
        self._simulators[name] = simulator
        self._repliers[name] = replier

        self.db.update_account_status(name, status="idle", error_message=None)
        logger.info(f"[{name}] Auto-recovery successful — browser restarted")
        self.notifier.send(
            title="Auto-Recovery Successful",
            description=f"**{name}** browser was restarted automatically.",
            color=0x00CC00,
        )

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------
    def _print_dashboard(self) -> None:
        print("\n" + "=" * 60)
        print("  BunnyTweets – Multi-Platform Social Media Automation")
        print("=" * 60)
        for acct in self.config.enabled_accounts:
            name = acct["name"]
            platform = self._get_platform(acct)
            status_obj = self.db.get_account_status(name)
            status = status_obj.status if status_obj else "unknown"
            rt_today = self.db.get_retweets_today(name)
            if platform == "threads":
                rt_limit = acct.get("reposting", {}).get("max_per_day", 5)
            else:
                rt_limit = acct.get("retweeting", {}).get("daily_limit", 3)
            print(f"  [{name}] platform={platform}  status={status}  retweets={rt_today}/{rt_limit}")
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

        # Browser provider – Profile listing (remote API, not required for engine)
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
            print(f"  [OK] {provider} remote API – {count} profile(s)")
        except Exception as exc:
            print(f"  [WARN] {provider} remote API: {exc}")
            print(f"         (The engine uses the local API and may still work fine)")

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
    parser.add_argument("--desktop", action="store_true", help="Launch desktop app (dashboard + system tray)")
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

    # Desktop mode — dashboard + system tray
    if args.desktop:
        from desktop import main as desktop_main
        import sys
        sys.argv = ["desktop.py", f"--port={args.port}"]
        desktop_main()
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
