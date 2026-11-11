"""Stairs, a ramp, rough ground and stepping stones: the courses, what is recorded, the causes."""

from __future__ import annotations

import math

import numpy as np
import pytest
from robot_helpers import synthetic_run

from creature_lab.robots.analysis import analyze
from creature_lab.robots.terrain import (
    Terrain,
    course,
    description,
    ground_height,
    key,
    label,
    layout,
)
from creature_lab.robots.types import RobotRun, Scenario


def _along(terrain: Terrain, xs: list[float]) -> list[float]:
    heights = ground_height(layout(terrain), np.array(xs), np.zeros(len(xs)))
    return [round(float(h), 4) for h in heights]


# ---- the courses ------------------------------------------------------------------------------


def test_the_course_is_sized_from_the_robots_height():
    humanoid = {key(t): t for t in course(134)}
    assert [t.level for t in humanoid.values() if t.kind == "stairs"] == [0.04, 0.08, 0.12, 0.16]
    assert [t.level for t in humanoid.values() if t.kind == "ramp"] == [8.0, 16.0, 24.0]
    assert list(humanoid)[:2] == ["terrain_stairs_4cm", "terrain_stairs_8cm"]
    desk = course(25)
    assert [t.level for t in desk if t.kind == "stairs"] == [0.008, 0.015, 0.022, 0.03]
    assert desk[0].unit_m == pytest.approx(0.055) and humanoid["terrain_stairs_4cm"].unit_m == 0.295
    assert label(desk[0]) == "Stairs with 8 mm steps" and key(desk[0]) == "terrain_stairs_8mm"
    assert label(humanoid["terrain_ramp_16deg"]) == "Ramp sloping 16°"
    assert label(humanoid["terrain_stones_11cm"]) == "Stepping stones 11 cm apart"


def test_stairs_go_up_four_steps_along_a_landing_and_down_again():
    stairs = Terrain(kind="stairs", level=0.1, unit_m=0.3, start_m=0.5)
    centres = [0.4] + [0.65 + 0.3 * i for i in range(9)] + [3.4]
    assert _along(stairs, centres) == [0.0, 0.1, 0.2, 0.3, 0.4, 0.4, 0.4, 0.3, 0.2, 0.1, 0.0]
    assert ground_height(layout(stairs), np.array([1.0]), np.array([5.0]))[0] == 0.0  # beside it


def test_a_ramp_rises_at_its_slope_and_comes_down_the_other_side():
    ramp = Terrain(kind="ramp", level=20.0, unit_m=0.2, start_m=0.5)
    slope = math.tan(math.radians(20.0))
    up, top, down = _along(ramp, [0.75, 1.6, 2.9])
    assert up == pytest.approx(0.25 * slope, abs=1e-4)
    assert top == pytest.approx(1.0 * slope, abs=1e-4)  # five 0.2 m units of run
    assert down == pytest.approx(0.2 * slope, abs=1e-4)


def test_stepping_stones_stand_over_a_pit_with_gaps_on_the_walking_line():
    stones = Terrain(kind="stones", level=0.1, unit_m=0.4, start_m=0.8)
    lay = layout(stones)
    assert lay.floor_z == pytest.approx(-0.4 / 0.3 * 0.4)
    pit = round(lay.floor_z, 4)
    # The start platform (to 0.8 m), a 10 cm gap, a 40 cm stone, the next gap, the next stone.
    assert _along(stones, [0.0, 0.85, 1.1, 1.35, 1.6]) == [0.0, pit, 0.0, pit, 0.0]
    assert _along(stones, [1.3, 1.31]) == [0.0, pit]


def test_rough_ground_is_the_same_for_the_same_seed_and_stays_under_its_level():
    rough = Terrain(kind="rough", level=0.05, unit_m=0.2, start_m=0.8)
    again = Terrain(kind="rough", level=0.05, unit_m=0.2, start_m=0.8)
    other = Terrain(kind="rough", level=0.05, unit_m=0.2, start_m=0.8, seed=1)
    xs = list(np.arange(0.9, 5.0, 0.2))
    assert _along(rough, xs) == _along(again, xs) != _along(other, xs)
    assert 0.0 <= min(_along(rough, xs)) and max(_along(rough, xs)) <= 0.05


def test_the_browser_gets_every_box_and_the_floor_height():
    stones = Terrain(kind="stones", level=0.1, unit_m=0.4, start_m=0.8)
    drawn = description(stones)
    assert drawn["kind"] == "stones" and drawn["floorZ"] < 0
    assert len(drawn["boxes"]) == len(layout(stones).boxes)
    assert set(drawn["boxes"][0]) == {"pos", "half", "quat", "rgba"}
    assert description(None) is None


# ---- scenarios and saved runs -----------------------------------------------------------------


def test_a_flat_floor_scenario_keeps_the_hash_it_had_before_terrain():
    saved = {
        "robot": "unitree_g1_29dof",
        "policy": "standard",
        "command": 0.6,
        "seconds": 10.0,
        "push_n": 0.0,
        "push_side": "left",
        "push_at_s": 4.0,
        "push_for_s": 0.2,
        "grip": 1.0,
        "battery_v": 7.4,
        "payload_kg": 0.0,
        "title": "Baseline walk",
    }
    digest = "sha256:c0f463684310cf97998cb75697af3cd0e42d85965a7161a11ded6fc4133f2ff0"
    assert Scenario.model_validate(saved).digest() == digest
    stairs = Terrain(kind="stairs", level=0.1, unit_m=0.3, start_m=0.5)
    assert Scenario.model_validate({**saved, "terrain": stairs}).digest() != digest


