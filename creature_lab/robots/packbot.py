"""Run a robot pack: any MuJoCo robot with a trained policy, wired from its ``robot.toml``."""

from __future__ import annotations

import hashlib
from collections.abc import Callable

import mujoco
import numpy as np

from creature_lab.robots.pack import Pack, PackError, pack_info, sensor_widths
from creature_lab.robots.policies import load_policy
from creature_lab.robots.rollout import MujocoRobot
from creature_lab.robots.scene import load_model, write_studio_scene
from creature_lab.robots.terrain import ground_height, layout
from creature_lab.robots.types import Scenario

Term = Callable[[float], np.ndarray]


class PackRobot(MujocoRobot):
    """PD (or position-servo) joints driven by the pack's policy at 50 Hz."""

    def __init__(self, scenario: Scenario, pack: Pack) -> None:
        super().__init__(scenario)
        spec = pack.spec
        self.pack = pack
        self.substeps = spec.substeps
        info = pack_info(pack)
        staging = info.staging
        model_path = pack.model_path
        scene = write_studio_scene(
            model_path.parent, staging.scene_name, model_path.name, tile_m=staging.tile_m
        )
        model = load_model(scene, scenario.terrain)
        model.opt.timestep = spec.physics_dt
        self.model = model
        self.data = mujoco.MjData(model)
        self.trunk = _body(model, spec.trunk)
        root = int(model.body_jntadr[self.trunk])
        if root < 0 or model.jnt_type[root] != mujoco.mjtJoint.mjJNT_FREE:
            raise PackError([f"trunk {spec.trunk!r} has no free joint, so the robot cannot fall"])
        self._root_q = int(model.jnt_qposadr[root])
        self._root_v = int(model.jnt_dofadr[root])

        self.joint_names = list(spec.joints)
        joint_ids = [_joint(model, name) for name in self.joint_names]
        self._qadr = model.jnt_qposadr[joint_ids]
        self._dadr = model.jnt_dofadr[joint_ids]
        self._act = np.array(
            [_actuator_of(model, j, n) for j, n in zip(joint_ids, self.joint_names, strict=True)]
        )
        joints = list(spec.joints.values())
        self._default = np.array([j.default for j in joints], dtype=np.float64)
        self._kp = np.array([j.kp or 0.0 for j in joints], dtype=np.float64)
        self._kd = np.array([j.kd or 0.0 for j in joints], dtype=np.float64)
        self._limit = np.array(
            [
                _torque_limit(model, jid, int(a), j.torque_limit, n)
                for jid, a, j, n in zip(joint_ids, self._act, joints, self.joint_names, strict=True)
            ]
        )
        self._position_servos = spec.actuator == "position"
        # One number for the whole robot keeps the arithmetic of a plain scalar; per-joint scales
        # are float32 like the policy's own output.
        self._scale: float | np.ndarray = (
            np.array([j.action_scale or spec.action_scale for j in joints], dtype=np.float32)
            if any(j.action_scale is not None for j in joints)
            else float(spec.action_scale)
        )

        self.policy_path = pack.policy_path(scenario.policy)
        self.policy = load_policy(self.policy_path)
        self._terms = self._build_terms()
        self.finish_setup()
        self.data.qpos[:] = model.qpos0
        self.data.qpos[self._qadr] = self._default
        if spec.spawn_height_m is not None:
            self.data.qpos[self._root_q + 2] = spec.spawn_height_m
        self._target = self._default.copy()
        self._action = np.zeros(len(joints), dtype=np.float32)
        self._torque = np.zeros(len(joints))
        mujoco.mj_forward(model, self.data)

    # ---- observation ----------------------------------------------------------------------
    def _build_terms(self) -> list[Term]:
        model, data, spec = self.model, self.data, self.pack.spec
        widths = sensor_widths(model)
        terms: list[Term] = []
        for term in spec.observation_for(self.scenario.policy):
            scale = np.asarray(term.scale, dtype=np.float64)
            kind = term.term
            if kind == "base_ang_vel":
                v = self._root_v
                terms.append(lambda t, s=scale, v=v: data.qvel[v + 3 : v + 6] * s)
            elif kind == "base_lin_vel":
                v = self._root_v
                terms.append(
                    lambda t, s=scale, v=v: (
                        (data.xmat[self.trunk].reshape(3, 3).T @ data.qvel[v : v + 3]) * s
                    )
                )
            elif kind == "projected_gravity":
                q = self._root_q
                terms.append(lambda t, s=scale, q=q: self._gravity(q) * s)
            elif kind == "command":
                size = term.size or 3

                def command(t: float, s=scale, size=size) -> np.ndarray:
                    vector = np.zeros(size)
                    vector[0] = self.scenario.command
                    return vector * s

                terms.append(command)
            elif kind == "joint_pos":
                terms.append(lambda t, s=scale: (data.qpos[self._qadr] - self._default) * s)
            elif kind == "joint_vel":
                terms.append(lambda t, s=scale: data.qvel[self._dadr] * s)
            elif kind == "last_action":
                terms.append(lambda t, s=scale: self._action * s)
            elif kind == "gait_phase":
                period = float(term.period_s or 1.0)

                def phase(t: float, period=period, s=float(scale)) -> np.ndarray:
                    angle = 2 * np.pi * ((t % period) / period)
                    return np.array([np.sin(angle), np.cos(angle)]) * s

                terms.append(phase)
            elif kind == "height_scan":
                terms.append(self._height_scan(term, scale))
            else:  # sensor
                name = term.sensor or ""
                if name not in widths:
                    raise PackError([f"observation: the model has no sensor named {name!r}"])
                sensor_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_SENSOR, name)
                start = int(model.sensor_adr[sensor_id])
                end = start + widths[name]
                terms.append(lambda t, s=scale, a=start, b=end: data.sensordata[a:b] * s)
        return terms

    def _height_scan(self, term, scale: np.ndarray) -> Term:
        """Height of a body above the ground at each point of a grid that turns with its heading.

        The same numbers as mjlab's ``height_scan`` from a yaw-aligned grid of rays cast straight
        down onto the terrain only (never the robot): the body's height minus the ground's height
        under each point, capped at ``max_distance_m``. The ground is the floor plus the boxes of
        the scenario's terrain, so its height is worked out exactly instead of by casting rays.
        """
        data = self.data
        body = _body(self.model, term.body or self.pack.spec.trunk)
        points = term.scan_points
        cap = float(term.max_distance_m)
        lay = layout(self.scenario.terrain) if self.scenario.terrain is not None else None

        def scan(t: float, s=scale) -> np.ndarray:
            pos = data.xpos[body]
            frame = data.xmat[body].reshape(3, 3)
            fx, fy = frame[0, 0], frame[1, 0]  # the body's x axis, flattened onto the floor
            norm = float(np.hypot(fx, fy))
            if norm < 0.1:  # x axis nearly vertical: turn the y axis a quarter turn instead
                yx, yy = frame[0, 1], frame[1, 1]
                side = float(np.hypot(yx, yy)) or 1e-6
                fx, fy, norm = yy / side, -yx / side, 1.0
            fx, fy = fx / norm, fy / norm
            x = pos[0] + points[:, 0] * fx - points[:, 1] * fy
            y = pos[1] + points[:, 0] * fy + points[:, 1] * fx
            ground = ground_height(lay, x, y) if lay is not None else np.zeros(len(points))
            return np.minimum(pos[2] - ground, cap) * s

        return scan

    def _gravity(self, q: int) -> np.ndarray:
        """Where "down" is in the trunk's frame, from the free joint's quaternion."""
        w, x, y, z = self.data.qpos[q + 3 : q + 7]
        return np.array([2 * (-z * x + w * y), -2 * (z * y + w * x), 1 - 2 * (w * w + z * z)])

    # ---- control --------------------------------------------------------------------------
    def control(self, time_s: float) -> None:
        observation = np.concatenate([term(time_s) for term in self._terms])
        action = self.policy.act(observation)
        if not np.all(np.isfinite(action)):
            raise PackError(["the policy returned a NaN or infinite action"])
        self._action = action
        clip = self.pack.spec.action_clip
        used = np.clip(action, -clip, clip) if clip else action
        self._target = self._default + used * self._scale

    def physics_step(self) -> None:
        data = self.data
        if self._position_servos:
            data.ctrl[self._act] = self._target
            mujoco.mj_step(self.model, data)
            self._torque = data.actuator_force[self._act].copy()
            return
        self._torque = (self._target - data.qpos[self._qadr]) * self._kp - data.qvel[
            self._dadr
        ] * self._kd
        data.ctrl[self._act] = self._torque
        mujoco.mj_step(self.model, data)

    def servo_load(self) -> np.ndarray:
        return self._torque / self._limit

    def provenance(self) -> dict:
        spec = self.pack.spec
        return {
            "robot": spec.key,
            "policy": self.scenario.policy,
            "policy_sha256": hashlib.sha256(self.policy_path.read_bytes()).hexdigest(),
            "pack": "robot.toml",
            "credit": spec.license.credit,
        }


