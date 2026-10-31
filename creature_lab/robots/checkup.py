"""The robot check-up: a fixed set of tests that shows where a policy breaks, and why."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pydantic import Field

from creature_lab import VERSION
from creature_lab.io_utils import atomic_write_text
from creature_lab.robots.analysis import RunAnalysis, analyze
from creature_lab.robots.api import run_scenario
from creature_lab.robots.catalog import RobotInfo, robot_info
from creature_lab.robots.types import RobotRun, Scenario
from creature_lab.schema.base import StrictModel

#: Shoves per strength, spread evenly across one stride (alternating sides).
SHOVE_PHASES = 8


@dataclass(frozen=True)
class _Levels:
    shoves_n: tuple[float, ...]
    grips: tuple[float, ...]
    batteries_v: tuple[float, ...]
    payloads_kg: tuple[float, ...]


_LEVELS = {
    "microduck": _Levels((1, 2, 3, 4, 6, 8), (0.5, 0.3, 0.15), (6.5, 6.0), ()),
    "unitree_g1": _Levels((50, 100, 150, 200, 300), (0.5, 0.3, 0.15), (), (3, 6, 10)),
}


class ShoveRow(StrictModel):
    """Results of every shove at one strength."""

    force_n: float
    total: int
    stayed_up: int
    got_up: int
    stayed_down: int
    #: The failing run saved for filming, if any shove at this strength made it fall.
    example_fall_run: str | None = None
    example_ok_run: str | None = None

    @property
    def survival(self) -> float:
        return self.stayed_up / self.total


class ConditionResult(StrictModel):
    key: str
    label: str
    passed: bool
    distance_m: float
    #: Distance walked relative to the baseline run.
    relative_distance: float
    analysis: RunAnalysis
    run: str


class Checkup(StrictModel):
    """Everything a report or video needs about one robot + policy."""

    schema_id: str = "creature-lab.robot-checkup/1"
    creature_lab: str = VERSION
    robot: str
    policy: str
    command: float
    baseline: RunAnalysis
    baseline_run: str
    shoves: list[ShoveRow]
    conditions: list[ConditionResult] = Field(default_factory=list)

    @property
    def never_falls_up_to_n(self) -> float | None:
        """Strongest shove (all tested strengths up to it) that never makes the robot fall."""
        best = None
        for row in self.shoves:
            if row.stayed_up != row.total:
                break
            best = row.force_n
        return best

    @property
    def never_stays_down_up_to_n(self) -> float | None:
        """Strongest shove (and all weaker ones) it always ends up standing after."""
        best = None
        for row in self.shoves:
            if row.stayed_down:
                break
            best = row.force_n
        return best


def _save(run: RobotRun, folder: Path, name: str) -> str:
    run.save(folder / "runs" / name)
    return name


def run_checkup(
    robot: str,
    policy: str,
    out_dir: Path,
    *,
    progress: Callable[[str], None] | None = None,
    command: float | None = None,
) -> Checkup:
    """Run the full check-up and save its featured runs plus ``checkup.json`` under ``out_dir``."""
    info: RobotInfo = robot_info(robot)
    levels = _LEVELS[robot]
    out_dir = Path(out_dir)
    speed = info.walk_command if command is None else command
    say = progress or (lambda message: None)

    def base(**changes) -> Scenario:
        return Scenario(robot=robot, policy=policy, command=speed, **changes)

    say("baseline walk")
    baseline_run = run_scenario(base(title="Baseline walk"))
    baseline = analyze(baseline_run)
    baseline_name = _save(baseline_run, out_dir, "baseline")

    shoves = []
    for force in levels.shoves_n:
        say(f"shoves at {force:g} N")
        outcomes = {"stayed_up": 0, "got_up": 0, "stayed_down": 0}
        example_fall = example_ok = None
        for phase in range(SHOVE_PHASES):
            scenario = base(
                push_n=force,
                push_side="left" if phase % 2 == 0 else "right",
                push_at_s=4.0 + phase * info.gait_period_s / SHOVE_PHASES,
                title=f"{force:g} N shove",
            )
            run = run_scenario(scenario)
            result = analyze(run)
            if not result.fell:
                outcomes["stayed_up"] += 1
                if example_ok is None:
                    example_ok = _save(run, out_dir, f"shove_{force:g}N_ok")
            else:
                outcomes["got_up" if result.outcome == "fell_and_got_up" else "stayed_down"] += 1
                if example_fall is None:
                    example_fall = _save(run, out_dir, f"shove_{force:g}N_fall")
        shoves.append(
            ShoveRow(
                force_n=force,
                total=SHOVE_PHASES,
                example_fall_run=example_fall,
                example_ok_run=example_ok,
                **outcomes,
            )
        )

    conditions = []

    def condition(key: str, label: str, **changes) -> None:
        say(label)
        run = run_scenario(base(title=label, **changes))
        result = analyze(run)
        reference = baseline.distance_m or 1.0
        conditions.append(
            ConditionResult(
                key=key,
                label=label,
                passed=not result.fell,
                distance_m=result.distance_m,
                relative_distance=result.distance_m / reference,
                analysis=result,
                run=_save(run, out_dir, key),
            )
        )

    for grip in levels.grips:
        condition(f"grip_{grip:g}", f"Floor grip at {grip:g}× normal", grip=grip)
    for volts in levels.batteries_v:
        condition(f"battery_{volts:g}V", f"{volts:g} V battery (7.4 V is full)", battery_v=volts)
    for kilos in levels.payloads_kg:
        condition(f"payload_{kilos:g}kg", f"Carrying {kilos:g} kg", payload_kg=kilos)

    result = Checkup(
        robot=robot,
        policy=policy,
        command=speed,
        baseline=baseline,
        baseline_run=baseline_name,
        shoves=shoves,
        conditions=conditions,
    )
    atomic_write_text(out_dir / "checkup.json", result.model_dump_json(indent=2) + "\n")
    return result


def read_checkup(out_dir: Path) -> Checkup:
    return Checkup.model_validate(json.loads((Path(out_dir) / "checkup.json").read_text("utf-8")))
