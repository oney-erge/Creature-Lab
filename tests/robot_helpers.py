"""Synthetic robot runs for tests that must not need a simulator."""

from __future__ import annotations

import numpy as np

from creature_lab.robots.analysis import analyze
from creature_lab.robots.checkup import Checkup, ConditionResult, ShoveRow
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
    qpos_width: int = 9,
    title: str = "",
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
        title=title,
    )
    qpos = np.zeros((steps, qpos_width))
    qpos[:, 2] = 0.12
    qpos[:, 3] = 1.0  # identity quaternion, so forward kinematics is well defined
    return RobotRun(
        scenario=scenario,
        joint_names=["hip", "knee"],
        time=time,
        qpos=qpos,
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


def saved_checkup(
    folder, policy: str, *, stays_down: bool, robot: str = "microduck", qpos_width: int = 9
) -> Checkup:
    """Write a small but complete check-up (runs plus checkup.json) and return it."""
    runs = folder / "runs"
    baseline = synthetic_run(
        robot=robot, policy=policy, qpos_width=qpos_width, title="Baseline walk"
    )
    baseline.save(runs / "baseline")
    fall = synthetic_run(
        robot=robot,
        policy=policy,
        qpos_width=qpos_width,
        fall_at=4.6,
        recover_at=None if stays_down else 5.6,
        push_n=3.0,
        pushed_outside=True,
        title="3 N shove",
    )
    fall.save(runs / "shove_3N_fall")
    synthetic_run(
        robot=robot, policy=policy, qpos_width=qpos_width, push_n=1.0, title="1 N shove"
    ).save(runs / "shove_1N_ok")
    ice = synthetic_run(
        robot=robot,
        policy=policy,
        qpos_width=qpos_width,
        fall_at=4.5,
        slide=0.3,
        grip=0.15,
        title="Floor grip at 0.15× normal",
    )
    ice.save(runs / "grip_0.15")

    def row(force, up, got, down, fall_run=None, ok_run=None):
        return ShoveRow(
            force_n=force,
            total=8,
            stayed_up=up,
            got_up=got,
            stayed_down=down,
            example_fall_run=fall_run,
            example_ok_run=ok_run,
        )

    if stays_down:
        shoves = [row(1, 8, 0, 0, ok_run="shove_1N_ok"), row(3, 1, 0, 7, "shove_3N_fall")]
    else:
        shoves = [row(1, 7, 1, 0, ok_run="shove_1N_ok"), row(3, 3, 5, 0, "shove_3N_fall")]
    checkup = Checkup(
        robot=robot,
        policy=policy,
        command=0.5,
        baseline=analyze(baseline),
        baseline_run="baseline",
        shoves=shoves,
        conditions=[
            ConditionResult(
                key="grip_0.15",
                label="Floor grip at 0.15× normal",
                passed=False,
                distance_m=0.3,
                relative_distance=0.2,
                analysis=analyze(ice),
                run="grip_0.15",
            )
        ],
    )
    (folder / "checkup.json").write_text(checkup.model_dump_json(indent=2), encoding="utf-8")
    return checkup
