"""Damage tests: a motor limited to part of its torque, and commands that reach the motors late."""

from __future__ import annotations

import numpy as np
import pytest
from robot_helpers import synthetic_run

from creature_lab.robots.analysis import analyze, joint_text
from creature_lab.robots.checkup import weak_joint
from creature_lab.robots.types import Scenario

BASE = {"robot": "microduck", "policy": "velstand"}


def test_unused_damage_fields_leave_a_scenarios_hash_alone():
    plain = Scenario(**BASE)
    assert Scenario(**BASE, weak_strength=1.0, delay_ms=0.0).digest() == plain.digest()
    assert Scenario(**BASE, delay_ms=40.0).digest() != plain.digest()
    assert Scenario(**BASE, delay_ms=40.0).delay_steps == 2


def test_the_weakened_motor_is_the_one_that_works_hardest_in_the_baseline():
    run = synthetic_run()
    run.load = np.zeros((len(run), 2))
    run.load[:, 1] = 0.5  # the knee works at half its limit all along
    run.load[100, 0] = 0.99  # one spike on the hip is not the hip working hard
    assert weak_joint(run) == "knee"
    assert joint_text("right_ankle_pitch_joint") == "right ankle pitch"


def _damaged(**changes) -> object:
    run = synthetic_run(fall_at=4.6, slide=0.2)
    run.scenario = run.scenario.model_copy(update=changes)
    return run


def test_a_weak_motor_at_its_limit_before_the_fall_is_the_cause():
    run = _damaged(weak_joint="knee", weak_strength=0.3)
    run.load = np.zeros((len(run), 2))
    run.load[run.time > 3.6, 1] = 1.0
    result = analyze(run)
    assert result.cause == "weak_motor"
    assert result.cause_text.startswith("The knee motor, down to 30% of its strength")
    assert result.evidence[1].label == "Weak motor at its limit"


def test_late_commands_on_a_normal_floor_are_named_before_the_sliding_feet():
    result = analyze(_damaged(delay_ms=40.0))
    assert result.cause == "delay"
    assert "40 ms late" in result.cause_text and "slid (median 0.20 m/s)" in result.cause_text
    # On a slippery floor the slide is the better explanation.
    assert analyze(_damaged(delay_ms=40.0, grip=0.15)).cause == "slipped"


def test_a_damaged_robot_that_stays_up_says_what_it_walked_with():
    run = synthetic_run()
    run.scenario = run.scenario.model_copy(update={"weak_joint": "knee", "weak_strength": 0.6})
    assert (
        analyze(run).verdict == "Walked 2.0 m without falling, with the knee motor at 60% strength."
    )


# ---- in the simulator -------------------------------------------------------------------------

mujoco = pytest.importorskip("mujoco")
pytest.importorskip("onnxruntime")

from pack_helpers import copy_example  # noqa: E402

from creature_lab.robots.pack import load_pack, register_pack  # noqa: E402
from creature_lab.robots.packbot import PackRobot  # noqa: E402
from creature_lab.robots.rollout import run_robot  # noqa: E402


@pytest.fixture
def stick_biped(tmp_path, monkeypatch):
    monkeypatch.setenv("CREATURE_LAB_ROBOTS_DIR", str(tmp_path / "cache"))
    folder = copy_example(tmp_path / "pack")
    register_pack(folder)
    return folder


def test_a_weak_motor_never_pushes_past_its_reduced_limit(stick_biped):
    scenario = Scenario(
        robot="stick_biped",
        policy="stand",
        seconds=1.0,
        push_n=300,
        push_at_s=0.3,
        weak_joint="left_knee",
        weak_strength=0.2,
    )
    robot = PackRobot(scenario, load_pack(stick_biped))
    index = robot.joint_names.index("left_knee")
    limit = float(robot.torque_limits()[index]) * 0.2
    dof = int(robot._dadr[index])
    biggest = 0.0
    step = robot.physics_step

    def watched() -> None:
        nonlocal biggest
        step()
        biggest = max(biggest, abs(float(robot.data.qfrc_actuator[dof])))

    robot.physics_step = watched
    run = run_robot(robot)
    assert 0.0 < biggest <= limit + 1e-6
    assert np.abs(run.load[:, index]).max() >= 0.95  # shown at its own, lower limit


def test_late_commands_reach_the_motors_whole_control_steps_later(stick_biped):
    scenario = Scenario(robot="stick_biped", policy="stand", seconds=0.2, delay_ms=40.0)
    robot = PackRobot(scenario, load_pack(stick_biped))
    decided, applied = [], []
    control, step = robot.control, robot.physics_step

    def deciding(time_s: float) -> None:
        control(time_s)
        decided.append(robot._target.copy())

    def applying() -> None:
        applied.append(robot._target.copy())
        step()

    robot.control, robot.physics_step = deciding, applying
    start = robot._target.copy()
    run_robot(robot)
    held = applied[:: robot.substeps]  # the target in force during each control step
    np.testing.assert_array_equal(held[0], start)
    np.testing.assert_array_equal(held[1], start)
    for k in range(2, len(held)):
        np.testing.assert_array_equal(held[k], decided[k - 2])