def test_a_run_saved_before_terrain_reads_as_flat_with_nothing_caught(tmp_path):
    run = synthetic_run()
    run.save(tmp_path / "run")
    with np.load(tmp_path / "run" / "states.npz") as arrays:
        old = {name: arrays[name] for name in arrays.files if name not in RobotRun.OPTIONAL}
    np.savez_compressed(tmp_path / "run" / "states.npz", **old)
    again = RobotRun.read(tmp_path / "run")
    assert not again.edge_force.any() and not again.lowest_contact_z.any()


# ---- why it fell ------------------------------------------------------------------------------


def _on(terrain: Terrain, *, fall_at: float | None = 4.6, mass_kg: float = 0.8) -> RobotRun:
    run = synthetic_run(fall_at=fall_at)
    run.scenario = run.scenario.model_copy(update={"terrain": terrain})
    run.provenance["mass_kg"] = mass_kg
    return run


STAIRS = Terrain(kind="stairs", level=0.02, unit_m=0.06, start_m=0.15)


def test_a_foot_caught_on_a_step_just_before_the_fall_is_the_cause():
    run = _on(STAIRS)
    run.edge_force[(run.time >= 3.9) & (run.time < 3.96)] = 6.0  # about 75% of body weight
    result = analyze(run)
    assert result.cause == "tripped"
    assert "caught the edge of a step at 3.90 s" in (result.cause_text or "")
    assert result.evidence[1].label == "Foot against the side of a step"


def test_a_light_brush_or_an_old_bump_on_the_step_is_not_blamed():
    run = _on(STAIRS)
    run.edge_force[(run.time >= 4.0) & (run.time < 4.04)] = 0.5  # under a quarter of the weight
    run.edge_force[(run.time >= 1.0) & (run.time < 1.04)] = 50.0  # long before it tipped
    assert analyze(run).cause == "unclear"


def test_a_foot_down_in_a_gap_between_stones_is_the_cause():
    stones = Terrain(kind="stones", level=0.02, unit_m=0.07, start_m=0.15)
    run = _on(stones)
    run.edge_force[(run.time >= 4.0) & (run.time < 4.04)] = 6.0
    run.lowest_contact_z[run.time >= 4.2] = -0.05
    result = analyze(run)
    assert result.cause == "missed_footing"
    assert "went down into a gap at 4.20 s" in (result.cause_text or "")
    assert result.evidence[1].value == "5 cm down"


def test_a_fall_on_a_ramp_with_nothing_caught_blames_the_slope():
    run = _on(Terrain(kind="ramp", level=24.0, unit_m=0.05, start_m=0.15))
    result = analyze(run)
    assert result.cause == "slope"
    assert result.cause_text.startswith("On the 24° slope")


def test_walking_the_course_says_where_it_walked():
    run = _on(STAIRS, fall_at=None)
    assert analyze(run).verdict == "Walked 2.0 m over stairs with 2 cm steps without falling."


# ---- in the simulator -------------------------------------------------------------------------

mujoco = pytest.importorskip("mujoco")
pytest.importorskip("onnxruntime")

from pack_helpers import copy_example  # noqa: E402

from creature_lab.robots.pack import load_pack, register_pack  # noqa: E402


@pytest.fixture
def stick_biped(tmp_path, monkeypatch):
    monkeypatch.setenv("CREATURE_LAB_ROBOTS_DIR", str(tmp_path / "cache"))
    folder = copy_example(tmp_path / "pack")
    register_pack(folder)
    return folder


def test_the_robot_stands_on_the_stepping_stones_platform_and_it_counts_as_ground(stick_biped):
    from creature_lab.robots.api import run_scenario

    stones = Terrain(kind="stones", level=0.05, unit_m=0.2, start_m=0.4)
    run = run_scenario(
        Scenario(robot="stick_biped", policy="stand", seconds=2.0, command=0.0, terrain=stones)
    )
    assert not analyze(run).fell
    assert not np.isnan(run.support[-1, 0, 0])  # the feet on the platform make an outline
    assert abs(float(run.lowest_contact_z[-1])) < 0.01 and not run.edge_force.any()


def test_a_height_scan_reads_the_ground_under_a_grid_that_turns_with_the_robot(stick_biped):
    from creature_lab.robots.packbot import PackRobot

    toml = stick_biped / "robot.toml"
    scan = (
        '\n[[policies.observation]]\nterm = "height_scan"\ngrid_m = [0.4, 0.2]\n'
        "spacing_m = 0.2\nmax_distance_m = 5.0\n"
    )
    toml.write_text(toml.read_text(encoding="utf-8") + scan, encoding="utf-8")
    stairs = Terrain(kind="stairs", level=0.05, unit_m=0.3, start_m=0.05)
    robot = PackRobot(
        Scenario(robot="stick_biped", policy="stand", terrain=stairs), load_pack(stick_biped)
    )
    (term,) = robot._terms
    z = float(robot.data.xpos[robot.trunk][2])
    # Facing +x: the grid's front column (x = +0.2 m) is over the first step.
    np.testing.assert_allclose(term(0.0), [z, z, z - 0.05, z, z, z - 0.05], atol=1e-9)
    # Turned to face +y, the grid's right-hand row (y = -0.1 m) lies over the step instead.
    q = robot._root_q
    robot.data.qpos[q + 3 : q + 7] = [math.cos(math.pi / 4), 0.0, 0.0, math.sin(math.pi / 4)]
    mujoco.mj_kinematics(robot.model, robot.data)
    z = float(robot.data.xpos[robot.trunk][2])
    np.testing.assert_allclose(term(0.0), [z - 0.05] * 3 + [z] * 3, atol=1e-9)
