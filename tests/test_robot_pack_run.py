"""Running and validating robot packs. Needs the ``robots`` extra (MuJoCo and onnxruntime)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from pack_helpers import copy_example, edit, make_policy_module
from typer.testing import CliRunner

pytest.importorskip("mujoco")
pytest.importorskip("onnxruntime")

import mujoco  # noqa: E402
import numpy as np  # noqa: E402

from creature_lab.cli import app  # noqa: E402
from creature_lab.robots.analysis import analyze  # noqa: E402
from creature_lab.robots.api import run_scenario  # noqa: E402
from creature_lab.robots.catalog import all_robots  # noqa: E402
from creature_lab.robots.checkup import run_checkup  # noqa: E402
from creature_lab.robots.fetch import is_installed  # noqa: E402
from creature_lab.robots.pack import load_pack, register_pack  # noqa: E402
from creature_lab.robots.packcheck import validate_pack  # noqa: E402
from creature_lab.robots.types import Scenario  # noqa: E402

runner = CliRunner()


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("CREATURE_LAB_ROBOTS_DIR", str(tmp_path / "cache"))
    return tmp_path / "cache"


@pytest.fixture
def pack_copy(tmp_path):
    return copy_example(tmp_path / "pack")


def test_the_example_pack_validates_and_stands(pack_copy):
    report = validate_pack(pack_copy)
    assert report.ok, report.errors
    assert not report.warnings
    assert report.facts["joints"] == "6"
    assert "27 numbers" in report.facts["observation"]
    assert "stayed upright" in report.facts["trial walk (stand)"]
    assert (pack_copy / "checkup_scene.xml").is_file()  # the studio scene sits beside the model


def test_a_pack_runs_like_any_robot_and_a_hard_shove_knocks_it_over(cache, pack_copy):
    register_pack(pack_copy)
    assert is_installed("stick_biped")
    calm = run_scenario(Scenario(robot="stick_biped", policy="stand", seconds=6.0))
    assert not analyze(calm).fell
    assert calm.provenance["robot"] == "stick_biped"
    assert len(calm.provenance["policy_sha256"]) == 64
    shoved = run_scenario(
        Scenario(robot="stick_biped", policy="stand", seconds=6.0, push_n=400, push_at_s=2.0)
    )
    result = analyze(shoved)
    assert result.fell and result.cause_text


def test_a_check_up_runs_on_a_pack_and_saves_its_results(cache, pack_copy, tmp_path):
    with (pack_copy / "robot.toml").open("a", encoding="utf-8") as handle:
        handle.write("\n[levels]\nshoves_n = [10, 500]\ngrips = [0.4]\npayloads_kg = [2]\n")
    register_pack(pack_copy)
    result = run_checkup("stick_biped", "stand", tmp_path / "out")
    assert [row.force_n for row in result.shoves] == [10, 500]
    assert result.shoves[0].stayed_up == result.shoves[0].total
    assert result.shoves[1].stayed_up < result.shoves[1].total
    assert {c.key for c in result.conditions} == {"grip_0.4", "payload_2kg"}
    assert (tmp_path / "out" / "checkup.json").is_file()


@pytest.mark.parametrize(
    ("file", "old", "new", "expected"),
    [
        (
            "robot.toml",
            '[[observation]]\nterm = "joint_vel"\nscale = 0.05\n\n',
            "",
            "expects 27 observation numbers but the observation list gives 21",
        ),
        ("robot.toml", "right_knee      =", "right_knee_x    =", "has no joint with that name"),
        ("robot.toml", 'trunk = "trunk"', 'trunk = "torso"', "no body named 'torso'"),
        (
            "robot.toml",
            "[joints]\nleft_hip_roll   = { default = 0.0,  kp = 60.0, kd = 2.0 }\n",
            "[joints]\n",
            "does not list: left_hip_roll",
        ),
        (
            "stick_biped.xml",
            "<worldbody>",
            '<worldbody>\n<geom type="plane" size="2 2 0.1"/>',
            "own ground plane",
        ),
        (
            "stick_biped.xml",
            '<geom name="trunk_box"',
            '<geom name="floor" type="sphere" size="0.01"/>\n<geom name="trunk_box"',
            "named 'floor'",
        ),
        ("stick_biped.xml", "<joint damping", "<joint foo='1' damping", "could not load it"),
    ],
)
def test_each_mistake_gets_a_plain_message(pack_copy, file, old, new, expected):
    edit(pack_copy, file, old, new)
    report = validate_pack(pack_copy, simulate=False)
    assert not report.ok
    assert any(expected in line for line in report.errors), report.errors


def test_a_policy_with_the_wrong_number_of_actions_is_caught(pack_copy):
    module = make_policy_module()
    (pack_copy / "policy.onnx").write_bytes(module.policy_bytes(np.zeros((27, 5)), np.zeros(5)))
    report = validate_pack(pack_copy, simulate=False)
    assert any("outputs 5 actions" in line for line in report.errors), report.errors


def test_an_unsupported_policy_file_says_what_to_do(pack_copy):
    (pack_copy / "policy.pt").write_bytes(b"not a model")
    edit(pack_copy, "robot.toml", 'file = "policy.onnx"', 'file = "policy.pt"')
    report = validate_pack(pack_copy, simulate=False)
    assert any(".onnx or .npz" in line for line in report.errors), report.errors


def test_a_robot_that_falls_in_the_trial_is_a_warning_not_an_error(pack_copy):
    edit(
        pack_copy,
        "robot.toml",
        "left_knee       = { default = 0.0,",
        "left_knee       = { default = 1.5,",
    )
    edit(
        pack_copy,
        "robot.toml",
        "right_knee      = { default = 0.0,",
        "right_knee      = { default = 1.5,",
    )
    report = validate_pack(pack_copy)
    assert report.ok
    assert any("fell over" in line for line in report.warnings), report.warnings


def test_position_servos_are_supported(pack_copy):
    text = (pack_copy / "stick_biped.xml").read_text(encoding="utf-8")
    for joint in (
        "left_hip_roll",
        "left_hip_pitch",
        "left_knee",
        "right_hip_roll",
        "right_hip_pitch",
        "right_knee",
    ):
        text = text.replace(
            f'<motor name="{joint}_motor" joint="{joint}"/>',
            f'<position name="{joint}_motor" joint="{joint}" kp="80" kv="2.5" '
            'ctrlrange="-1.7 1.7"/>',
        )
    (pack_copy / "stick_biped.xml").write_text(text, encoding="utf-8")
    edit(pack_copy, "robot.toml", 'actuator = "pd"', 'actuator = "position"')
    report = validate_pack(pack_copy)
    assert report.ok, report.errors
    assert "stayed upright" in report.facts["trial walk (stand)"]


def test_sensors_can_feed_the_observation(pack_copy):
    edit(
        pack_copy,
        "stick_biped.xml",
        '<freejoint name="root"/>',
        '<freejoint name="root"/>\n<site name="imu" pos="0 0 0"/>',
    )
    edit(
        pack_copy,
        "stick_biped.xml",
        "</actuator>",
        '</actuator>\n<sensor><gyro name="imu_gyro" site="imu"/></sensor>',
    )
    edit(pack_copy, "robot.toml", 'term = "base_ang_vel"', 'term = "sensor"\nsensor = "imu_gyro"')
    report = validate_pack(pack_copy)
    assert report.ok, report.errors
    edit(pack_copy, "robot.toml", 'sensor = "imu_gyro"', 'sensor = "nope"')
    broken = validate_pack(pack_copy, simulate=False)
    assert any("no sensor 'nope'" in line and "imu_gyro" in line for line in broken.errors)


def test_a_torque_limit_missing_from_the_model_is_asked_for(pack_copy):
    edit(pack_copy, "stick_biped.xml", ' actuatorfrcrange="-20 20"', "")
    edit(pack_copy, "stick_biped.xml", '<motor ctrlrange="-20 20"/>', "<motor/>")
    report = validate_pack(pack_copy, simulate=False)
    assert any("torque_limit" in line for line in report.errors), report.errors
    for side in ("left", "right"):
        for joint in ("hip_roll", "hip_pitch", "knee"):
            name = f"{side}_{joint}"
            line = next(
                row
                for row in (pack_copy / "robot.toml").read_text(encoding="utf-8").splitlines()
                if row.startswith(name)
            )
            edit(pack_copy, "robot.toml", line, line.replace("{ ", "{ torque_limit = 20.0, "))
    assert validate_pack(pack_copy, simulate=False).ok


def test_validate_add_list_and_remove_work_from_the_command_line(cache, pack_copy):
    result = runner.invoke(app, ["robots", "validate", str(pack_copy)])
    assert result.exit_code == 0, result.output
    assert "Ready to add" in result.output

    result = runner.invoke(app, ["robots", "add", str(pack_copy)])
    assert result.exit_code == 0, result.output
    assert "Added Stick biped" in result.output

    listing = runner.invoke(app, ["robots", "list"])
    assert "stick-biped" in listing.output and "yours" in listing.output

    result = runner.invoke(app, ["robots", "fetch", "stick-biped"])
    assert result.exit_code == 0 and "nothing to download" in result.output

    result = runner.invoke(app, ["robots", "remove", "stick-biped"])
    assert result.exit_code == 0 and "files are still in" in result.output
    assert (pack_copy / "robot.toml").is_file()
    assert runner.invoke(app, ["robots", "remove", "stick-biped"]).exit_code == 1


def test_a_broken_pack_is_not_added(cache, pack_copy):
    edit(pack_copy, "robot.toml", 'trunk = "trunk"', 'trunk = "torso"')
    result = runner.invoke(app, ["robots", "add", str(pack_copy)])
    assert result.exit_code == 1
    assert "no body named" in result.output and "Not added" in result.output
    assert "stick_biped" not in all_robots()


# ---- the same robot, described as a pack, behaves exactly like the built-in one -------------

needs_g1 = pytest.mark.skipif(not is_installed("unitree_g1"), reason="Unitree G1 not downloaded")


def _g1_pack(folder: Path) -> Path:
    """The built-in G1 adapter's constants, written as a robot.toml."""
    from creature_lab.robots import g1
    from creature_lab.robots.fetch import robot_dir

    model_file = robot_dir("unitree_g1") / "g1_12dof.xml"
    model = mujoco.MjModel.from_xml_path(str(model_file))
    names = [
        mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_JOINT, int(model.actuator_trnid[i, 0]))
        for i in range(model.nu)
    ]
    joints = "\n".join(
        f"{name} = {{ default = {float(g1._DEFAULT[i])!r}, kp = {float(g1._KP[i])!r}, "
        f"kd = {float(g1._KD[i])!r} }}"
        for i, name in enumerate(names)
    )
    policy = Path(g1.__file__).parent / "data" / "unitree_g1_policy.npz"
    folder.mkdir()
    shutil.copy(policy, folder / "policy.npz")
    (folder / "robot.toml").write_text(
        f"""
key = "g1_as_pack"
title = "Unitree G1"
maker = "Unitree Robotics"
summary = "The G1, described as a robot pack."
height_cm = 130
mass_kg = 35
model = '{model_file}'
trunk = "pelvis"
physics_dt = 0.002
action_scale = 0.25
gait_period_s = 0.8
[license]
notice = "Unitree G1 model and policy, BSD 3-Clause."
credit = "Unitree"
[joints]
{joints}
[[observation]]
term = "base_ang_vel"
scale = 0.25
[[observation]]
term = "projected_gravity"
[[observation]]
term = "command"
scale = [2.0, 2.0, 0.25]
[[observation]]
term = "joint_pos"
[[observation]]
term = "joint_vel"
scale = 0.05
[[observation]]
term = "last_action"
[[observation]]
term = "gait_phase"
period_s = 0.8
[[policies]]
key = "motion"
title = "Unitree walking policy"
file = "policy.npz"
""",
        encoding="utf-8",
    )
    return folder


@needs_g1
@pytest.mark.parametrize(
    "changes",
    [
        {},
        {"push_n": 150, "push_at_s": 4.2},
        {"push_n": 300, "push_at_s": 4.5, "push_side": "right"},
        {"grip": 0.3},
        {"payload_kg": 10},
    ],
    ids=["walk", "shove-150N", "shove-300N-right", "slippery", "loaded"],
)
def test_the_g1_as_a_pack_matches_the_built_in_adapter_exactly(tmp_path, changes):
    from creature_lab.robots.g1 import UnitreeG1
    from creature_lab.robots.packbot import PackRobot
    from creature_lab.robots.rollout import run_robot

    pack = load_pack(_g1_pack(tmp_path / "g1"))
    scenario = Scenario(robot="unitree_g1", policy="motion", command=0.5, **changes)
    built_in = run_robot(UnitreeG1(scenario))
    described = run_robot(PackRobot(scenario, pack))
    assert described.joint_names == built_in.joint_names
    for name in built_in.ARRAYS:
        same = np.array_equal(getattr(built_in, name), getattr(described, name), equal_nan=True)
        assert same, name
