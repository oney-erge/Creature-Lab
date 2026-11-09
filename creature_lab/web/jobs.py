"""Background jobs the app starts: downloading a robot and running a check-up."""

from __future__ import annotations

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

from creature_lab.robots.catalog import ROBOTS
from creature_lab.robots.checkup import planned_steps
from creature_lab.robots.fetch import FetchError, ensure_robot

_RUNNER = "from creature_lab.cli import app; app()"
_FETCH_STEP = re.compile(r"^\[(\d+)/(\d+)\]")
#: Finished jobs kept so the page can read their last state.
_KEEP = 20


@dataclass
class Job:
    id: str
    kind: str
    robot: str
    state: str = "running"  # running | done | failed
    progress: float = 0.0
    message: str = ""
    error: str | None = None
    #: For a check-up: the results folder it writes.
    output: str | None = None
    log: list[str] = field(default_factory=list)

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

    def get(self, job_id: str) -> Job:
        return self._jobs[job_id]

    def running(self, kind: str, robot: str) -> Job | None:
        with self._lock:
            return next(
                (
                    j
                    for j in self._jobs.values()
                    if j.kind == kind and j.robot == robot and j.state == "running"
                ),
                None,
            )

    def _register(self, kind: str, robot: str) -> Job:
        job = Job(id=uuid.uuid4().hex[:10], kind=kind, robot=robot)
        with self._lock:
            self._jobs[job.id] = job
            for stale in [j for j in self._jobs.values() if j.state != "running"][:-_KEEP]:
                del self._jobs[stale.id]
        return job

    # ---- download ------------------------------------------------------------------------
    def start_download(self, robot: str) -> Job:
        """Download a robot's files. The caller has already shown the license and got consent."""
        existing = self.running("download", robot)
        if existing:
            return existing
        job = self._register("download", robot)
        job.message = "Starting the download…"
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
        except (FetchError, OSError) as error:
            job.state, job.error = "failed", str(error)
            return
        job.state, job.progress, job.message = "done", 1.0, "Downloaded and verified."

    # ---- check-up ------------------------------------------------------------------------
    def start_checkup(self, robot: str) -> Job:
        existing = self.running("checkup", robot)
        if existing:
            return existing
        job = self._register("checkup", robot)
        out = self._root / f"{robot}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        job.output = out.name
        job.message = "Starting…"
        threading.Thread(target=self._checkup, args=(job, out), daemon=True).start()
        return job

    def _checkup(self, job: Job, out: Path) -> None:
        total = max(planned_steps(job.robot), 1)
        steps = 0
        try:
            process = self._launcher(
                ["robots", "checkup", job.robot.replace("_", "-"), "--out", str(out)]
            )
            for raw in process.stdout or []:
                line = raw.rstrip()
                job.log.append(line)
                # Each test the CLI starts prints one indented line, e.g. "  shoves at 2 N".
                if line.startswith("  ") and line.strip():
                    steps += 1
                    job.message = line.strip()
                    job.progress = min(steps / total, 0.99)
            code = process.wait()
        except OSError as error:
            job.state, job.error = "failed", str(error)
            return
        if code == 0 and (out / "report.html").exists():
            job.state, job.progress, job.message = "done", 1.0, "Check-up finished."
        else:
            tail = " ".join(job.log[-3:]).strip()
            job.state = "failed"
            job.error = f"The check-up stopped (exit code {code}). {tail}".strip()


def known_robot(key: str) -> bool:
    return key in ROBOTS
