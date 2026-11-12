"""The robot check-up: a fixed set of tests that shows where a policy breaks, and why."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import numpy as np
from pydantic import Field

from creature_lab import VERSION
from creature_lab.io_utils import atomic_write_text
from creature_lab.robots.analysis import RunAnalysis, analyze, joint_text
from creature_lab.robots.catalog import CheckupLevels, RobotInfo, robot_info
from creature_lab.robots.terrain import course
from creature_lab.robots.terrain import key as terrain_key
from creature_lab.robots.terrain import label as terrain_label
from creature_lab.robots.types import RobotRun, Scenario
from creature_lab.schema.base import StrictModel

#: Shoves per strength, spread evenly across one stride (alternating sides).
SHOVE_PHASES = 8
#: Shares of its torque the weakened motor keeps, and the command delays tried (ms).
WEAK_STRENGTHS = (0.6, 0.3)
DELAYS_MS = (20.0, 40.0, 60.0)


def weak_joint(baseline: RobotRun) -> str | None:
    """The joint the damage test weakens: the one that works hardest in the baseline walk (the
    highest 95th-percentile share of its torque limit), where a failing motor matters most."""
    if not baseline.joint_names or baseline.load.size == 0:
        return None
    effort = np.percentile(np.abs(baseline.load), 95, axis=0)
    return baseline.joint_names[int(np.argmax(effort))]


def tested_levels(robot: str) -> CheckupLevels:
    """The shove strengths, floors, batteries and loads the check-up tries on ``robot``."""
    return robot_info(robot).levels


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
    # Here, not at import: reading a saved check-up (the report, the app's listings) must not
    # need the simulator, which pulls in MuJoCo.
    from creature_lab.robots.api import run_scenario

    info: RobotInfo = robot_info(robot)
    levels = info.levels
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
                # Staying up is not enough: a robot stuck at the foot of a ramp did not pass it.
                # Unless going nowhere is what its own walk does (a stand-still policy).
                passed=not result.fell and not (result.stalled and not baseline.stalled),
                distance_m=result.distance_m,
                relative_distance=result.distance_m / reference,
                analysis=result,
                run=_save(run, out_dir, key),
            )
        )

    for terrain in course(info.height_cm):
        condition(terrain_key(terrain), terrain_label(terrain), terrain=terrain)
    hardest = weak_joint(baseline_run)
    if hardest is not None:
        words = joint_text(hardest)
        for strength in WEAK_STRENGTHS:
            percent = round(100 * strength)
            condition(
                f"damage_weak_{percent}",
                f"{words[0].upper()}{words[1:]} motor at {percent}% strength",
                weak_joint=hardest,
                weak_strength=strength,
            )
    for delay in DELAYS_MS:
        condition(
            f"damage_delay_{delay:g}ms",
            f"Commands arrive {delay:g} ms late",
            delay_ms=delay,
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


#: What makes two saved runs "the same test" (the app pairs runs on the same fields).
TWIN_FIELDS = (
    "push_n",
    "push_side",
    "push_at_s",
    "push_for_s",
    "grip",
    "battery_v",
    "payload_kg",
    "terrain",
    "weak_joint",
    "weak_strength",
    "delay_ms",
)


def _shoves(folder: Path) -> dict[tuple, dict]:
    """The saved shove runs of one policy's results, keyed by what makes them the same test."""
    found = {}
    for meta_file in sorted((Path(folder) / "runs").glob("shove*/robot_run.json")):
        scenario = json.loads(meta_file.read_text(encoding="utf-8"))["scenario"]
        found[tuple(scenario.get(f) for f in TWIN_FIELDS)] = scenario
    return found


def add_twins(folders: dict[str, Path], progress: Callable[[str], None] | None = None) -> int:
    """Run each saved shove under every other policy too, so any shove can be shown side by side.

    A check-up saves one example fall and one example of staying up per shove strength, at
    whichever moment of the stride came first, so two policies rarely share a saved shove. The
    twin is the same shove (strength, side, moment) under the other policy, saved beside its own
    runs. Returns how many runs were added.
    """
    from creature_lab.robots.api import run_scenario

    saved = {policy: _shoves(folder) for policy, folder in folders.items()}
    wanted: list[tuple[str, dict]] = []
    for policy, shoves in saved.items():
        for other, other_shoves in saved.items():
            if other == policy:
                continue
            for key, scenario in other_shoves.items():
                if key not in shoves:
                    wanted.append((policy, {**scenario, "policy": policy}))
    added = 0
    seen: set[tuple] = set()
    for policy, scenario in wanted:
        key = (policy, *(scenario.get(f) for f in TWIN_FIELDS))
        if key in seen:
            continue
        seen.add(key)
        if progress and added == 0:
            progress("the same shoves for every policy")
        name = f"shove_{scenario['push_n']:g}N_{scenario['push_side']}_{scenario['push_at_s']:.2f}s"
        _save(run_scenario(Scenario.model_validate(scenario)), Path(folders[policy]), name)
        added += 1
    return added


def read_checkup(out_dir: Path) -> Checkup:
    return Checkup.model_validate(json.loads((Path(out_dir) / "checkup.json").read_text("utf-8")))


def planned_steps(robot: str) -> int:
    """How many progress lines a full check-up of ``robot`` prints (every policy, every test)."""
    levels = robot_info(robot).levels
    per_policy = 1 + len(levels.shoves_n) + len(levels.grips) + len(levels.batteries_v)
    per_policy += len(levels.payloads_kg)
    return per_policy * len(robot_info(robot).policies)