def _body(model: mujoco.MjModel, name: str) -> int:
    body = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, name)
    if body < 0:
        raise PackError([f"trunk: the model has no body named {name!r}"])
    return body


def _joint(model: mujoco.MjModel, name: str) -> int:
    joint = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, name)
    if joint < 0:
        raise PackError([f"joints.{name}: the model has no joint with that name"])
    return joint


def _actuator_of(model: mujoco.MjModel, joint: int, name: str) -> int:
    """The actuator that drives ``joint``."""
    for index in range(model.nu):
        if (
            model.actuator_trntype[index] == mujoco.mjtTrn.mjTRN_JOINT
            and int(model.actuator_trnid[index, 0]) == joint
        ):
            return index
    raise PackError([f"joints.{name}: the model has no actuator on this joint"])


def _torque_limit(
    model: mujoco.MjModel, joint: int, actuator: int, declared: float | None, name: str
) -> float:
    """Torque that counts as 100%: what the pack says, else the model's own limit."""
    if declared is not None:
        return float(declared)
    if model.jnt_actfrclimited[joint]:
        return float(model.jnt_actfrcrange[joint][1])
    if model.actuator_forcelimited[actuator]:
        return float(model.actuator_forcerange[actuator][1])
    if model.actuator_ctrllimited[actuator]:
        return float(model.actuator_ctrlrange[actuator][1])
    raise PackError(
        [f"joints.{name}: no torque limit in the model; add torque_limit = <N·m> to this joint"]
    )
