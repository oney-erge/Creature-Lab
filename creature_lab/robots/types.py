"""What a robot check-up runs (``Scenario``) and what it records (``RobotRun``)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import numpy as np
from pydantic import Field

from creature_lab.hashing import spec_hash
from creature_lab.io_utils import atomic_write_text
from creature_lab.robots.terrain import Terrain
from creature_lab.schema.base import StrictModel

#: Both robots are controlled at 50 Hz.
CONTROL_HZ = 50
#: Most contact points kept per frame for the support outline.
SUPPORT_VERTICES = 8


class Scenario(StrictModel):
    """One 10-second walk with an optional shove and optional bad conditions."""

    robot: str
    policy: str
    #: Forward walking command handed to the policy.
    command: float = Field(default=0.5, ge=0.0, le=1.0)
    seconds: float = Field(default=10.0, gt=0.0, le=60.0)
    #: Sideways force on the trunk, in newtons, held for ``push_for_s``.
    push_n: float = Field(default=0.0, ge=0.0, le=2000.0)
    push_side: Literal["left", "right"] = "left"
    push_at_s: float = Field(default=4.0, ge=0.0)
    push_for_s: float = Field(default=0.2, gt=0.0, le=2.0)
    #: Multiplier on every contact friction coefficient (1 = the model's own).
    grip: float = Field(default=1.0, gt=0.0, le=2.0)
    #: Battery voltage (Microduck only; the G1 model has no battery).
    battery_v: float = Field(default=7.4, ge=5.0, le=9.0)
    #: Extra mass added to the trunk, in kilograms.
    payload_kg: float = Field(default=0.0, ge=0.0, le=50.0)
    #: Stairs, a ramp, rough ground or stepping stones ahead of the robot; None is a flat floor.
    terrain: Terrain | None = None
    #: A joint whose motor is failing (its MuJoCo name), and the share of its torque it still has.
    weak_joint: str | None = None
    weak_strength: float = Field(default=1.0, gt=0.0, le=1.0)
    #: Milliseconds between the policy deciding and the motors getting the command, in whole
    #: 20 ms control steps (0, 20, 40, ...).
    delay_ms: float = Field(default=0.0, ge=0.0, le=200.0)
    title: str = ""

    def digest(self) -> str:
        # Fields added after the first release are left out while unused, so a scenario that does
        # not use them hashes as it always did.
        unused = {name for name, default in _ADDED.items() if getattr(self, name) == default}
        return spec_hash(self, exclude=unused or None)

    @property
    def delay_steps(self) -> int:
        return round(self.delay_ms * CONTROL_HZ / 1000.0)

    @property
    def push_sign(self) -> float:
        return 1.0 if self.push_side == "left" else -1.0


#: Scenario fields added after the first release, with the value that means "not used".
_ADDED = {"terrain": None, "weak_joint": None, "weak_strength": 1.0, "delay_ms": 0.0}


@dataclass
class RobotRun:
    """Everything recorded at 50 Hz during one rollout (arrays have one row per frame)."""

    scenario: Scenario
    joint_names: list[str]
    time: np.ndarray
    qpos: np.ndarray
    qvel: np.ndarray
    #: Servo/motor torque as a fraction of its limit (signed).
    load: np.ndarray
    #: Trunk z-axis dotted with world up: 1 upright, 0 on its side, -1 upside down.
    upright: np.ndarray
    trunk_pos: np.ndarray
    com: np.ndarray
    com_vel: np.ndarray
    #: Ground-contact outline (x, y) per frame, NaN-padded to ``SUPPORT_VERTICES`` rows.
    support: np.ndarray
    #: Fastest sliding speed of any loaded ground-contact point, in m/s (0 = planted).
    slide_speed: np.ndarray
    #: Sideways push force applied each frame, in newtons (signed).
    push_force: np.ndarray
    #: Height of the lowest point touching the ground each frame, in metres (NaN when nothing
    #: touches). A foot that drops into a gap between stepping stones shows up here.
    lowest_contact_z: np.ndarray | None = None
    #: Force pressing on the side or edge of a step, stone or tile each frame, in newtons: a toe
    #: catching a step shows up here. Always 0 on a flat floor.
    edge_force: np.ndarray | None = None
    provenance: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Runs saved before these were recorded read as "flat floor, nothing caught".
        if self.lowest_contact_z is None:
            self.lowest_contact_z = np.zeros(len(self.time))
        if self.edge_force is None:
            self.edge_force = np.zeros(len(self.time))

    ARRAYS = (
        "time",
        "qpos",
        "qvel",
        "load",
        "upright",
        "trunk_pos",
        "com",
        "com_vel",
        "support",
        "slide_speed",
        "push_force",
        "lowest_contact_z",
        "edge_force",
    )
    #: Arrays a run saved by an earlier version may not have (``__post_init__`` fills them).
    OPTIONAL = ("lowest_contact_z", "edge_force")

    def __len__(self) -> int:
        return len(self.time)

    def save(self, folder: Path) -> Path:
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            folder / "states.npz", **{name: getattr(self, name) for name in self.ARRAYS}
        )
        meta = {
            "schema": "creature-lab.robot-run/1",
            "scenario": self.scenario.model_dump(mode="json"),
            "scenario_hash": self.scenario.digest(),
            "joint_names": self.joint_names,
            "provenance": self.provenance,
        }
        atomic_write_text(folder / "robot_run.json", json.dumps(meta, indent=2) + "\n")
        return folder

    @classmethod
    def read(cls, folder: Path) -> RobotRun:
        folder = Path(folder)
        meta = json.loads((folder / "robot_run.json").read_text(encoding="utf-8"))
        with np.load(folder / "states.npz") as arrays:
            data = {
                name: arrays[name]
                for name in cls.ARRAYS
                if name in arrays.files or name not in cls.OPTIONAL
            }
        return cls(
            scenario=Scenario.model_validate(meta["scenario"]),
            joint_names=meta["joint_names"],
            provenance=meta.get("provenance", {}),
            **data,
        )
