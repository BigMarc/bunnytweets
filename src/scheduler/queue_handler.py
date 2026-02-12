"""Thread-safe task queue for asynchronous job execution."""

import threading
from concurrent.futures import ThreadPoolExecutor, Future
from dataclasses import dataclass, field
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


class QueueHandler:
    """Manages a thread pool + queue for account tasks.

    Ensures only one task per account runs at a time (to avoid concurrent
    Selenium operations on the same browser profile).
    """

    def __init__(self, max_workers: int = 5):
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self._queue: Queue[Task] = Queue()
        self._running: dict[str, Future] = {}
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._worker_thread: threading.Thread | None = None

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
                    fut = self._running.pop(k)
                    exc = fut.exception()
                    if exc:
                        logger.error(f"Task for {k} failed: {exc}")

            # Pull next task from queue
            try:
                task = self._queue.get(timeout=1)
            except Empty:
                continue

            with self._lock:
                if task.account_name in self._running:
                    # Re-queue: only one task per account at a time
                    self._queue.put(task)
                    continue

                task.status = TaskStatus.RUNNING
                future = self.executor.submit(self._run_task, task)
                self._running[task.account_name] = future

    @staticmethod
    def _run_task(task: Task) -> Any:
        try:
            result = task.callback(*task.args, **task.kwargs)
            task.status = TaskStatus.COMPLETED
            task.result = result
            return result
        except Exception as exc:
            task.status = TaskStatus.FAILED
            task.error = exc
            logger.error(f"Task {task.task_type} for {task.account_name} failed: {exc}")
            raise

    @property
    def queue_size(self) -> int:
        return self._queue.qsize()

    @property
    def active_tasks(self) -> int:
        with self._lock:
            return len(self._running)
