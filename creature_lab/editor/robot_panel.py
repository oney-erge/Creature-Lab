"""The editor's "Robot check-up" panel: show a published robot, replay its runs, run a check-up.

The check-up itself runs in a subprocess so the editor only loads MuJoCo when a robot is shown
in 3D. The panel never accepts a license on the user's behalf: a robot that is not downloaded
yet is fetched from a terminal, where its license notice is shown first.
"""

from __future__ import annotations

import json
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
_NO_REPLAYS = "(run a check-up first)"
#: How the real robots are listed in the editor's creature pickers (shown first).
PICKER_LABELS = {
    "Microduck · real robot": "microduck",
    "Unitree G1 humanoid · real robot": "unitree_g1",
}
#: Run folders worth replaying, in the order they are listed.
_ORDER = ("baseline", "shove", "grip", "battery", "payload")


def _launch(args: Sequence[str]) -> subprocess.Popen:
    return subprocess.Popen(  # noqa: S603 - fixed interpreter and our own arguments
        [sys.executable, "-c", _RUNNER, *args],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def find_replays(out_root: Path, robot_key: str | None = None) -> dict[str, Path]:
    """Label -> saved run folder, from the newest check-up of each robot under ``out_root``."""
    found: dict[str, Path] = {}
    if not out_root.is_dir():
        return found
    for key, info in ROBOTS.items():
        if robot_key is not None and key != robot_key:
            continue
        results = sorted(
            (p for p in out_root.glob(f"{key}*") if p.is_dir() and any(p.glob("*/checkup.json"))),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not results:
            continue
        runs: list[tuple[int, str, Path]] = []
        for run_dir in results[0].glob("*/runs/*/robot_run.json"):
            meta = json.loads(run_dir.read_text(encoding="utf-8"))["scenario"]
            name = run_dir.parent.name
            suffix = (
                " (falls)"
                if name.endswith("_fall")
                else " (stays up)"
                if name.endswith("_ok")
                else ""
            )
            policy = info.policy(meta["policy"]).title
            label = f"{info.title} · {policy}: {meta.get('title') or name}{suffix}"
            rank = next((i for i, word in enumerate(_ORDER) if name.startswith(word)), len(_ORDER))
            runs.append((rank, label, run_dir.parent))
        for _, label, path in sorted(runs, key=lambda item: (item[0], item[1])):
            found[label] = path
    return found


class RobotCheckupPanel:
    """A collapsed folder: pick a robot, see it in 3D, replay its runs, run a check-up."""

    def __init__(
        self,
        gui: Any,
        *,
        stage: Any = None,
        out_root: Path = Path("outputs") / "checkup",
        launcher: Callable[[Sequence[str]], Any] = _launch,
        opener: Callable[[str], Any] = webbrowser.open,
        installed: Callable[[str], bool] = is_installed,
        missing: Callable[[], list[str]] = missing_extra,
    ) -> None:
        self._stage = stage
        self._out_root = out_root
        self._launcher = launcher
        self._opener = opener
        self._installed = installed
        self._missing = missing
        self._process: Any = None
        self._report: Path | None = None
        self._replays: dict[str, Path] = {}
        self._labels = {info.title: key for key, info in ROBOTS.items()}
        with gui.add_folder("Real robots: Microduck, Unitree G1", expand_by_default=False):
            gui.add_markdown(
                "Real published robots with their real trained policies. **Show** one in the 3D "
                "view, **replay** the saved runs of a check-up, or **run** a check-up: it shoves "
                "the robot, explains every fall, and opens a report. A simulation, not the "
                "hardware."
            )
            self._choice = gui.add_dropdown(
                "Robot", list(self._labels), initial_value=next(iter(self._labels))
            )
            self._show_button = gui.add_button("Show robot in 3D", color="blue")
            self._replay_choice = gui.add_dropdown(
                "Replay", [_NO_REPLAYS], initial_value=_NO_REPLAYS
            )
            self._replay_button = gui.add_button("Replay in 3D")
            self._follow = gui.add_checkbox("Camera follows the robot", initial_value=True)
            self._back_button = gui.add_button("Back to my creature")
            self._back_button.visible = False
            self._run_button = gui.add_button("Run robot check-up", color="blue")
            self._status = gui.add_markdown("")
        self._show_button.on_click(lambda _event: self.show_robot())
        self._replay_button.on_click(lambda _event: self.replay())
        self._back_button.on_click(lambda _event: self.back())
        self._follow.on_update(lambda _event: self._set_follow())
        self._run_button.on_click(lambda _event: self.start())
        self._refresh_replays()

    @property
    def running(self) -> bool:
        return self._process is not None

    # ---- 3D view -------------------------------------------------------------------------
    def _ready(self, key: str, title: str) -> bool:
        """Say what is missing and return False, or return True when ``key`` can be shown/run."""
        missing = self._missing()
        if missing:
            self._status.content = (
                f"Missing {', '.join(missing)}. Install the extra, then restart the editor: "
                "`uv sync --inexact --extra robots`"
            )
            return False
        if not self._installed(key):
            command = f"creature-lab robots fetch {key.replace('_', '-')}"
            self._status.content = (
                f"{title} is not downloaded yet. Run `{command}` in a terminal once: it shows "
                "the model's license and asks before downloading."
            )
            return False
        return True

    def _refresh_replays(self) -> None:
        self._replays = find_replays(self._out_root)
        options = list(self._replays) or [_NO_REPLAYS]
        self._replay_choice.options = tuple(options)
        if self._replay_choice.value not in options:
            self._replay_choice.value = options[0]

    def _set_follow(self) -> None:
        if self._stage is not None:
            self._stage.follow = bool(self._follow.value)

    def show_robot(self) -> None:
        key = self._labels[self._choice.value]
        if self._stage is None or not self._ready(key, self._choice.value):
            return
        try:
            self._stage.show(key)
        except Exception as error:  # a model that fails to load must not break the editor
            self._status.content = f"Could not show {self._choice.value}: {error}"
            return
        self._set_follow()
        self._back_button.visible = True
        self._status.content = f"Showing {self._choice.value}. Pick a replay to watch it move."

    def replay(self) -> None:
        label = self._replay_choice.value
        path = self._replays.get(label)
        if self._stage is None or path is None:
            self._status.content = "No saved runs yet. Click **Run robot check-up** first."
            return
        from creature_lab.robots.types import RobotRun

        run = RobotRun.read(path)
        key = run.scenario.robot
        if not self._ready(key, ROBOTS[key].title):
            return
        try:
            if self._stage.active and self._stage.robot == key:
                self._stage.play(run)
            else:
                self._stage.show(key, run)
        except Exception as error:
            self._status.content = f"Could not replay: {error}"
            return
        self._set_follow()
        self._back_button.visible = True
        self._status.content = f"Replaying: {label}"

    def back(self) -> None:
        if self._stage is not None:
            self._stage.hide()
        self._back_button.visible = False
        self._status.content = "Back to your creature."

    # ---- entry point from the creature pickers -------------------------------------------
    @property
    def showing(self) -> bool:
        return self._stage is not None and self._stage.active

    def can_open(self, key: str) -> bool:
        """True when ``key`` is downloaded and the extra is installed (no message side effects)."""
        return self._stage is not None and not self._missing() and self._installed(key)

    def open_robot(self, key: str) -> str:
        """Show ``key`` and play its newest saved baseline walk; returns a one-line status."""
        title = ROBOTS[key].title
        if self._stage is None:
            return "The 3D robot view is not available in this editor."
        if not self._ready(key, title):
            return self._status.content
        from creature_lab.robots.types import RobotRun

        baseline = next(
            (
                path
                for path in find_replays(self._out_root, key).values()
                if path.name == "baseline"
            ),
            None,
        )
        try:
            self._stage.show(key, RobotRun.read(baseline) if baseline else None)
        except Exception as error:  # a model that fails to load must not break the editor
            self._status.content = f"Could not show {title}: {error}"
            return self._status.content
        self._choice.value = title
        self._set_follow()
        self._back_button.visible = True
        self._refresh_replays()
        if baseline is None:
            message = (
                f"Showing {title}. Open Real robots and click Run robot check-up to see it walk, "
                "get shoved, and fall."
            )
        else:
            message = (
                f"{title} walking with its trained policy. Open Real robots to replay the shoves "
                "and falls, or pick a creature in Start from to design your own."
            )
        self._status.content = message
        return message

    # ---- check-up subprocess -------------------------------------------------------------
    def start(self) -> None:
        if self.running:
            self._status.content = "A check-up is already running."
            return
        key = self._labels[self._choice.value]
        if not self._ready(key, self._choice.value):
            return
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        out = self._out_root / f"{key}-{stamp}"
        self._report = out / "report.html"
        self._process = self._launcher(
            ["robots", "checkup", key.replace("_", "-"), "--out", str(out)]
        )
        self._run_button.disabled = True
        self._status.content = f"Running the {self._choice.value} check-up…"

    def tick(self, dt: float = 0.0) -> None:
        """Call regularly: advances a replay and notices when the check-up has finished."""
        if self._stage is not None and dt:
            self._stage.tick(dt)
        if self._process is None or self._process.poll() is None:
            return
        code, report = self._process.returncode, self._report
        self._process, self._report = None, None
        self._run_button.disabled = False
        if code == 0 and report is not None and report.exists():
            self._refresh_replays()
            self._status.content = (
                f"Done. Report: `{report}`. Pick a replay above to watch the runs in 3D."
            )
            self._opener(report.resolve().as_uri())
        else:
            self._status.content = (
                f"The check-up stopped (exit code {code}). Run `creature-lab robots checkup` "
                "in a terminal to see why."
            )
