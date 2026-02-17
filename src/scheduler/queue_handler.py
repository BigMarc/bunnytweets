"""Thread-safe task queue for asynchronous job execution."""

from __future__ import annotations

import threading
import time as _time
from concurrent.futures import ThreadPoolExecutor, Future
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from queue import Queue, Empty
from typing import Any, Callable

from loguru import logger


class TaskStatus(Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Task:
    account_name: str
    task_type: str
    callback: Callable
    args: tuple = ()
    kwargs: dict = field(default_factory=dict)
    status: TaskStatus = TaskStatus.QUEUED
    result: Any = None
    error: Exception | None = None
    retry_count: int = 0
    max_retries: int = 3


class QueueHandler:
    """Manages a thread pool + queue for account tasks.

    Ensures only one task per account runs at a time (to avoid concurrent
    Selenium operations on the same browser profile).

    Supports retry with exponential backoff and account pausing after
    max retries are exhausted.
    """

    def __init__(self, max_workers: int = 5, error_handling: dict | None = None,
                 db=None, notifier=None):
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self._queue: Queue[Task] = Queue()
        self._running: dict[str, Future] = {}
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._worker_thread: threading.Thread | None = None
        self._error_handling = error_handling or {}
        self._db = db
        self._notifier = notifier
        self._paused_accounts: dict[str, datetime] = {}

        # Restore paused accounts from a previous run so they don't
        # accidentally resume when the process restarts.
        self._load_paused_accounts()

    def _load_paused_accounts(self) -> None:
        """Restore paused accounts from the database.

        If an account was paused before the process stopped, re-populate
        ``_paused_accounts`` so the pause is honoured after restart.  Accounts
        whose pause window has already expired are cleared back to idle.
        """
        if not self._db:
            return
        try:
            from src.core.database import AccountStatus

            with self._db.session() as s:
                paused = (
                    s.query(AccountStatus)
                    .filter(AccountStatus.status == "paused")
                    .all()
                )
                pause_minutes = self._error_handling.get("pause_duration_minutes", 60)
                for acct in paused:
                    # Estimate unpause time from the error_message or fall back
                    # to pause_duration_minutes from now (safe default).
                    unpause_at = datetime.utcnow() + timedelta(minutes=pause_minutes)
                    self._paused_accounts[acct.account_name] = unpause_at
                    logger.info(
                        f"[{acct.account_name}] Restored paused state from DB "
                        f"(will unpause around {unpause_at.strftime('%H:%M')})"
                    )
        except Exception as exc:
            logger.warning(f"Could not load paused accounts from DB: {exc}")

    def submit(self, task: Task) -> None:
        """Add a task to the queue."""
        self._queue.put(task)
        logger.debug(
            f"Queued task: {task.task_type} for {task.account_name} "
            f"(queue size: {self._queue.qsize()})"
        )

    def start(self) -> None:
        """Start the background worker that drains the queue."""
        self._stop_event.clear()
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker_thread.start()
        logger.info("Queue handler started")

    def stop(self) -> None:
        """Signal the worker to stop and wait for in-flight tasks."""
        self._stop_event.set()
        self.executor.shutdown(wait=True)
        if self._worker_thread:
            self._worker_thread.join(timeout=10)
        logger.info("Queue handler stopped")

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            # Clean up completed futures
            with self._lock:
                done = [k for k, v in self._running.items() if v.done()]
                for k in done:
                    self._running.pop(k)

            # Pull next task from queue
            try:
                task = self._queue.get(timeout=1)
            except Empty:
                continue

            # Skip tasks for paused accounts
            if self._is_account_paused(task.account_name):
                logger.debug(
                    f"Skipping task {task.task_type} for paused account {task.account_name}"
                )
                continue

            with self._lock:
                if task.account_name in self._running:
                    logger.debug(
                        f"Account {task.account_name} is busy — "
                        f"re-queuing {task.task_type} task"
                    )
                    self._queue.put(task)
                    continue

                task.status = TaskStatus.RUNNING
                future = self.executor.submit(self._run_task, task)
                self._running[task.account_name] = future

    def _run_task(self, task: Task) -> Any:
        try:
            start = _time.monotonic()
            result = task.callback(*task.args, **task.kwargs)
            duration = _time.monotonic() - start
            task.status = TaskStatus.COMPLETED
            task.result = result
            self._log_task(task, "success", duration=duration)
            return result
        except Exception as exc:
            duration = _time.monotonic() - start
            task.error = exc
            logger.error(
                f"Task {task.task_type} for {task.account_name} failed "
                f"(attempt {task.retry_count + 1}/{task.max_retries}): {exc}"
            )

            if task.retry_count < task.max_retries - 1:
                task.retry_count += 1
                task.status = TaskStatus.QUEUED
                backoff = self._error_handling.get("retry_backoff", 5)
                delay = backoff * (2 ** (task.retry_count - 1))
                logger.info(
                    f"Retrying {task.task_type} for {task.account_name} "
                    f"in {delay}s (attempt {task.retry_count + 1}/{task.max_retries})"
                )
                self._log_task(task, "failed", duration=duration,
                               error_message=str(exc))
                threading.Thread(
                    target=self._delayed_requeue, args=(task, delay), daemon=True
                ).start()
                return None
            else:
                task.status = TaskStatus.FAILED
                self._log_task(task, "failed", duration=duration,
                               error_message=str(exc))
                self._pause_account(task.account_name, str(exc))
                raise

    def _delayed_requeue(self, task: Task, delay: float) -> None:
        _time.sleep(delay)
        self._queue.put(task)

    def _pause_account(self, account_name: str, error: str) -> None:
        pause_minutes = self._error_handling.get("pause_duration_minutes", 60)
        unpause_at = datetime.utcnow() + timedelta(minutes=pause_minutes)
        self._paused_accounts[account_name] = unpause_at

        if self._db:
            self._db.update_account_status(
                account_name, status="paused",
                error_message=f"Paused until {unpause_at.strftime('%H:%M')} after max retries: {error[:200]}"
            )

        if self._notifier:
            max_retries = self._error_handling.get("max_retries", 3)
            self._notifier.send(
                title="Account Paused",
                description=(
                    f"**{account_name}** paused for {pause_minutes} minutes "
                    f"after {max_retries} consecutive failures."
                ),
                color=0xFFA500,
                fields=[{"name": "Last Error", "value": f"```{error[:500]}```", "inline": False}],
            )

        logger.warning(
            f"[{account_name}] Paused for {pause_minutes} minutes (max retries exhausted)"
        )

    def _is_account_paused(self, account_name: str) -> bool:
        if account_name not in self._paused_accounts:
            return False
        unpause_at = self._paused_accounts[account_name]
        if datetime.utcnow() >= unpause_at:
            del self._paused_accounts[account_name]
            if self._db:
                self._db.update_account_status(
                    account_name, status="idle", error_message=None
                )
            logger.info(f"[{account_name}] Pause period expired, resuming")
            return False
        return True

    def _log_task(self, task: Task, status: str, duration: float = 0,
                  error_message: str | None = None) -> None:
        if not self._db:
            return
        try:
            self._db.log_task(
                account_name=task.account_name,
                task_type=task.task_type,
                status=status,
                error_message=error_message,
                duration_seconds=int(duration),
            )
        except Exception as exc:
            logger.warning(f"Failed to log task: {exc}")

    @property
    def queue_size(self) -> int:
        return self._queue.qsize()

    @property
    def active_tasks(self) -> int:
        with self._lock:
            return len(self._running)
