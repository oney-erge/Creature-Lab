"""``robots init``: drafting robot.toml from a model and the metadata a policy carries."""

from __future__ import annotations

import pytest
from pack_helpers import copy_example, make_policy_module
from typer.testing import CliRunner

pytest.importorskip("mujoco")
pytest.importorskip("onnxruntime")

import numpy as np  # noqa: E402

from creature_lab.cli import app  # noqa: E402
from creature_lab.robots.pack import PackError, load_pack, parse_pack  # noqa: E402
from creature_lab.robots.packcheck import validate_pack  # noqa: E402
from creature_lab.robots.packinit import draft_pack, write_draft  # noqa: E402

runner = CliRunner()

JOINTS = [
    "left_hip_roll",
    "left_hip_pitch",
    "left_knee",
    "right_hip_roll",
    "right_hip_pitch",
    "right_knee",
]


def _metadata(**changes) -> dict[str, str]:
    """What mjlab writes into a policy it exports (numbers to three decimals)."""
    meta = {
        "joint_names": ",".join(JOINTS),
        "default_joint_pos": ",".join(["0.000"] * 6),
        "joint_stiffness": "60.000,80.000,80.000,60.000,80.000,80.000",
        "joint_damping": "2.000,2.500,2.500,2.000,2.500,2.500",
        "action_scale": ",".join(["0.250"] * 6),
        "observation_names": "base_ang_vel,projected_gravity,command,joint_pos,joint_vel,actions",
        "observation_terms_scale": "0.250,1.000,1.000,1.000,0.050,1.000",
        "observation_terms_history_length": "0.000,0.000,0.000,0.000,0.000,0.000",
    }
    meta.update(changes)
    return meta


@pytest.fixture
def folder(tmp_path):
    """The example pack without its robot.toml: a model and a policy that carries metadata."""
    target = copy_example(tmp_path / "my-biped")
    (target / "robot.toml").unlink()
    module = make_policy_module()
    (target / "policy.onnx").write_bytes(
        module.policy_bytes(np.zeros((27, 6)), np.zeros(6), _metadata())
    )
    return target


def test_the_draft_reads_the_model_and_the_policys_metadata(folder):
    text = draft_pack(folder / "stick_biped.xml", [folder / "policy.onnx"])
    spec = parse_pack(text)
    assert spec.trunk == "trunk" and spec.physics_dt == 0.005 and spec.actuator == "pd"
    assert spec.mass_kg == pytest.approx(6.4, abs=0.01)
    assert 60 <= spec.height_cm <= 80
    assert list(spec.joints) == JOINTS
    assert spec.joints["left_knee"].kp == 80.0 and spec.joints["left_hip_roll"].kd == 2.0
    assert spec.action_scale == 0.25
    assert [(t.term, t.scale) for t in spec.observation] == [
        ("base_ang_vel", 0.25),
        ("projected_gravity", 1.0),
        ("command", 1.0),
        ("joint_pos", 1.0),
        ("joint_vel", 0.05),
        ("last_action", 1.0),
    ]
    assert spec.observation_length() == 27
    assert spec.policies[0].key == "policy"


def test_the_draft_validates_with_only_the_things_a_person_must_say_left_over(folder):
    write_draft(folder, draft_pack(folder / "stick_biped.xml", [folder / "policy.onnx"]))
    report = validate_pack(folder)
    assert report.ok, report.errors
    todo = [w for w in report.warnings if "TODO" in w]
    assert todo, "the placeholders must be flagged"
    trial = [v for k, v in report.facts.items() if k.startswith("trial")]
    assert trial and "stayed upright" in trial[0]


def test_a_policy_without_metadata_still_gets_a_draft_with_the_gaps_marked(tmp_path):
    folder = copy_example(tmp_path / "bare")
    (folder / "robot.toml").unlink()
    text = draft_pack(folder / "stick_biped.xml", [folder / "policy.onnx"])
    assert "TODO: [[observation]]" in text and "actuator order" in text
    assert "kp and kd are not in the policy" in text
    with pytest.raises(PackError):  # not usable until the person fills the gaps in
        parse_pack(text)


def test_per_joint_action_scales_are_kept(folder):
    module = make_policy_module()
    scales = "0.100,0.200,0.300,0.400,0.500,0.600"
    (folder / "policy.onnx").write_bytes(
        module.policy_bytes(np.zeros((27, 6)), np.zeros(6), _metadata(action_scale=scales))
    )
    spec = parse_pack(draft_pack(folder / "stick_biped.xml", [folder / "policy.onnx"]))
    assert spec.action_scale is None
    assert [j.action_scale for j in spec.joints.values()] == [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"observation_names": "base_ang_vel,height_scan,command"}, "height_scan"),
        (
            {"observation_terms_history_length": "0,0,0,0,0,5"},
            "stacks past observations",
        ),
    ],
)
def test_terms_robot_packs_cannot_provide_are_named(folder, changes, expected):
    module = make_policy_module()
    (folder / "policy.onnx").write_bytes(
        module.policy_bytes(np.zeros((27, 6)), np.zeros(6), _metadata(**changes))
    )
    with pytest.raises(PackError, match=expected):
        draft_pack(folder / "stick_biped.xml", [folder / "policy.onnx"])


def test_a_model_with_no_free_joint_is_refused(folder):
    text = (
        (folder / "stick_biped.xml")
        .read_text(encoding="utf-8")
        .replace('<freejoint name="root"/>', "")
    )
    (folder / "stick_biped.xml").write_text(text, encoding="utf-8")
    with pytest.raises(PackError, match="free joint"):
        draft_pack(folder / "stick_biped.xml", [folder / "policy.onnx"])


def test_sensors_in_the_model_are_used_for_velocities(folder):
    xml = (folder / "stick_biped.xml").read_text(encoding="utf-8")
    xml = xml.replace(
        '<freejoint name="root"/>', '<freejoint name="root"/>\n<site name="imu" pos="0 0 0"/>'
    )
    xml = xml.replace(
        "</actuator>", '</actuator>\n<sensor><gyro name="imu_ang_vel" site="imu"/></sensor>'
    )
    (folder / "stick_biped.xml").write_text(xml, encoding="utf-8")
    spec = parse_pack(draft_pack(folder / "stick_biped.xml", [folder / "policy.onnx"]))
    assert (spec.observation[0].term, spec.observation[0].sensor) == ("sensor", "imu_ang_vel")


def test_init_writes_the_file_and_will_not_overwrite_it(folder):
    result = runner.invoke(app, ["robots", "init", str(folder)])
    assert result.exit_code == 0, result.output
    assert (folder / "robot.toml").is_file() and "TODO" in (folder / "robot.toml").read_text(
        "utf-8"
    )
    assert load_pack(folder).spec.key == "my_biped"  # from the folder name
    again = runner.invoke(app, ["robots", "init", str(folder)])
    assert again.exit_code == 1 and "already exists" in again.output
    assert runner.invoke(app, ["robots", "init", str(folder), "--force"]).exit_code == 0


def test_init_asks_when_it_cannot_choose(folder, tmp_path):
    (folder / "second.xml").write_text("<mujoco/>", encoding="utf-8")
    assert "--model" in runner.invoke(app, ["robots", "init", str(folder)]).output
    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / "m.xml").write_text("<mujoco/>", encoding="utf-8")
    assert "No policy found" in runner.invoke(app, ["robots", "init", str(empty)]).output
