"""Shared MuJoCo rollout: step a robot for a scenario and record what an analysis needs."""

from __future__ import annotations

import math
from abc import ABC, abstractmethod

import mujoco
import numpy as np

from creature_lab import VERSION
from creature_lab.robots.types import CONTROL_HZ, SUPPORT_VERTICES, RobotRun, Scenario

#: Contacts pressing less than this (newtons) are ignored when outlining the support area.
_MIN_CONTACT_N = 0.02


class MujocoRobot(ABC):
    """One robot, one policy, one scenario. Subclasses wire the observation and actuators."""

    model: mujoco.MjModel
    data: mujoco.MjData
    joint_names: list[str]
    #: Physics steps per 50 Hz control step.
    substeps: int
    trunk: int

    def __init__(self, scenario: Scenario) -> None:
        self.scenario = scenario

    @abstractmethod
    def control(self, time_s: float) -> None:
        """Read sensors, run the policy, and set the actuator targets for this control step."""

    @abstractmethod
    def physics_step(self) -> None:
        """Apply actuator forces and advance physics by one step."""

    @abstractmethod
    def servo_load(self) -> np.ndarray:
        """Signed actuator torque as a fraction of its limit, one value per joint."""

    @abstractmethod
    def provenance(self) -> dict:
        """Versions and file hashes that make the run reproducible."""

    def finish_setup(self) -> None:
        """Apply the scenario's world changes; call once after the model is compiled."""
        model, scenario = self.model, self.scenario
        model.geom_friction[:, 0] *= scenario.grip
        if scenario.payload_kg:
            model.body_mass[self.trunk] += scenario.payload_kg
            mujoco.mj_setConst(model, self.data)
        self._floor = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, "floor")
        self._root = int(model.body_rootid[self.trunk])
        self._contact_buffer = np.zeros(6)


def _convex_hull(points: np.ndarray) -> np.ndarray:
    """Counter-clockwise hull (Andrew's monotone chain) of an (n, 2) array."""
    unique = sorted({(round(float(x), 6), round(float(y), 6)) for x, y in points})
    if len(unique) <= 2:
        return np.array(unique, dtype=float).reshape(-1, 2)

    def turn(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[tuple[float, float]] = []
    for point in unique:
        while len(lower) >= 2 and turn(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)
    upper: list[tuple[float, float]] = []
    for point in reversed(unique):
        while len(upper) >= 2 and turn(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)
    return np.array(lower[:-1] + upper[:-1], dtype=float)


def _ground_contacts(robot: MujocoRobot) -> tuple[np.ndarray, float]:
    """Support outline (NaN-padded) and the fastest contact-point slide this frame (m/s)."""
    model, data = robot.model, robot.data
    points = []
    slide = 0.0
    velocity = np.zeros(6)
    for index in range(data.ncon):
        contact = data.contact[index]
        if robot._floor not in (contact.geom1, contact.geom2):
            continue
        mujoco.mj_contactForce(model, data, index, robot._contact_buffer)
        if robot._contact_buffer[0] < _MIN_CONTACT_N:
            continue
        points.append(contact.pos[:2].copy())
        geom = contact.geom2 if contact.geom1 == robot._floor else contact.geom1
        mujoco.mj_objectVelocity(model, data, mujoco.mjtObj.mjOBJ_GEOM, geom, velocity, 0)
        # Velocity of the touching point itself: centre velocity plus spin about the centre.
        offset = contact.pos - data.geom_xpos[geom]
        point_velocity = velocity[3:] + np.cross(velocity[:3], offset)
        slide = max(slide, math.hypot(point_velocity[0], point_velocity[1]))
    outline = np.full((SUPPORT_VERTICES, 2), np.nan)
    if points:
        hull = _convex_hull(np.array(points))
        if len(hull) > SUPPORT_VERTICES:
            hull = hull[np.linspace(0, len(hull) - 1, SUPPORT_VERTICES).astype(int)]
        outline[: len(hull)] = hull
    return outline, slide


def run_robot(robot: MujocoRobot) -> RobotRun:
    """Roll the scenario out at 50 Hz and return the recorded run."""
    scenario, model, data = robot.scenario, robot.model, robot.data
    steps = int(round(scenario.seconds * CONTROL_HZ))
    columns: dict[str, list] = {
        name: [] for name in ("qpos", "qvel", "load", "upright", "trunk_pos", "com", "com_vel")
    }
    support, slide_speed, push_force = [], [], []
    push_on = scenario.push_at_s
    push_off = scenario.push_at_s + scenario.push_for_s
    for step in range(steps):
        time_s = step / CONTROL_HZ
        robot.control(time_s)
        pushing = scenario.push_n > 0 and push_on <= time_s < push_off
        force = scenario.push_sign * scenario.push_n if pushing else 0.0
        data.xfrc_applied[robot.trunk, 1] = force
        for _ in range(robot.substeps):
            robot.physics_step()
        data.xfrc_applied[robot.trunk, 1] = 0.0
        mujoco.mj_subtreeVel(model, data)
        outline, slide = _ground_contacts(robot)
        columns["qpos"].append(data.qpos.copy())
        columns["qvel"].append(data.qvel.copy())
        columns["load"].append(robot.servo_load())
        columns["upright"].append(float(data.xmat[robot.trunk].reshape(3, 3)[2, 2]))
        columns["trunk_pos"].append(data.xpos[robot.trunk].copy())
        columns["com"].append(data.subtree_com[robot._root].copy())
        columns["com_vel"].append(data.subtree_linvel[robot._root].copy())
        support.append(outline)
        slide_speed.append(slide)
        push_force.append(force)
    return RobotRun(
        scenario=scenario,
        joint_names=robot.joint_names,
        time=np.arange(1, steps + 1) / CONTROL_HZ,
        support=np.array(support),
        slide_speed=np.array(slide_speed),
        push_force=np.array(push_force),
        provenance={
            "creature_lab": VERSION,
            "mujoco": mujoco.__version__,
            "scenario_hash": scenario.digest(),
            **robot.provenance(),
        },
        **{name: np.array(values) for name, values in columns.items()},
    )
