"""Microduck (Pollen Robotics): MuJoCo model + ONNX policy + XL330 servo model."""

from __future__ import annotations

import hashlib

import mujoco
import numpy as np

from creature_lab.robots.actuator import ServoBank, friction_budget
from creature_lab.robots.catalog import robot_info
from creature_lab.robots.fetch import is_installed, robot_dir
from creature_lab.robots.policies import OnnxPolicy
from creature_lab.robots.rollout import MujocoRobot
from creature_lab.robots.scene import write_studio_scene
from creature_lab.robots.terrain import add_terrain
from creature_lab.robots.types import Scenario

_PHYSICS_DT = 0.005
_SPAWN_HEIGHT = 0.125
_NO_HEAD_COMMANDS = 10  # head pose (4) and body pose (6) commands stay at zero


class Microduck(MujocoRobot):
    """Walks with Pollen's ONNX policies, driven through the XL330 servo model."""

    substeps = 4

    def __init__(self, scenario: Scenario) -> None:
        super().__init__(scenario)
        if not is_installed("microduck"):
            raise FileNotFoundError(
                "Microduck is not downloaded yet; run: creature-lab robots fetch microduck"
            )
        info = robot_info("microduck")
        folder = robot_dir("microduck")
        policy_file = info.policy(scenario.policy).file
        self.policy_path = folder / policy_file
        self.policy = OnnxPolicy(self.policy_path)
        scene = write_studio_scene(folder, "Microduck", "robot_groundcontact.xml", tile_m=0.12)
        self.servos = ServoBank(14, battery_v=scenario.battery_v)
        self._build(str(scene))
        self.finish_setup()
        self._reset_pose()

    def _build(self, scene_path: str) -> None:
        spec = mujoco.MjSpec.from_file(scene_path)
        limit = self.servos.stall_torque
        for actuator in spec.actuators:
            joint = actuator.target
            # The servo model supplies torque, friction and damping every step.
            actuator.set_to_motor()
            actuator.forcelimited = True
            actuator.forcerange = (-limit, limit)
            actuator.ctrllimited = False
            actuator.gear = [1.0, 0, 0, 0, 0, 0]
            for candidate in spec.joints:
                if candidate.name == joint:
                    candidate.damping = np.zeros((3, 1))
                    candidate.frictionloss = 0.0
                    # Stiff friction constraint, as in the policies' training setup.
                    candidate.solref_friction = (-5.0e4, -2.0e2)
                    candidate.solimp_friction = (0.99, 0.9999, 0.001, 0.5, 2.0)
                    break
        if self.scenario.terrain is not None:
            add_terrain(spec, self.scenario.terrain)
        model = spec.compile()
        model.opt.timestep = _PHYSICS_DT
        self.model = model
        self.data = mujoco.MjData(model)
        self.trunk = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "trunk_base")
        joint_ids = [int(model.actuator_trnid[i, 0]) for i in range(model.nu)]
        self.joint_names = [
            mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_JOINT, j) for j in joint_ids
        ]
        gyro_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_SENSOR, "imu_ang_vel")
        self._gyro = int(model.sensor_adr[gyro_id])
        self._qadr = model.jnt_qposadr[joint_ids]
        self._dadr = model.jnt_dofadr[joint_ids]
        model.dof_armature[self._dadr] = 0.0018077432831600838
        mujoco.mj_setConst(model, self.data)

    def _reset_pose(self) -> None:
        model, data = self.model, self.data
        free = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, "trunk_base_freejoint")
        adr = int(model.jnt_qposadr[free])
        data.qpos[adr : adr + 7] = [0.0, 0.0, _SPAWN_HEIGHT, 1.0, 0.0, 0.0, 0.0]
        data.qpos[self._qadr] = self.policy.default_pose
        self.servos.reset()
        self._target = self.policy.default_pose.astype(np.float64)
        self._last_action = np.zeros(model.nu, dtype=np.float32)
        self._friction_rows = None
        mujoco.mj_forward(model, data)

    def _projected_gravity(self) -> np.ndarray:
        w, x, y, z = self.data.xquat[self.trunk]
        v = np.array([x, y, z])
        g = np.array([0.0, 0.0, -1.0])
        t = np.cross(v, g) * 2
        return (g - w * t + np.cross(v, t)).astype(np.float32)

    def control(self, time_s: float) -> None:
        data = self.data
        gyro = data.sensordata[self._gyro : self._gyro + 3]
        command = np.zeros(3 + _NO_HEAD_COMMANDS, dtype=np.float32)
        command[0] = self.scenario.command
        observation = np.concatenate(
            [
                gyro.astype(np.float32),
                self._projected_gravity(),
                data.qpos[self._qadr].astype(np.float32) - self.policy.default_pose,
                data.qvel[self._dadr].astype(np.float32),
                self._last_action,
                command,
            ]
        )
        action = self.policy.act(observation)
        self._last_action = action
        self._target = self.policy.default_pose + action * self.policy.action_scale

    def physics_step(self) -> None:
        model, data = self.model, self.data
        q = data.qpos[self._qadr]
        dq = data.qvel[self._dadr]
        torque = self.servos.torque(self._target, q, dq)
        data.ctrl[:] = torque
        # Gearbox friction depends on the load seen at each servo (BAM friction budget).
        external = -data.qfrc_bias[self._dadr] + data.qfrc_constraint[self._dadr]
        external -= self._friction_constraint_force()
        loss, damping = friction_budget(data.qfrc_actuator[self._dadr], external, dq)
        model.dof_frictionloss[self._dadr] = loss
        model.dof_damping[self._dadr] = damping
        mujoco.mj_step(model, data)

    def _friction_constraint_force(self) -> np.ndarray:
        """Friction-loss constraint force MuJoCo applied on each servo dof last step."""
        data = self.data
        if data.nefc == 0:
            return np.zeros(len(self._dadr))
        rows = data.efc_type[: data.nefc] == mujoco.mjtConstraint.mjCNSTR_FRICTION_DOF
        force = np.zeros(self.model.nv)
        np.add.at(force, data.efc_id[: data.nefc][rows], data.efc_force[: data.nefc][rows])
        return force[self._dadr]

    def servo_load(self) -> np.ndarray:
        return np.asarray(self.data.ctrl, dtype=float) / self.servos.stall_torque

    def provenance(self) -> dict:
        info = robot_info("microduck")
        return {
            "robot": "microduck",
            "policy": self.scenario.policy,
            "policy_sha256": hashlib.sha256(self.policy_path.read_bytes()).hexdigest(),
            "servo_model": "BAM XL330 M6 (reimplemented)",
            "credit": info.credit,
        }
