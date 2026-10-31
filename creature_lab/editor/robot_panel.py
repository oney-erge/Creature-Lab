"""The editor's "Robot check-up" panel: run a published robot's check-up from the browser.

The check-up runs in a subprocess so the editor never loads MuJoCo, and the panel never
accepts a license on the user's behalf: a robot that is not downloaded yet is fetched from a
terminal, where its license notice is shown first.
"""

from __future__ import annotations

import subprocess
import sys
import webbrowser
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from creature_lab.robots.catalog import ROBOTS
from creature_lab.robots.fetch import is_installed, missing_extra

_RUNNER = "from creature_lab.cli import app; app()"


def _launch(args: Sequence[str]) -> subprocess.Popen:
    return subprocess.Popen(  # noqa: S603 - fixed interpreter and our own arguments
        [sys.executable, "-c", _RUNNER, *args],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


class RobotCheckupPanel:
    """A collapsed folder with a robot picker and one button."""

    def __init__(
        self,
        gui: Any,
        *,
        out_root: Path = Path("outputs") / "checkup",
        launcher: Callable[[Sequence[str]], Any] = _launch,
        opener: Callable[[str], Any] = webbrowser.open,
        installed: Callable[[str], bool] = is_installed,
        missing: Callable[[], list[str]] = missing_extra,
    ) -> None:
        self._out_root = out_root
        self._launcher = launcher
        self._opener = opener
        self._installed = installed
        self._missing = missing
        self._process: Any = None
        self._report: Path | None = None
        self._labels = {info.title: key for key, info in ROBOTS.items()}
        with gui.add_folder("Robot check-up", expand_by_default=False, order=40):
            gui.add_markdown(
                "Shove a real published robot with its real trained policy and get a report "
                "that explains every fall. Runs in the background (about a minute) and opens "
                "in your browser. A simulation, not the hardware."
            )
            self._choice = gui.add_dropdown(
                "Robot", list(self._labels), initial_value=next(iter(self._labels))
            )
            self._button = gui.add_button("Run robot check-up", color="blue")
            self._status = gui.add_markdown("")
        self._button.on_click(lambda _event: self.start())

    @property
    def running(self) -> bool:
        return self._process is not None

    def start(self) -> None:
        if self.running:
            self._status.content = "A check-up is already running."
            return
        key = self._labels[self._choice.value]
        missing = self._missing()
        if missing:
            self._status.content = (
                f"Missing {', '.join(missing)}. Install the extra, then restart the editor: "
                "`uv sync --inexact --extra robots`"
            )
            return
        if not self._installed(key):
            command = f"creature-lab robots fetch {key.replace('_', '-')}"
            self._status.content = (
                f"{self._choice.value} is not downloaded yet. Run `{command}` in a terminal "
                "once: it shows the model's license and asks before downloading."
            )
            return
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        out = self._out_root / f"{key}-{stamp}"
        self._report = out / "report.html"
        self._process = self._launcher(
            ["robots", "checkup", key.replace("_", "-"), "--out", str(out)]
        )
        self._button.disabled = True
        self._status.content = f"Running the {self._choice.value} check-up…"

    def tick(self) -> None:
        """Call regularly: notices when the background check-up has finished."""
        if self._process is None or self._process.poll() is None:
            return
        code, report = self._process.returncode, self._report
        self._process, self._report = None, None
        self._button.disabled = False
        if code == 0 and report is not None and report.exists():
            self._status.content = f"Done. Report: `{report}`"
            self._opener(report.resolve().as_uri())
        else:
            self._status.content = (
                f"The check-up stopped (exit code {code}). Run `creature-lab robots checkup` "
                "in a terminal to see why."
            )
