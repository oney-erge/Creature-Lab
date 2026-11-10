"""Preset creatures and tasks for the build editor."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from creature_lab.scaffold import (
    generate_hexapod,
    generate_humanoid,
    generate_quadruped,
    generate_worm,
)
from creature_lab.schema import CreatureSpec, TaskSpec

ParamKind = Literal["float", "int"]


@dataclass(frozen=True)
class ParamSpec:
    key: str
    label: str
    minimum: float
    maximum: float
    step: float
    initial: float
    kind: ParamKind = "float"


@dataclass(frozen=True)
class CreaturePreset:
    name: str
    label: str
    params: tuple[ParamSpec, ...]
    generator: Callable[[dict[str, float]], CreatureSpec]


def _int_param(params: dict[str, float], key: str) -> int:
    return int(round(params[key]))


def _quadruped(params: dict[str, float]) -> CreatureSpec:
    return generate_quadruped(
        leg_length=params["leg_length"],
        body_length=params["body_length"],
        body_width=params["body_width"],
        amplitude=params["amplitude"],
        frequency=params["frequency"],
    )


def _hexapod(params: dict[str, float]) -> CreatureSpec:
    return generate_hexapod(
        leg_length=params["leg_length"],
        body_length=params["body_length"],
        body_width=params["body_width"],
        amplitude=params["amplitude"],
        frequency=params["frequency"],
    )


def _worm(params: dict[str, float]) -> CreatureSpec:
    return generate_worm(
        _int_param(params, "segments"),
        seg_length=params["segment_length"],
        radius=params["radius"],
        mass=params["segment_mass"],
        amplitude=params["amplitude"],
        frequency=params["frequency"],
    )


def _humanoid(params: dict[str, float]) -> CreatureSpec:
    dof = 12 if params["dof"] >= 10 else 8
    return generate_humanoid(
        height=params["height"],
        mass=params["mass"],
        dof=dof,
        torso_height_ratio=params["torso_height_ratio"],
        torso_width_ratio=params["torso_width_ratio"],
        upper_leg_ratio=params["upper_leg_ratio"],
        lower_leg_ratio=params["lower_leg_ratio"],
        upper_arm_ratio=params["upper_arm_ratio"],
        lower_arm_ratio=params["lower_arm_ratio"],
        shoulder_extra_ratio=params["shoulder_extra_ratio"],
        limb_radius_ratio=params["limb_radius_ratio"],
        hip_spread_ratio=params["hip_spread_ratio"],
        amplitude=params["amplitude"],
        frequency=params["frequency"],
    )


CREATURE_PRESETS: dict[str, CreaturePreset] = {
    "quadruped": CreaturePreset(
        "quadruped",
        "Quadruped",
        (
            ParamSpec("body_length", "Body length", 0.2, 1.0, 0.01, 0.4),
            ParamSpec("body_width", "Body width", 0.12, 0.8, 0.01, 0.32),
            ParamSpec("leg_length", "Leg length", 0.08, 0.6, 0.01, 0.22),
            ParamSpec("amplitude", "Motor amplitude", 0.0, 1.4, 0.05, 0.7),
            ParamSpec("frequency", "Motor frequency", 0.0, 5.0, 0.1, 2.0),
        ),
        _quadruped,
    ),
    "hexapod": CreaturePreset(
        "hexapod",
        "Hexapod",
        (
            ParamSpec("body_length", "Body length", 0.3, 1.2, 0.01, 0.6),
            ParamSpec("body_width", "Body width", 0.12, 0.8, 0.01, 0.3),
            ParamSpec("leg_length", "Leg length", 0.08, 0.6, 0.01, 0.2),
            ParamSpec("amplitude", "Motor amplitude", 0.0, 1.4, 0.05, 0.7),
            ParamSpec("frequency", "Motor frequency", 0.0, 5.0, 0.1, 2.0),
        ),
        _hexapod,
    ),
    "worm": CreaturePreset(
        "worm",
        "Worm",
        (
            ParamSpec("segments", "Segments", 2, 12, 1, 5, "int"),
            ParamSpec("segment_length", "Segment length", 0.05, 0.5, 0.01, 0.18),
            ParamSpec("radius", "Radius", 0.01, 0.16, 0.005, 0.05),
            ParamSpec("segment_mass", "Segment mass", 0.05, 2.0, 0.05, 0.4),
            ParamSpec("amplitude", "Motor amplitude", 0.0, 1.5, 0.05, 1.0),
            ParamSpec("frequency", "Motor frequency", 0.0, 5.0, 0.1, 1.5),
        ),
        _worm,
    ),
    "humanoid": CreaturePreset(
        "humanoid",
        "Humanoid",
        (
            ParamSpec("height", "Height", 0.6, 2.4, 0.02, 1.6),
            ParamSpec("mass", "Mass", 5.0, 120.0, 1.0, 60.0),
            # Default 12, not 8: adds feet/hands, a much bigger and flatter ground
            # contact than a bare capsule tip - see docs/KNOWN_ISSUES.md.
            ParamSpec("dof", "DOF", 8, 12, 4, 12, "int"),
            ParamSpec("torso_height_ratio", "Torso height %", 0.18, 0.45, 0.01, 0.25),
            ParamSpec("torso_width_ratio", "Shoulder width %", 0.10, 0.35, 0.01, 0.18),
            ParamSpec("upper_leg_ratio", "Upper leg %", 0.12, 0.35, 0.01, 0.20),
            ParamSpec("lower_leg_ratio", "Lower leg %", 0.12, 0.35, 0.01, 0.20),
            ParamSpec("hip_spread_ratio", "Hip stance width %", 0.25, 0.70, 0.01, 0.50),
            ParamSpec("upper_arm_ratio", "Upper arm %", 0.08, 0.28, 0.01, 0.18),
            ParamSpec("lower_arm_ratio", "Lower arm %", 0.08, 0.28, 0.01, 0.16),
            ParamSpec("shoulder_extra_ratio", "Arm offset %", 0.01, 0.12, 0.005, 0.04),
            ParamSpec("limb_radius_ratio", "Limb radius %", 0.015, 0.08, 0.005, 0.035),
            # Keep the baked teaching baseline identical to the packaged body so
            # `curated` can select its separately tuned walking controller by hash.
            ParamSpec("amplitude", "Motor amplitude", 0.0, 1.4, 0.05, 0.4),
            ParamSpec("frequency", "Motor frequency", 0.0, 5.0, 0.1, 1.0),
        ),
        _humanoid,
    ),
}


def preset_names() -> list[str]:
    return list(CREATURE_PRESETS)


def preset_labels() -> list[str]:
    return [preset.label for preset in CREATURE_PRESETS.values()]


def preset_name_from_label(label: str) -> str:
    for name, preset in CREATURE_PRESETS.items():
        if preset.label == label:
            return name
    raise KeyError(label)


def preset_label(name: str) -> str:
    return CREATURE_PRESETS[name].label


def default_params(name: str) -> dict[str, float]:
    return {param.key: param.initial for param in CREATURE_PRESETS[name].params}


def generate_creature(name: str, params: dict[str, float] | None = None) -> CreatureSpec:
    preset = CREATURE_PRESETS[name]
    merged = default_params(name)
    if params:
        merged.update(params)
    return preset.generator(merged)


TASK_PRESETS: dict[str, dict[str, Any]] = {
    "crawl_forward": {
        "name": "crawl_forward",
        "duration": 5.0,
        "timestep": 1.0 / 60.0,
        "terrain": {"type": "plane", "friction": 1.0},
        "reward": {"forward_distance": 1.0},
    },
    "low_friction_crawl": {
        "name": "low_friction_crawl",
        "duration": 5.0,
        "timestep": 1.0 / 60.0,
        "terrain": {"type": "plane", "friction": 0.25},
        # energy_penalty=0.01 looks small but raw accumulated energy over a few
        # seconds of open-loop actuation is ~100-280 (measured across every preset
        # creature) - at 0.01 that swamped the forward-distance reward and made a
        # working crawl score negative. 0.001 leaves energy as a real tie-breaker
        # without cancelling out visible forward progress. See KNOWN_ISSUES.md.
        "reward": {"forward_distance": 1.0, "energy_penalty": 0.001},
    },
    "reach_target": {
        "name": "reach_target",
        "duration": 5.0,
        "timestep": 1.0 / 60.0,
        "terrain": {"type": "plane", "friction": 1.0},
        "target": {"type": "sphere", "position": [1.0, 0.0, 0.2], "radius": 0.15},
        # forward_distance explicitly 0: RewardSpec defaults it to 1.0, which was
        # silently double-rewarding raw +x movement on top of target approach for
        # a task that is supposed to be scored on the target alone.
        "reward": {"forward_distance": 0.0, "target_distance": 1.0, "energy_penalty": 0.001},
    },
    "stability_hold": {
        "name": "stability_hold",
        "duration": 4.0,
        "timestep": 1.0 / 60.0,
        "terrain": {"type": "plane", "friction": 1.0},
        # A "stay balanced" task built only from penalties (fall_penalty +
        # energy_penalty) can never score above 0, so a creature that succeeds
        # still looks like it failed. `survival` is the positive mirror of
        # fall_penalty: reward for still being upright at the end. forward_distance
        # is explicitly 0 - movement is not the objective here.
        "reward": {
            "forward_distance": 0.0,
            "fall_penalty": 1.0,
            "energy_penalty": 0.001,
            "survival": 1.0,
        },
    },
}


def task_names() -> list[str]:
    return list(TASK_PRESETS)


#: First-run onboarding goals: goal key -> (display label, backing task preset name).
#: Kept to task presets that already exist and are exercised by tests, rather than
#: promising terrain goals (climb/step/cross) the editor doesn't yet expose.
ONBOARDING_GOALS: dict[str, tuple[str, str]] = {
    "move_forward": ("Move forward", "crawl_forward"),
    "reach_target": ("Reach a target", "reach_target"),
    "stay_balanced": ("Stay balanced", "stability_hold"),
}


def onboarding_goal_labels() -> list[str]:
    return [label for label, _task in ONBOARDING_GOALS.values()]


def onboarding_goal_key_from_label(label: str) -> str:
    for key, (goal_label, _task) in ONBOARDING_GOALS.items():
        if goal_label == label:
            return key
    raise KeyError(label)


def generate_task(
    name: str,
    *,
    duration: float | None = None,
    friction: float | None = None,
) -> TaskSpec:
    data = dict(TASK_PRESETS[name])
    data["terrain"] = dict(data.get("terrain", {}))
    data["reward"] = dict(data.get("reward", {}))
    if "target" in data:
        data["target"] = dict(data["target"])
    if duration is not None:
        data["duration"] = duration
    if friction is not None:
        data["terrain"]["friction"] = friction
    return TaskSpec.model_validate(data)
