"""Tests for the background job manager used by async simulate/robustness."""

from __future__ import annotations

import threading
import time

import pytest

from creature_lab.editor.jobs import EditorJobManager, JobCancelled, ProgressReporter


def _wait_until(predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("condition was not met within timeout")


def test_job_completes_and_reports_result():
    manager = EditorJobManager()
    started = manager.start(lambda reporter: 42)
    assert started is True

    _wait_until(lambda: manager.status().state == "completed")
    status = manager.status()
    assert status.result == 42
    assert status.progress == 1.0
    assert status.error is None


def test_job_reports_progress_while_running():
    gate = threading.Event()

    def work(reporter: ProgressReporter):
        reporter.report(0.25, "quarter done")
        gate.wait(timeout=2.0)
        return "done"

    manager = EditorJobManager()
    manager.start(work)
    _wait_until(lambda: manager.status().progress >= 0.25)
    status = manager.status()
    assert status.state == "running"
    assert status.message == "quarter done"
    gate.set()
    _wait_until(lambda: manager.status().state == "completed")


def test_job_can_be_cancelled_cooperatively():
    def work(reporter: ProgressReporter):
        for _ in range(1000):
            reporter.check_cancelled()
            time.sleep(0.001)
        return "should not reach here"

    manager = EditorJobManager()
    manager.start(work)
    _wait_until(lambda: manager.status().state == "running")
    manager.cancel()
    _wait_until(lambda: manager.status().state == "cancelled")
    assert manager.status().result is None


def test_cancel_request_is_visible_until_worker_acknowledges_it():
    entered = threading.Event()
    release = threading.Event()

    def work(reporter: ProgressReporter):
        entered.set()
        assert release.wait(2)
        reporter.check_cancelled()

    manager = EditorJobManager()
    assert manager.start(work)
    assert entered.wait(2)
    job_id = manager.status().job_id
    manager.cancel()
    waiting = manager.status()
    assert waiting.job_id == job_id
    assert waiting.state == "running"
    assert waiting.cancel_requested is True
    release.set()
    _wait_until(lambda: manager.status().state == "cancelled")
    assert manager.status().job_id == job_id


def test_job_failure_is_captured_not_raised():
    def work(reporter: ProgressReporter):
        raise ValueError("boom")

    manager = EditorJobManager()
    manager.start(work)
    _wait_until(lambda: manager.status().state == "failed")
    assert "boom" in manager.status().error


def test_cannot_start_a_second_job_while_one_is_running():
    gate = threading.Event()

    def work(reporter: ProgressReporter):
        gate.wait(timeout=2.0)
        return "first"

    manager = EditorJobManager()
    manager.start(work)
    _wait_until(lambda: manager.status().state == "running")

    started_again = manager.start(lambda reporter: "second")
    assert started_again is False

    gate.set()
    _wait_until(lambda: manager.status().state == "completed")
    assert manager.status().result == "first"


def test_clear_resets_finished_job_to_idle():
    manager = EditorJobManager()
    manager.start(lambda reporter: "x")
    _wait_until(lambda: manager.status().state == "completed")

    manager.clear()
    assert manager.status().state == "idle"


def test_clear_is_a_no_op_while_running():
    gate = threading.Event()
    manager = EditorJobManager()
    manager.start(lambda reporter: gate.wait(timeout=2.0))
    _wait_until(lambda: manager.status().state == "running")

    manager.clear()
    assert manager.status().state == "running"
    gate.set()
    _wait_until(lambda: manager.status().state == "completed")


def test_status_snapshot_is_a_copy_not_a_live_reference():
    manager = EditorJobManager()
    manager.start(lambda reporter: "x")
    _wait_until(lambda: manager.status().state == "completed")

    snap1 = manager.status()
    manager.clear()
    snap2 = manager.status()
    assert snap1.state == "completed"
    assert snap2.state == "idle"


def test_progress_reporter_check_cancelled_raises():
    event = threading.Event()
    reporter = ProgressReporter(event, lambda f, m: None)
    reporter.check_cancelled()  # no-op, not cancelled yet
    event.set()
    with pytest.raises(JobCancelled):
        reporter.check_cancelled()


def test_shutdown_cancels_and_joins_worker():
    manager = EditorJobManager()

    def work(reporter: ProgressReporter):
        while True:
            reporter.check_cancelled()
            time.sleep(0.001)

    manager.start(work)
    _wait_until(lambda: manager.is_running)

    assert manager.shutdown(timeout=1.0) is True
    assert manager.status().state == "cancelled"
