"""Synthetic robot runs for tests that must not need a simulator."""

from __future__ import annotations

import numpy as np

from creature_lab.robots.types import CONTROL_HZ, SUPPORT_VERTICES, RobotRun, Scenario


def synthetic_run(
    *,
    robot: str = "microduck",
    policy: str = "velstand",
    seconds: float = 10.0,
    fall_at: float | None = None,
    recover_at: float | None = None,
    push_n: float = 0.0,
    push_at: float = 4.0,
    slide: float = 0.0,
    load: float = 0.0,
    pushed_outside: bool = False,
    grip: float = 1.0,
) -> RobotRun:
    """A walking run that optionally falls, recovers, is shoved, slips or saturates."""
    steps = int(seconds * CONTROL_HZ)
    time = np.arange(1, steps + 1) / CONTROL_HZ
    upright = np.ones(steps)
    if fall_at is not None:
        upright[time >= fall_at] = 0.1
    if recover_at is not None:
        upright[time >= recover_at] = 1.0
    trunk = np.zeros((steps, 3))
    trunk[:, 0] = 0.2 * time
    trunk[:, 2] = 0.12
    com = trunk.copy()
    if pushed_outside:
        window = (time >= push_at) & (time <= push_at + 0.8)
        com[window, 1] = 0.2  # centre of mass well outside a 10 cm foot outline
    com_vel = np.zeros((steps, 3))
    support = np.full((steps, SUPPORT_VERTICES, 2), np.nan)
    square = np.array([[-0.05, -0.05], [0.05, -0.05], [0.05, 0.05], [-0.05, 0.05]])
    for frame in range(steps):
        support[frame, :4] = square + trunk[frame, :2]
    push_force = np.zeros(steps)
    if push_n:
        push_force[(time >= push_at) & (time < push_at + 0.2)] = push_n
    scenario = Scenario(
        robot=robot,
        policy=policy,
        seconds=seconds,
        push_n=push_n,
        push_at_s=push_at,
        grip=grip,
    )
    return RobotRun(
        scenario=scenario,
        joint_names=["hip", "knee"],
        time=time,
        qpos=np.zeros((steps, 9)),
        qvel=np.zeros((steps, 8)),
        load=np.full((steps, 2), load),
        upright=upright,
        trunk_pos=trunk,
        com=com,
        com_vel=com_vel,
        support=support,
        slide_speed=np.full(steps, slide),
        push_force=push_force,
        provenance={"creature_lab": "test", "mujoco": "test", "policy_sha256": "0" * 64},
    )
