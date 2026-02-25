"""Single-threaded task queue for synchronous job execution.

Playwright's sync API is bound to the thread where ``sync_playwright()``
was called.  **Any** Playwright call from a different thread raises
``Error: Cannot switch to a different thread``.

This module therefore provides a simple ``queue.Queue`` wrapper whose
``process_next()`` method pops one task and executes it **synchronously**
on the caller's thread (the main thread).  There are no worker threads,
no ``ThreadPoolExecutor``, and no background draining loop.

APScheduler and Flask routes **only** call ``submit()`` (which is
thread-safe — ``queue.Queue.put`` is internally locked).  The main
thread's ``run_forever()`` loop calls ``process_next()`` each iteration
to actually execute the work.
"""

from __future__ import annotations

import time as _time
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
    timeout_seconds: int = 600


class QueueHandler:
    """Single-threaded task queue.

    * ``submit(task)`` — thread-safe enqueue (called from any thread).
    * ``process_next()`` — dequeue and execute one task **synchronously**
      on the calling thread.  Must be called from the main thread.
    * One task per account at a time — if the popped task's account is
      busy, the task is re-queued with a short delay.
    """

    def __init__(self, error_handling: dict | None = None,
                 db=None, notifier=None, **_kw):
        self._queue: Queue[Task] = Queue()
        self._error_handling = error_handling or {}
        self._db = db
        self._notifier = notifier
        self._paused_accounts: dict[str, datetime] = {}
        self._busy_accounts: set[str] = set()

        # Restore paused accounts from a previous run so they don't
        # accidentally resume when the process restarts.
        self._load_paused_accounts()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def submit(self, task: Task) -> None:
        """Add a task to the queue (thread-safe)."""
        self._queue.put(task)
        logger.debug(
            f"Queued task: {task.task_type} for {task.account_name} "
            f"(queue size: ~{self._queue.qsize()})"
        )

    def process_next(self) -> bool:
        """Pop and execute one task synchronously.  Returns True if work was done.

        Call this from the **main thread** inside the ``run_forever()`` loop.
        """
        try:
            task = self._queue.get_nowait()
        except Empty:
            return False

        # Skip paused accounts
        if self._is_account_paused(task.account_name):
            logger.debug(
                f"Skipping task {task.task_type} for paused account {task.account_name}"
            )
            return False

        # One task per account — re-queue if busy
        if task.account_name in self._busy_accounts:
            logger.debug(
                f"Account {task.account_name} is busy — "
                f"re-queuing {task.task_type} task"
            )
            self._queue.put(task)
            return False

        self._busy_accounts.add(task.account_name)
        try:
            self._run_task(task)
        finally:
            self._busy_accounts.discard(task.account_name)

        return True

    def start(self) -> None:
        """No-op for backwards compatibility.

        The old QueueHandler spawned a background worker thread here.
        The new single-threaded design doesn't need it — ``process_next()``
        is called directly from the main loop.
        """
        logger.info("Queue handler ready (single-threaded mode)")

    def stop(self) -> None:
        """No-op for backwards compatibility."""
        logger.info("Queue handler stopped")

    # ------------------------------------------------------------------
    # Task execution (runs on caller's thread = main thread)
    # ------------------------------------------------------------------
    def _run_task(self, task: Task) -> None:
        task.status = TaskStatus.RUNNING
        if self._db:
            self._db.update_account_status(task.account_name, status="running")

        start = _time.monotonic()
        try:
            result = task.callback(*task.args, **task.kwargs)
            duration = _time.monotonic() - start

            # Enforce timeout via wall-clock check (the callback itself
            # may honour internal timeouts, but this is a safety net).
            if duration > task.timeout_seconds:
                raise TimeoutError(
                    f"Task {task.task_type} for {task.account_name} "
                    f"took {duration:.0f}s (limit {task.timeout_seconds}s)"
                )

            task.status = TaskStatus.COMPLETED
            task.result = result

            if result:
                self._log_task(task, "success", duration=duration)
            else:
                logger.warning(
                    f"Task {task.task_type} for {task.account_name} "
                    f"returned failure ({duration:.1f}s)"
                )
                self._log_task(task, "failed", duration=duration)

            if self._db:
                self._db.update_account_status(task.account_name, status="idle")

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
                max_backoff = self._error_handling.get("max_backoff", 300)
                delay = min(backoff * (2 ** (task.retry_count - 1)), max_backoff)
                logger.info(
                    f"Retrying {task.task_type} for {task.account_name} "
                    f"in {delay}s (attempt {task.retry_count + 1}/{task.max_retries})"
                )
                self._log_task(task, "failed", duration=duration,
                               error_message=str(exc))
                # Re-queue immediately — the main loop's sleep provides
                # the effective backoff.  For longer delays the task will
                # simply sit in the queue until picked up again.
                self._queue.put(task)
            else:
                task.status = TaskStatus.FAILED
                self._log_task(task, "failed", duration=duration,
                               error_message=str(exc))
                self._pause_account(task.account_name, str(exc))

    # ------------------------------------------------------------------
    # Pause / unpause
    # ------------------------------------------------------------------
    def _load_paused_accounts(self) -> None:
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
                    unpause_at = datetime.utcnow() + timedelta(minutes=pause_minutes)
                    self._paused_accounts[acct.account_name] = unpause_at
                    logger.info(
                        f"[{acct.account_name}] Restored paused state from DB "
                        f"(will unpause around {unpause_at.strftime('%H:%M')})"
                    )
        except Exception as exc:
            logger.warning(f"Could not load paused accounts from DB: {exc}")

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
            self._paused_accounts.pop(account_name, None)
            if self._db:
                self._db.update_account_status(
                    account_name, status="idle", error_message=None
                )
            logger.info(f"[{account_name}] Pause period expired, resuming")
            return False
        return True

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # Properties (used by Flask API routes for status display)
    # ------------------------------------------------------------------
    @property
    def queue_size(self) -> int:
        return self._queue.qsize()

    @property
    def active_tasks(self) -> int:
        return len(self._busy_accounts)
