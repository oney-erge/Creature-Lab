"""Unitree G1 (12 leg joints) with Unitree's own pretrained walking policy."""

from __future__ import annotations

import hashlib
from importlib import resources

import mujoco
import numpy as np

from creature_lab.robots.catalog import robot_info
from creature_lab.robots.fetch import is_installed, robot_dir
from creature_lab.robots.policies import G1WalkPolicy
from creature_lab.robots.rollout import MujocoRobot
from creature_lab.robots.scene import load_model, write_studio_scene
from creature_lab.robots.types import Scenario

# Gains and scales from unitree_rl_gym/deploy/deploy_mujoco/configs/g1.yaml.
_KP = np.array([100, 100, 100, 150, 40, 40] * 2, dtype=np.float64)
_KD = np.array([2, 2, 2, 4, 2, 2] * 2, dtype=np.float64)
_DEFAULT = np.array([-0.1, 0.0, 0.0, 0.3, -0.2, 0.0] * 2, dtype=np.float64)
_ACTION_SCALE = 0.25
_ANG_VEL_SCALE = 0.25
_DOF_VEL_SCALE = 0.05
_COMMAND_SCALE = np.array([2.0, 2.0, 0.25])
_GAIT_PERIOD_S = 0.8
_PHYSICS_DT = 0.002


class UnitreeG1(MujocoRobot):
    """PD-controlled legs driven by the pretrained LSTM policy."""

    substeps = 10

    def __init__(self, scenario: Scenario) -> None:
        super().__init__(scenario)
        if not is_installed("unitree_g1"):
            raise FileNotFoundError(
                "The G1 model is not downloaded yet; run: creature-lab robots fetch unitree_g1"
            )
        folder = robot_dir("unitree_g1")
        scene = write_studio_scene(folder, "Unitree G1", "g1_12dof.xml", tile_m=0.5)
        model = load_model(scene, scenario.terrain)
        model.opt.timestep = _PHYSICS_DT
        self.model = model
        self.data = mujoco.MjData(model)
        self.trunk = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "pelvis")
        self.joint_names = [
            mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_JOINT, int(model.actuator_trnid[i, 0]))
            for i in range(model.nu)
        ]
        self.policy = G1WalkPolicy()
        self._limit = np.array(
            [model.jnt_actfrcrange[int(model.actuator_trnid[i, 0])][1] for i in range(model.nu)]
        )
        self.finish_setup()
        self.data.qpos[:] = model.qpos0
        self.data.qpos[7:19] = _DEFAULT
        self._target = _DEFAULT.copy()
        self._action = np.zeros(12, dtype=np.float32)
        self._torque = np.zeros(12)
        mujoco.mj_forward(model, self.data)

    def _gravity(self) -> np.ndarray:
        w, x, y, z = self.data.qpos[3:7]
        return np.array([2 * (-z * x + w * y), -2 * (z * y + w * x), 1 - 2 * (w * w + z * z)])

    def control(self, time_s: float) -> None:
        data = self.data
        phase = (time_s % _GAIT_PERIOD_S) / _GAIT_PERIOD_S
        command = np.array([self.scenario.command, 0.0, 0.0]) * _COMMAND_SCALE
        observation = np.concatenate(
            [
                data.qvel[3:6] * _ANG_VEL_SCALE,
                self._gravity(),
                command,
                data.qpos[7:19] - _DEFAULT,
                data.qvel[6:18] * _DOF_VEL_SCALE,
                self._action,
                [np.sin(2 * np.pi * phase), np.cos(2 * np.pi * phase)],
            ]
        )
        self._action = self.policy.act(observation)
        self._target = _DEFAULT + self._action * _ACTION_SCALE

    def physics_step(self) -> None:
        data = self.data
        self._torque = (self._target - data.qpos[7:19]) * _KP - data.qvel[6:18] * _KD
        data.ctrl[:] = self._torque
        mujoco.mj_step(self.model, data)

    def servo_load(self) -> np.ndarray:
        return self._torque / self._limit

    def provenance(self) -> dict:
        info = robot_info("unitree_g1")
        weights = resources.files("creature_lab.robots").joinpath("data", "unitree_g1_policy.npz")
        return {
            "robot": "unitree_g1",
            "policy": self.scenario.policy,
            "policy_sha256": hashlib.sha256(weights.read_bytes()).hexdigest(),
            "credit": info.credit,
        }
