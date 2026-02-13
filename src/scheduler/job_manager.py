"""APScheduler-based job manager that sets up cron and interval jobs per account."""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from enum import Enum

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED
from loguru import logger


class JobType(Enum):
    POST_CONTENT = "post_content"
    RETWEET_TARGET = "retweet_target"
    DRIVE_SYNC = "drive_sync"
    HEALTH_CHECK = "health_check"
    HUMAN_SIMULATION = "human_simulation"
    CTA_COMMENT = "cta_comment"
    REPLY = "reply"


class JobManager:
    """Manages all scheduled jobs via APScheduler."""

    def __init__(self, timezone: str = "America/New_York"):
        self.scheduler = BackgroundScheduler(timezone=timezone)
        self.scheduler.add_listener(self._on_job_event, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)
        self.timezone = timezone

    def _on_job_event(self, event):
        if event.exception:
            logger.error(f"Job {event.job_id} raised: {event.exception}")
        else:
            logger.debug(f"Job {event.job_id} executed successfully")

    # ------------------------------------------------------------------
    # Posting schedules
    # ------------------------------------------------------------------
    def add_posting_jobs(self, account_name: str, schedule: list[dict], callback) -> None:
        """Add cron jobs for posting at specific times.

        schedule items: [{"time": "09:00"}, {"time": "15:00"}, ...]
        """
        for i, entry in enumerate(schedule):
            t = entry.get("time", "12:00")
            hour, minute = t.split(":")
            job_id = f"post_{account_name}_{i}"
            self.scheduler.add_job(
                callback,
                trigger="cron",
                hour=int(hour),
                minute=int(minute),
                id=job_id,
                replace_existing=True,
                name=f"Post for {account_name} at {t}",
            )
            logger.info(f"Scheduled posting job: {job_id} at {t}")

    # ------------------------------------------------------------------
    # Retweet schedules
    # ------------------------------------------------------------------
    def add_retweet_jobs(
        self,
        account_name: str,
        daily_limit: int,
        time_windows: list[dict],
        callback,
    ) -> None:
        """Schedule retweet jobs spread across time windows.

        Distributes `daily_limit` retweets across the given windows using
        one-shot triggers that are re-scheduled daily.
        """
        if not time_windows or daily_limit <= 0:
            return

        # Spread retweets evenly across time windows
        retweets_per_window = max(1, daily_limit // len(time_windows))
        remaining = daily_limit

        for wi, window in enumerate(time_windows):
            if remaining <= 0:
                break
            count = min(retweets_per_window, remaining)
            start_h, start_m = map(int, window["start"].split(":"))
            end_h, end_m = map(int, window["end"].split(":"))

            for ri in range(count):
                # Pick a random minute within the window for each retweet
                total_start = start_h * 60 + start_m
                total_end = end_h * 60 + end_m
                random_minute = random.randint(total_start, max(total_start, total_end - 1))
                h = random_minute // 60
                m = random_minute % 60

                job_id = f"retweet_{account_name}_w{wi}_r{ri}"
                self.scheduler.add_job(
                    callback,
                    trigger="cron",
                    hour=h,
                    minute=m,
                    id=job_id,
                    replace_existing=True,
                    name=f"Retweet for {account_name} at {h:02d}:{m:02d}",
                )
                logger.info(f"Scheduled retweet job: {job_id} at {h:02d}:{m:02d}")
                remaining -= 1

    # ------------------------------------------------------------------
    # Drive sync interval
    # ------------------------------------------------------------------
    def add_drive_sync_job(
        self, account_name: str, interval_minutes: int, callback
    ) -> None:
        job_id = f"drive_sync_{account_name}"
        self.scheduler.add_job(
            callback,
            trigger="interval",
            minutes=interval_minutes,
            id=job_id,
            replace_existing=True,
            name=f"Drive sync for {account_name}",
            next_run_time=datetime.now(),  # run immediately on start
        )
        logger.info(
            f"Scheduled Drive sync: {job_id} every {interval_minutes} minutes"
        )

    # ------------------------------------------------------------------
    # Human simulation schedules
    # ------------------------------------------------------------------
    def add_simulation_jobs(
        self,
        account_name: str,
        daily_sessions: int,
        time_windows: list[dict],
        callback,
    ) -> None:
        """Schedule human simulation sessions spread across time windows.

        Distributes sessions across the given windows at random times.
        """
        if not time_windows or daily_sessions <= 0:
            return

        sessions_per_window = max(1, daily_sessions // len(time_windows))
        remaining = daily_sessions

        for wi, window in enumerate(time_windows):
            if remaining <= 0:
                break
            count = min(sessions_per_window, remaining)
            start_h, start_m = map(int, window["start"].split(":"))
            end_h, end_m = map(int, window["end"].split(":"))

            for si in range(count):
                total_start = start_h * 60 + start_m
                total_end = end_h * 60 + end_m
                random_minute = random.randint(total_start, max(total_start, total_end - 1))
                h = random_minute // 60
                m = random_minute % 60

                job_id = f"sim_{account_name}_w{wi}_s{si}"
                self.scheduler.add_job(
                    callback,
                    trigger="cron",
                    hour=h,
                    minute=m,
                    id=job_id,
                    replace_existing=True,
                    name=f"Human sim for {account_name} at {h:02d}:{m:02d}",
                )
                logger.info(f"Scheduled simulation job: {job_id} at {h:02d}:{m:02d}")
                remaining -= 1

    # ------------------------------------------------------------------
    # Reply schedules
    # ------------------------------------------------------------------
    def add_reply_jobs(
        self,
        account_name: str,
        daily_limit: int,
        time_windows: list[dict],
        callback,
    ) -> None:
        """Schedule reply-to-mentions jobs spread across time windows."""
        if not time_windows or daily_limit <= 0:
            return

        replies_per_window = max(1, daily_limit // len(time_windows))
        remaining = daily_limit

        for wi, window in enumerate(time_windows):
            if remaining <= 0:
                break
            count = min(replies_per_window, remaining)
            start_h, start_m = map(int, window["start"].split(":"))
            end_h, end_m = map(int, window["end"].split(":"))

            for ri in range(count):
                total_start = start_h * 60 + start_m
                total_end = end_h * 60 + end_m
                random_minute = random.randint(total_start, max(total_start, total_end - 1))
                h = random_minute // 60
                m = random_minute % 60

                job_id = f"reply_{account_name}_w{wi}_r{ri}"
                self.scheduler.add_job(
                    callback,
                    trigger="cron",
                    hour=h,
                    minute=m,
                    id=job_id,
                    replace_existing=True,
                    name=f"Reply for {account_name} at {h:02d}:{m:02d}",
                )
                logger.info(f"Scheduled reply job: {job_id} at {h:02d}:{m:02d}")
                remaining -= 1

    # ------------------------------------------------------------------
    # CTA comment check
    # ------------------------------------------------------------------
    def add_cta_check_job(self, callback, interval_minutes: int = 5) -> None:
        """Periodically check for accounts with cta_pending and run their CTA comment."""
        job_id = "cta_comment_check"
        self.scheduler.add_job(
            callback,
            trigger="interval",
            minutes=interval_minutes,
            id=job_id,
            replace_existing=True,
            name="CTA comment check",
        )
        logger.info(f"Scheduled CTA comment check every {interval_minutes} minutes")

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------
    def add_health_check(self, callback, interval_minutes: int = 5) -> None:
        self.scheduler.add_job(
            callback,
            trigger="interval",
            minutes=interval_minutes,
            id="health_check",
            replace_existing=True,
            name="Health check",
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self) -> None:
        self.scheduler.start()
        logger.info("Scheduler started")

    def shutdown(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
        logger.info("Scheduler shut down")

    def get_jobs_summary(self) -> list[dict]:
        """Return a summary of all scheduled jobs."""
        jobs = []
        for j in self.scheduler.get_jobs():
            jobs.append(
                {
                    "id": j.id,
                    "name": j.name,
                    "next_run": str(j.next_run_time) if j.next_run_time else None,
                    "trigger": str(j.trigger),
                }
            )
        return jobs
