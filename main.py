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
    python main.py --quiet      Run with terminal output suppressed (logs to files only)
"""

from __future__ import annotations

import argparse
import signal
import sys
import threading
import time
from datetime import datetime
from pathlib import Path


from loguru import logger

# Module-level reference so APScheduler dispatchers can reach the app at
# runtime.  Set once in Application.__init__().
_app_ref = None  # type: Application | None

# Task-type → (component dict attr, method name)
_TASK_DISPATCH = {
    "post": ("_posters", "run_posting_cycle"),
    "retweet": ("_retweeters", "run_retweet_cycle"),
    "simulation": ("_simulators", "run_session"),
    "reply": ("_repliers", "run_reply_cycle"),
}


def dispatch_job(account_name: str, task_type: str) -> None:
    """Module-level callback that APScheduler can serialise to the job store.

    Looks up the correct component from the live Application instance and
    enqueues the task through the normal queue.
    """
    app = _app_ref
    if app is None:
        logger.warning(f"dispatch_job({account_name!r}, {task_type!r}) skipped: app not ready")
        return

    entry = _TASK_DISPATCH.get(task_type)
    if entry is None:
        logger.error(f"dispatch_job: unknown task_type {task_type!r}")
        return

    attr, method_name = entry
    try:
        components = getattr(app, attr, None)
        if components is None:
            logger.warning(f"dispatch_job: app has no attribute {attr!r}")
            return
        component = components.get(account_name)
        if component is None:
            logger.warning(f"dispatch_job: no {task_type} component for {account_name!r}")
            return
        method = getattr(component, method_name, None)
        if method is None:
            logger.error(f"dispatch_job: {type(component).__name__} has no method {method_name!r}")
            return
        app._enqueue_task(account_name, task_type, method)
    except Exception as exc:
        logger.error(f"dispatch_job({account_name!r}, {task_type!r}) failed: {exc}")


def dispatch_health_check() -> None:
    """Module-level health-check callback for APScheduler persistence."""
    if _app_ref is not None:
        _app_ref._health_check()


def dispatch_cta_check() -> None:
    """Module-level CTA-check callback for APScheduler persistence."""
    if _app_ref is not None:
        _app_ref._check_cta_pending()


def dispatch_setup_retry() -> None:
    """Module-level callback to retry failed account setups."""
    if _app_ref is not None:
        _app_ref._retry_failed_accounts()


class Application:
    """Main application that wires all components together."""

    def __init__(self, quiet: bool = False):
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

        self._quiet = quiet
        self.config = ConfigLoader()
        self.db = Database(str(self.config.resolve_path(self.config.database_path)))

        # Logging
        log_cfg = self.config.logging
        self._log_retention_days = log_cfg.get("retention_days", 30)
        setup_logging(
            level=log_cfg.get("level", "INFO"),
            retention_days=self._log_retention_days,
            per_account_logs=log_cfg.get("per_account_logs", True),
            log_dir=str(self.config.resolve_path("data/logs")),
            quiet=quiet or log_cfg.get("quiet", False),
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
        self.file_monitor = None
        if Path(creds_path).exists():
            try:
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
            except Exception as exc:
                logger.warning(
                    f"Google Drive credentials at {creds_path} could not be loaded: {exc}. "
                    "Drive sync will be disabled."
                )
                self.drive_client = None
                self.file_monitor = None
        else:
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

        # Track accounts that failed setup for periodic retry
        self._failed_accounts: list[dict] = []
        self._setup_retry_counts: dict[str, int] = {}
        self._max_setup_retries = 3

        self._shutdown = False
        self._shutdown_lock = threading.Lock()
        self._shutdown_complete = False
        self._ready = threading.Event()

        global _app_ref
        _app_ref = self

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
        """Return the platform for an account config ('twitter', 'threads', or 'redgifs')."""
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
        elif platform == "redgifs":
            from src.platforms.redgifs.automation import RedGifsAutomation
            from src.platforms.redgifs.poster import RedGifsPoster
            from src.platforms.redgifs.human_simulator import RedGifsHumanSimulator

            automation = RedGifsAutomation(driver, self.config.delays)
            poster = (
                RedGifsPoster(
                    automation, self.file_monitor, self.db, name, acct,
                    notifier=self.notifier,
                )
                if self.file_monitor
                else None
            )
            retweeter = None   # RedGifs has no repost feature
            simulator = RedGifsHumanSimulator(automation, self.db, name, acct)
            replier = None     # RedGifs has no reply feature
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
        get_account_logger(name, str(self.config.resolve_path("data/logs")),
                          retention_days=self._log_retention_days)

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

        # Check login state – profiles should already be logged in
        platform_labels = {"threads": "Threads", "redgifs": "RedGifs"}
        platform_label = platform_labels.get(platform, "Twitter")
        if not automation.is_logged_in():
            logger.warning(
                f"[{name}] Browser is NOT logged in to {platform_label}. "
                f"Please log in manually via {self.provider_name} first."
            )
            self.db.update_account_status(
                name, status="error", error_message="Not logged in"
            )
            self.notifier.alert_not_logged_in(name)
            # Stop the browser we just started to avoid orphaned processes
            try:
                self.profile_manager.stop_browser(profile_id)
            except Exception:
                pass
            return False

        # Only store components after login check passes to avoid stale
        # entries visible to health-check and dispatch threads.
        self._automations[name] = automation
        if poster:
            self._posters[name] = poster
        if retweeter is not None:
            self._retweeters[name] = retweeter
        self._simulators[name] = simulator
        if replier is not None:
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
                    callback=dispatch_job,
                    callback_args=(name, "post"),
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
                callback=dispatch_job,
                callback_args=(name, "retweet"),
            )

        # Human simulation schedule
        sim_cfg = acct.get("human_simulation", {})
        if sim_cfg.get("enabled") and name in self._simulators:
            self.job_manager.add_simulation_jobs(
                name,
                daily_sessions=sim_cfg.get("daily_sessions_limit", 2),
                time_windows=sim_cfg.get("time_windows", []),
                callback=dispatch_job,
                callback_args=(name, "simulation"),
            )

        # Reply schedule
        reply_cfg = acct.get("reply_to_replies", {})
        if reply_cfg.get("enabled") and name in self._repliers:
            self.job_manager.add_reply_jobs(
                name,
                daily_limit=reply_cfg.get("daily_limit", 10),
                time_windows=reply_cfg.get("time_windows", []),
                callback=dispatch_job,
                callback_args=(name, "reply"),
            )

    def _enqueue_task(self, account_name: str, task_type: str, callback) -> None:
        from src.scheduler.queue_handler import Task
        max_retries = self.config.error_handling.get("max_retries", 3)
        task = Task(account_name=account_name, task_type=task_type,
                    callback=callback, max_retries=max_retries)
        self.queue.submit(task)

    def _check_cta_pending(self) -> None:
        """Check all accounts for pending CTA comments (posted >55 min ago)."""
        for name, poster in list(self._posters.items()):
            if not hasattr(poster, "run_cta_comment"):
                continue
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

    def _retry_failed_accounts(self) -> None:
        """Periodically retry accounts that failed initial setup."""
        still_failed = []
        for acct in self._failed_accounts:
            name = acct["name"]
            attempts = self._setup_retry_counts.get(name, 0)
            if attempts >= self._max_setup_retries:
                logger.warning(f"[{name}] Giving up setup retry after {attempts} attempts")
                self.notifier.send(
                    title="Account Setup Failed Permanently",
                    description=(
                        f"**{name}** could not be initialised after "
                        f"{attempts} attempts. Manual intervention required."
                    ),
                    color=0xFF0000,
                )
                continue
            self._setup_retry_counts[name] = attempts + 1
            logger.info(f"[{name}] Retrying setup (attempt {attempts + 1}/{self._max_setup_retries})")
            if self.setup_account(acct):
                self.schedule_account(acct)
                logger.info(f"[{name}] Setup retry succeeded")
            else:
                still_failed.append(acct)
        self._failed_accounts = still_failed
        if not self._failed_accounts:
            # All recovered or gave up — remove the retry job
            try:
                self.job_manager.scheduler.remove_job("setup_retry")
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------
    def run(self) -> None:
        accounts = self.config.enabled_accounts
        if not accounts:
            raise RuntimeError("No enabled accounts found in configuration")

        logger.info(f"Starting BunnyTweets with {len(accounts)} enabled account(s)")

        # Authenticate with browser provider API (required before any profile ops)
        logger.info(f"Browser provider: {self.provider_name}")
        if self.browser_client.api_token:
            if not self.browser_client.authenticate():
                raise RuntimeError(
                    f"{self.provider_name} authentication failed. "
                    "Check your API token in settings.yaml or the corresponding env var."
                )
        else:
            logger.warning(
                f"No {self.provider_name} API token configured. "
                "The local API may reject requests."
            )

        # Set up each account (parallel – browser starts are I/O-bound)
        from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeout

        setup_timeout = 600  # seconds — hard cap on total account setup time
        active_accounts = []
        pool = ThreadPoolExecutor(max_workers=min(len(accounts), 15))
        future_to_acct = {
            pool.submit(self.setup_account, acct): acct for acct in accounts
        }
        try:
            for future in as_completed(future_to_acct, timeout=setup_timeout):
                acct = future_to_acct[future]
                try:
                    if future.result():
                        self.schedule_account(acct)
                        active_accounts.append(acct)
                    else:
                        self._failed_accounts.append(acct)
                except Exception as exc:
                    logger.error(f"[{acct['name']}] Setup failed: {exc}")
                    self._failed_accounts.append(acct)
        except FuturesTimeout:
            for fut, acct in future_to_acct.items():
                if not fut.done():
                    logger.warning(
                        f"[{acct['name']}] Setup timed out after {setup_timeout}s"
                    )
                    self._failed_accounts.append(acct)
                    fut.cancel()
        finally:
            # Give timed-out threads a grace period to finish cleanly,
            # but don't block forever if they're stuck.
            pool.shutdown(wait=True, cancel_futures=True)

        if not active_accounts:
            self.shutdown()
            raise RuntimeError("No accounts could be initialised")

        logger.info(f"{len(active_accounts)} account(s) active")

        # Health check
        self.job_manager.add_health_check(dispatch_health_check, interval_minutes=5)

        # CTA comment check (looks for pending CTAs every 5 min)
        self.job_manager.add_cta_check_job(dispatch_cta_check, interval_minutes=5)

        # Retry failed account setups every 5 min (up to max_setup_retries)
        if self._failed_accounts:
            logger.info(
                f"{len(self._failed_accounts)} account(s) failed setup — "
                f"will retry every 5 minutes (max {self._max_setup_retries} attempts)"
            )
            self.job_manager.scheduler.add_job(
                dispatch_setup_retry,
                trigger="interval",
                minutes=5,
                id="setup_retry",
                replace_existing=True,
                name="Retry failed account setups",
            )

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
        with self._shutdown_lock:
            if self._shutdown_complete:
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
        platform_labels = {"threads": "Threads", "redgifs": "RedGifs"}
        platform_label = platform_labels.get(self._get_platform(acct), "Twitter")

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
        if retweeter is not None:
            self._retweeters[name] = retweeter
        self._simulators[name] = simulator
        if replier is not None:
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
        if self._quiet:
            return
        print("\n" + "=" * 60)
        print("  BunnyTweets – Multi-Platform Social Media Automation")
        print("=" * 60)
        for acct in self.config.enabled_accounts:
            name = acct["name"]
            platform = self._get_platform(acct)
            status_obj = self.db.get_account_status(name)
            status = status_obj.status if status_obj else "unknown"
            if platform == "redgifs":
                print(f"  [{name}] platform={platform}  status={status}")
            else:
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
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="Suppress terminal output (logs still written to files)")
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

        if args.quiet:
            # Auto-start engine when --web --quiet used together
            state = flask_app.config["APP_STATE"]
            state.start_engine()
            # Suppress Werkzeug per-request access logs (keep errors)
            import logging
            logging.getLogger("werkzeug").setLevel(logging.ERROR)

        print(f"\n  BunnyTweets Dashboard: http://localhost:{args.port}\n")
        flask_app.run(host="0.0.0.0", port=args.port, debug=False)
        return

    app = Application(quiet=args.quiet)

    if args.status:
        app.show_status()
    elif args.test:
        app.test_connections()
    else:
        # Handle SIGTERM for Docker graceful shutdown
        signal.signal(signal.SIGTERM, lambda *_: app.shutdown())
        try:
            app.run()
        except RuntimeError as exc:
            logger.error(str(exc))
            sys.exit(1)


if __name__ == "__main__":
    main()
