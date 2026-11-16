"""Background jobs the app starts: downloading a robot and running a check-up."""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import threading
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from creature_lab.io_utils import atomic_write_text
from creature_lab.robots.catalog import all_robots
from creature_lab.robots.checkup import planned_steps
from creature_lab.robots.fetch import ensure_robot

_RUNNER = "from creature_lab.cli import app; app()"
_FETCH_STEP = re.compile(r"^\[(\d+)/(\d+)\]")
#: Finished jobs kept so the page can read their last state.
_KEEP = 20
logger = logging.getLogger(__name__)


class RecoveryError(RuntimeError):
    """A previous job cannot be identified safely from its durable record."""


@dataclass
class Job:
    id: str
    kind: str
    robot: str
    state: str = "running"  # running | cancelling | done | failed | cancelled
    progress: float = 0.0
    message: str = ""
    error: str | None = None
    #: For a check-up: the results folder it writes.
    output: str | None = None
    log: list[str] = field(default_factory=list)
    cancel_requested: bool = False
    process: subprocess.Popen | None = field(default=None, repr=False)
    process_pid: int | None = None
    outcome_unknown: bool = False
    cancel_signal_failed: bool = False
    cancel_signal_sent: bool = False

    def snapshot(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "robot": self.robot,
            "state": self.state,
            "progress": round(self.progress, 3),
            "message": self.message,
            "error": self.error,
            "output": self.output,
            "cancel_requested": self.cancel_requested,
            "process_pid": self.process_pid,
            "outcome_unknown": self.outcome_unknown,
            "cancel_signal_failed": self.cancel_signal_failed,
            "cancel_signal_sent": self.cancel_signal_sent,
        }


