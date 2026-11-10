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
    title: str = ""

    def digest(self) -> str:
        return spec_hash(self)

    @property
    def push_sign(self) -> float:
        return 1.0 if self.push_side == "left" else -1.0


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
    provenance: dict[str, Any] = field(default_factory=dict)

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
    )

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
            data = {name: arrays[name] for name in cls.ARRAYS}
        return cls(
            scenario=Scenario.model_validate(meta["scenario"]),
            joint_names=meta["joint_names"],
            provenance=meta.get("provenance", {}),
            **data,
        )
