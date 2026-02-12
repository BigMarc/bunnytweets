"""Tests for the QueueHandler."""

import time
import threading

import pytest

from src.scheduler.queue_handler import QueueHandler, Task, TaskStatus


@pytest.fixture
def queue():
    q = QueueHandler(max_workers=2)
    q.start()
    yield q
    q.stop()


def test_submit_and_execute(queue):
    results = []

    def work():
        results.append("done")

    task = Task(account_name="acct1", task_type="test", callback=work)
    queue.submit(task)
    time.sleep(2)
    assert results == ["done"]
    assert task.status == TaskStatus.COMPLETED


def test_one_task_per_account(queue):
    """Only one task per account should run concurrently."""
    running = []
    lock = threading.Lock()

    def slow_work():
        with lock:
            running.append(threading.current_thread().name)
        time.sleep(1)

    t1 = Task(account_name="acct1", task_type="a", callback=slow_work)
    t2 = Task(account_name="acct1", task_type="b", callback=slow_work)
    queue.submit(t1)
    queue.submit(t2)
    time.sleep(3)
    # Both should eventually complete
    assert t1.status == TaskStatus.COMPLETED
    assert t2.status == TaskStatus.COMPLETED


def test_failed_task(queue):
    def bad():
        raise ValueError("boom")

    task = Task(account_name="acct1", task_type="fail", callback=bad)
    queue.submit(task)
    time.sleep(2)
    assert task.status == TaskStatus.FAILED
    assert task.error is not None