def _launch(args: Sequence[str]) -> subprocess.Popen:
    return subprocess.Popen(  # noqa: S603 - fixed interpreter and our own arguments
        [sys.executable, "-c", _RUNNER, *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )


class Jobs:
    """Starts and tracks jobs; at most one job per kind and robot runs at a time."""

    def __init__(
        self,
        checkup_root: Path,
        *,
        fetch: Callable[..., Path] = ensure_robot,
        launcher: Callable[[Sequence[str]], subprocess.Popen] = _launch,
    ) -> None:
        self._root = Path(checkup_root)
        self._fetch = fetch
        self._launcher = launcher
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._recovery_errors: list[str] = []
        self._load()

    def _persist(self, job: Job) -> None:
        atomic_write_text(self._root / ".jobs" / f"{job.id}.json", json.dumps(job.snapshot()))

    def _load(self) -> None:
        for path in (self._root / ".jobs").glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if (
                    not isinstance(data, dict)
                    or not re.fullmatch(r"[0-9a-f]{10}", path.stem)
                    or data.get("id") != path.stem
                    or data.get("kind") not in {"download", "checkup"}
                    or not isinstance(data.get("robot"), str)
                    or not re.fullmatch(r"[a-z][a-z0-9_]{1,39}", data["robot"])
                ):
                    raise ValueError("invalid job identity")
                job = Job(
                    id=data["id"],
                    kind=data["kind"],
                    robot=data["robot"],
                    state=data.get("state", "failed"),
                    progress=float(data.get("progress", 0)),
                    message=str(data.get("message", "")),
                    error=data.get("error"),
                    output=data.get("output"),
                    cancel_requested=bool(data.get("cancel_requested")),
                    process_pid=data.get("process_pid"),
                    outcome_unknown=bool(data.get("outcome_unknown")),
                    cancel_signal_failed=bool(data.get("cancel_signal_failed")),
                    cancel_signal_sent=bool(data.get("cancel_signal_sent")),
                )
                if job.state not in {
                    "running",
                    "cancelling",
                    "done",
                    "failed",
                    "cancelled",
                    "interrupted",
                }:
                    raise ValueError("invalid job state")
                if job.state in {"running", "cancelling"}:
                    job.state = "interrupted"
                    job.outcome_unknown = job.kind == "checkup"
                    job.message = (
                        "The server restarted. Confirm the check-up process has stopped "
                        "before retrying."
                        if job.outcome_unknown
                        else "The server restarted during the download; retry it."
                    )
                    self._persist(job)
                self._jobs[job.id] = job
            except (OSError, ValueError, KeyError, TypeError) as error:
                logger.warning("Could not recover job record %s: %s", path, error)
                self._recovery_errors.append(path.name)

    def get(self, job_id: str) -> Job:
        with self._lock:
            return self._jobs[job_id]

    def active(self) -> list[Job]:
        """The jobs still running, so a page that was reloaded can follow them again."""
        with self._lock:
            return [
                j
                for j in self._jobs.values()
                if j.state in {"running", "cancelling"} or j.outcome_unknown
            ]

    def running(self, kind: str, robot: str) -> Job | None:
        with self._lock:
            return next(
                (
                    j
                    for j in self._jobs.values()
                    if j.kind == kind
                    and j.robot == robot
                    and (j.state in {"running", "cancelling"} or j.outcome_unknown)
                ),
                None,
            )

    def _register(self, kind: str, robot: str) -> tuple[Job, bool]:
        with self._lock:
            if self._recovery_errors:
                raise RecoveryError(
                    "Cannot safely start a job because saved job records could not be read: "
                    + ", ".join(self._recovery_errors)
                    + ". Confirm any previous processes have stopped and repair the records."
                )
            existing = next(
                (
                    j
                    for j in self._jobs.values()
                    if j.kind == kind
                    and j.robot == robot
                    and (j.state in {"running", "cancelling"} or j.outcome_unknown)
                ),
                None,
            )
            if existing is not None:
                return existing, False
            job = Job(id=uuid.uuid4().hex[:10], kind=kind, robot=robot)
            if kind == "checkup":
                job.output = f"{robot}-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{job.id}"
                job.message = "Starting…"
            else:
                job.message = "Starting the download…"
            self._persist(job)
            self._jobs[job.id] = job
            for stale in [
                j
                for j in self._jobs.values()
                if j.state not in {"running", "cancelling"} and not j.outcome_unknown
            ][:-_KEEP]:
                del self._jobs[stale.id]
        return job, True

    # ---- download ------------------------------------------------------------------------
    def start_download(self, robot: str) -> Job:
        """Download a robot's files. The caller has already shown the license and got consent."""
        job, created = self._register("download", robot)
        if not created:
            return job
        threading.Thread(target=self._download, args=(job,), daemon=True).start()
        return job

    def _download(self, job: Job) -> None:
        def progress(message: str) -> None:
            job.message = message
            step = _FETCH_STEP.match(message)
            if step:
                job.progress = int(step.group(1)) / max(int(step.group(2)), 1)

        try:
            self._fetch(job.robot, progress=progress)
        except Exception as error:  # noqa: BLE001 - background failures must have a terminal state
            logger.exception("Robot download failed")
            with self._lock:
                job.state, job.error = "failed", str(error)
                self._persist(job)
            return
        with self._lock:
            job.state, job.progress, job.message = "done", 1.0, "Downloaded and verified."
            self._persist(job)

    # ---- check-up ------------------------------------------------------------------------
    def start_checkup(self, robot: str) -> Job:
        job, created = self._register("checkup", robot)
        if not created:
            return job
        assert job.output is not None  # Assigned with the durable admission record.
        out = self._root / job.output
        threading.Thread(target=self._checkup, args=(job, out), daemon=True).start()
        return job

    def _checkup(self, job: Job, out: Path) -> None:
        total = max(planned_steps(job.robot), 1)
        steps = 0
        try:
            process = self._launcher(
                ["robots", "checkup", job.robot.replace("_", "-"), "--out", str(out)]
            )
            with self._lock:
                job.process = process
                job.process_pid = getattr(process, "pid", None)
                try:
                    self._persist(job)
                except OSError as error:
                    # The subprocess still exists; retain and monitor its owner.
                    # The last durable running record recovers as unknown.
                    job.error = f"Could not save process status: {error}"
                should_stop = job.cancel_requested
            if should_stop:
                self._signal_stop(job, process)
            for raw in process.stdout or []:
                line = raw.rstrip()
                job.log.append(line)
                # Each test the CLI starts prints one indented line, e.g. "  shoves at 2 N".
                if line.startswith("  ") and line.strip():
                    steps += 1
                    if not job.cancel_requested:
                        job.message = line.strip()
                    job.progress = min(steps / total, 0.99)
            code = process.wait()
        except OSError as error:
            with self._lock:
                # A failed pipe/status read is not proof the subprocess exited.
                if job.process is not None and job.process.poll() is None:
                    job.state = "interrupted"
                    job.outcome_unknown = True
                    job.message = "Check that the check-up process has stopped before retrying."
                else:
                    job.state = "failed"
                job.error = str(error)
                self._persist(job)
            return
        with self._lock:
            if code == 0 and (out / "report.html").exists():
                job.state, job.progress, job.message = "done", 1.0, "Check-up finished."
            elif job.cancel_requested and job.cancel_signal_sent:
                job.state, job.message = "cancelled", "Check-up stopped."
            else:
                tail = " ".join(job.log[-3:]).strip()
                job.state = "failed"
                job.error = f"The check-up stopped (exit code {code}). {tail}".strip()
            job.process = None
            self._persist(job)

    def _signal_stop(self, job: Job, process: subprocess.Popen) -> None:
        # Serialize signaling with the terminal decision: if the process already
        # finished, a later stop request must not relabel its outcome as cancelled.
        with self._lock:
            if job.state != "cancelling" or job.process is not process:
                return
            try:
                process.terminate()
                job.cancel_signal_sent = True
            except ProcessLookupError:
                pass  # The worker will report the already-exited process.
            except OSError as error:
                job.cancel_signal_failed = True
                job.message = "Could not send the stop signal; the check-up is still running."
                job.error = str(error)
            try:
                self._persist(job)
            except OSError:
                # A restarted server treats the last durable active state as unknown.
                logger.exception("Could not save the stop signal outcome")

    def cancel(self, job_id: str) -> Job:
        """Request a stop only for a check-up subprocess owned by this manager."""
        with self._lock:
            job = self._jobs[job_id]
            if job.kind != "checkup":
                raise ValueError(
                    "Downloads cannot be stopped safely; wait for verification to finish."
                )
            if job.state == "cancelling" and not job.cancel_signal_failed:
                return job
            if job.state not in {"running", "cancelling"}:
                return job
            previous_state = (
                job.state,
                job.cancel_requested,
                job.cancel_signal_failed,
                job.message,
                job.error,
            )
            if job.cancel_signal_failed:
                job.error = None
            job.cancel_requested = True
            job.cancel_signal_failed = False
            job.state = "cancelling"
            job.message = "Stopping the check-up…"
            process = job.process
            try:
                self._persist(job)
            except OSError as error:
                (
                    job.state,
                    job.cancel_requested,
                    job.cancel_signal_failed,
                    job.message,
                    job.error,
                ) = previous_state
                raise RecoveryError(
                    "Could not save the stop request; the check-up is still running."
                ) from error
        if process is not None:
            self._signal_stop(job, process)
        return job

    def acknowledge_interruption(self, job_id: str) -> Job:
        """Record an operator's confirmation; never signal an unowned PID."""
        with self._lock:
            job = self._jobs[job_id]
            if job.state != "interrupted" or not job.outcome_unknown:
                raise ValueError("This job does not need interruption review.")
            job.outcome_unknown = False
            job.message = "Process stop confirmed; the interrupted outcome remains unknown."
            self._persist(job)
            return job


def known_robot(key: str) -> bool:
    return key in all_robots()
