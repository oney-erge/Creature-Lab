"""Dynamixel XL330 servo model used by the Microduck policies.

The Microduck walking policies were trained against Rhoban's BAM "M6" servo model
(https://github.com/Rhoban/bam, Apache-2.0, Copyright 2025 Marc Duclusaud & Grégoire
Passault): a voltage-controlled DC motor behind a firmware P-loop, plus a load-dependent
friction budget. Driving the joints with plain position actuators makes the same policy
behave differently, so this module reimplements just the XL330/M6 equations in numpy.
``tests/test_robot_actuator.py`` pins its output to values produced by the BAM package.

The module is pure numpy: the MuJoCo glue lives in ``creature_lab.robots.mujoco_rollout``.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

#: Fitted XL330 "M6" parameters from ``bam/params/xl330/m6.json``.
M6 = {
    "kt": 0.36601349688984386,
    "R": 2.8113923539223227,
    "armature": 0.0018077432831600838,
    "friction_base": 0.004771183165566,
    "friction_stribeck": 0.004676345799486616,
    "load_friction_motor": 0.2667860954283698,
    "load_friction_external": 8.515871897059342e-06,
    "load_friction_motor_stribeck": 1.0722918395099123e-05,
    "load_friction_external_stribeck": 0.08077928978935671,
    "load_friction_motor_quad": 0.009972471242139415,
    "load_friction_external_quad": 0.004902565732332559,
    "dtheta_stribeck": 2.890372094130307,
    "alpha": 8.683259907618984,
    "friction_viscous": 0.005359668274599504,
}

# XL330 firmware: encoder counts per rev / (P-gain divisor * PWM limit) turns a
# kp * radians error into a duty cycle.
_ERROR_GAIN = (4096 / (2 * np.pi)) / (256 * 885)

#: Microduck keeps the servo's firmware stiffness at 200 (as in training).
FIRMWARE_KP = 200.0
NOMINAL_BATTERY_V = 7.4
#: Effective voltage never sags below this (as in training).
MIN_BATTERY_V = 6.0
#: Volts lost per N·m of total servo load.
BATTERY_SAG_V_PER_NM = 0.1


@dataclass
class ServoBank:
    """Servos sharing one battery; ``torque`` must be called once per physics step."""

    count: int
    battery_v: float = NOMINAL_BATTERY_V
    firmware_kp: float = FIRMWARE_KP
    sag_v_per_nm: float = BATTERY_SAG_V_PER_NM
    min_v: float = MIN_BATTERY_V

    def __post_init__(self) -> None:
        self._previous_torque = np.zeros(self.count)

    @property
    def stall_torque(self) -> float:
        """Torque limit [N·m]: full battery voltage with the shaft held still."""
        return self.battery_v * M6["kt"] / M6["R"]

    def reset(self) -> None:
        self._previous_torque[:] = 0.0

    def effective_voltage(self) -> float:
        """Battery voltage after the sag caused by last step's total servo load."""
        if self.sag_v_per_nm <= 0:
            return self.battery_v
        sagged = self.battery_v - self.sag_v_per_nm * float(np.sum(np.abs(self._previous_torque)))
        return max(sagged, self.min_v)

    def torque(self, target: np.ndarray, q: np.ndarray, dq: np.ndarray) -> np.ndarray:
        """DC-motor torque for a firmware position command: ``kt*V/R - kt^2*dq/R``."""
        duty = np.clip((target - q) * self.firmware_kp * _ERROR_GAIN, -1.0, 1.0)
        volts = self.effective_voltage() * duty
        torque = M6["kt"] * volts / M6["R"] - (M6["kt"] ** 2) * dq / M6["R"]
        self._previous_torque = np.atleast_1d(torque).copy()
        return torque


def friction_budget(
    motor_torque: np.ndarray, external_torque: np.ndarray, dq: np.ndarray
) -> tuple[np.ndarray, float]:
    """Gearbox ``(frictionloss, damping)`` for the current load (BAM M6 formulation)."""
    p = M6
    gearbox = np.abs(
        external_torque * p["load_friction_external"] - motor_torque * p["load_friction_motor"]
    )
    gearbox_stribeck = np.abs(
        external_torque * p["load_friction_external_stribeck"]
        - motor_torque * p["load_friction_motor_stribeck"]
    )
    stribeck = np.exp(-(np.abs(dq / p["dtheta_stribeck"]) ** p["alpha"]))

    loss = p["friction_base"] + gearbox
    loss = loss + stribeck * p["friction_stribeck"] + gearbox_stribeck * stribeck

    opposed = np.sign(external_torque) != np.sign(motor_torque)
    motor_dominates = np.abs(external_torque) < np.abs(motor_torque)
    external_dominates = np.abs(external_torque) > np.abs(motor_torque)
    quad_motor_side = p["load_friction_external_quad"] * np.abs(external_torque) ** 2
    quad_external_side = p["load_friction_motor_quad"] * np.abs(motor_torque) ** 2
    loss = (
        loss
        + stribeck
        * (motor_dominates * quad_motor_side + external_dominates * quad_external_side)
        * opposed
    )
    return loss, p["friction_viscous"]
