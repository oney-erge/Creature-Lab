"""Run long operations (simulate, robustness sweeps) off the GUI callback thread.

Viser dispatches each button click as a callback; if that callback blocks until an
entire physics episode (or a 50-trial robustness sweep) finishes, nothing else can
update in the meantime — no progress bar, no elapsed timer, no way to cancel. The fix
is the usual one: run the actual work in a background thread and let the caller poll
:meth:`EditorJobManager.status` from wherever it already runs a loop (see
``editor/live.py``'s main loop, which already polls for external file changes).

``EditorJobManager`` is deliberately independent of Viser and physics: the callable it
runs receives a :class:`ProgressReporter` and returns any picklable-ish result. That
keeps this module trivially unit-testable with a plain function and a timer.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any, Literal

JobState = Literal["idle", "running", "completed", "cancelled", "failed"]


class JobCancelled(Exception):
    """Raised inside a job callable (via ``ProgressReporter.check_cancelled``) to
    unwind early once cancellation has been requested."""


class ProgressReporter:
    """Passed into a running job so it can report progress and notice cancellation."""

    def __init__(
        self, cancel_event: threading.Event, set_progress: Callable[[float, str], None]
    ) -> None:
        self._cancel_event = cancel_event
        self._set_progress = set_progress

    def report(self, fraction: float, message: str = "") -> None:
        """Record progress in [0, 1] and an optional status message."""
        self._set_progress(max(0.0, min(1.0, fraction)), message)

    @property
    def cancel_requested(self) -> bool:
        return self._cancel_event.is_set()

    def check_cancelled(self) -> None:
        """Raise ``JobCancelled`` if cancellation has been requested.

        Call this between expensive units of work (physics steps, trials) so a
        cancel request actually stops the job instead of only being observed after
        it would have finished anyway.
        """
        if self._cancel_event.is_set():
            raise JobCancelled


@dataclass
class JobStatus:
    """A snapshot of job state; safe to hold onto after the job moves on."""

    state: JobState = "idle"
    job_id: str | None = None
    cancel_requested: bool = False
    progress: float = 0.0
    message: str = ""
    started_at: float | None = None
    finished_at: float | None = None
    result: Any = None
    error: str | None = None

    @property
    def elapsed(self) -> float:
        if self.started_at is None:
            return 0.0
        end = self.finished_at if self.finished_at is not None else time.monotonic()
        return end - self.started_at

    @property
    def is_active(self) -> bool:
        return self.state == "running"


class EditorJobManager:
    """Runs at most one background job at a time and reports its status thread-safely."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._status = JobStatus()
        self._cancel_event = threading.Event()
        self._thread: threading.Thread | None = None

    def status(self) -> JobStatus:
        """A point-in-time copy; safe to read from any thread."""
        with self._lock:
            return replace(self._status)

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._status.state == "running"

    def start(self, fn: Callable[[ProgressReporter], Any]) -> bool:
        """Start ``fn`` in a background thread.

        Returns ``False`` without starting anything if a job is already running
        (callers should disable the triggering button while ``is_running``, but this
        guards the race regardless).
        """
        with self._lock:
            if self._status.state == "running":
                return False
            self._cancel_event = threading.Event()
            self._status = JobStatus(
                state="running", job_id=uuid.uuid4().hex, started_at=time.monotonic()
            )
        cancel_event = self._cancel_event

        def _set_progress(fraction: float, message: str) -> None:
            with self._lock:
                if self._status.state != "running":
                    return
                self._status.progress = fraction
                if message:
                    self._status.message = message

        reporter = ProgressReporter(cancel_event, _set_progress)

        def _run() -> None:
            try:
                result = fn(reporter)
            except JobCancelled:
                with self._lock:
                    self._status.state = "cancelled"
                    self._status.finished_at = time.monotonic()
                return
            except Exception as exc:  # noqa: BLE001 - surfaced to the UI, not swallowed
                # Some exceptions (e.g. Click/Typer's ``typer.Exit``) carry no message
                # by design - their text is a side effect printed elsewhere, which is
                # fine for a terminal but leaves the browser status line blank. Fall
                # back to the exception's type name so there's always something to show.
                message = str(exc) or f"{type(exc).__name__} (see server console for details)"
                with self._lock:
                    self._status.state = "failed"
                    self._status.error = message
                    self._status.finished_at = time.monotonic()
                return
            with self._lock:
                self._status.state = "completed"
                self._status.progress = 1.0
                self._status.result = result
                self._status.finished_at = time.monotonic()

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()
        return True

    def cancel(self) -> None:
        """Request cancellation of the running job (a no-op if none is running)."""
        with self._lock:
            if self._status.state == "running":
                self._status.cancel_requested = True
                self._cancel_event.set()

    def clear(self) -> None:
        """Reset a finished job back to idle. No-op while a job is still running."""
        with self._lock:
            if self._status.state != "running":
                self._status = JobStatus()

    def shutdown(self, timeout: float = 10.0) -> bool:
        """Request cancellation and wait for the worker before editor teardown.

        Returns whether the worker stopped within ``timeout``. Python threads cannot
        be killed safely, so job functions still need to honor ProgressReporter.
        """
        self.cancel()
        thread = self._thread
        if thread is None:
            return True
        thread.join(timeout=max(0.0, timeout))
        return not thread.is_alive()
