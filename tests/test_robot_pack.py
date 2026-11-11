"""Robot packs, the file format and the list of added robots. None of this needs a simulator."""

from __future__ import annotations

import shutil

import pytest
from pack_helpers import EXAMPLE, copy_example, edit

from creature_lab.robots.catalog import ROBOTS, all_robots, robot_info
from creature_lab.robots.pack import (
    PackError,
    default_levels,
    load_pack,
    pack_info,
    parse_pack,
    register_pack,
    registry_status,
    unregister_pack,
)


@pytest.fixture
def cache(tmp_path, monkeypatch):
    """An empty robot cache, so a test never touches the real list of added robots."""
    monkeypatch.setenv("CREATURE_LAB_ROBOTS_DIR", str(tmp_path / "cache"))
    return tmp_path / "cache"


@pytest.fixture
def pack_copy(tmp_path):
    return copy_example(tmp_path / "pack")


def _example_text() -> str:
    return (EXAMPLE / "robot.toml").read_text(encoding="utf-8")


def test_the_example_pack_parses():
    pack = load_pack(EXAMPLE)
    assert pack.spec.key == "stick_biped"
    assert list(pack.spec.joints)[:2] == ["left_hip_roll", "left_hip_pitch"]  # file order kept
    assert pack.spec.observation_length() == 27
    assert pack.spec.substeps == 4


def test_a_pack_becomes_a_catalog_entry_with_scaled_defaults():
    info = pack_info(load_pack(EXAMPLE))
    assert info.folder == EXAMPLE.resolve()
    assert info.manifest is None and info.first_run_s == 0
    assert info.policies[0].key == "stand" and info.default_policy == "stand"
    shoves = info.levels.shoves_n
    assert list(shoves) == sorted(shoves) and len(shoves) == 5
    assert 8 < shoves[0] < 12 and 50 < shoves[-1] < 62  # 6.4 kg: about 9 N to 57 N
    assert info.levels.batteries_v == ()
    assert info.staging.unit == pytest.approx(70 / 25)


def test_default_levels_scale_with_mass():
    shoves, loads = default_levels(35)  # the G1's mass: close to its hand-picked 50-300 N, 3-10 kg
    assert shoves == (52.0, 100.0, 150.0, 210.0, 310.0)
    assert loads == (3.5, 7.0, 10.0)


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        ('key = "stick_biped"', 'key = "unitree_g1"', "built-in robot"),
        ('key = "stick_biped"', 'key = "Stick Biped"', "lowercase"),
        ("physics_dt = 0.005", "physics_dt = 0.007", "does not divide"),
        ("kp = 60.0, kd = 2.0 }\nleft_hip_pitch", "kd = 2.0 }\nleft_hip_pitch", "kp and kd"),
        (
            'term = "base_ang_vel"\nscale = 0.25',
            'term = "base_ang_vel"\nscale = [1, 2]',
            "scale has 2",
        ),
        ('term = "joint_pos"', 'term = "gait_phase"', "needs period_s"),
        ("height_cm = 70", "height_cm = 70\nhieght = 1", "Extra inputs"),
        ("action_scale = 0.25", "action_scale = 0", "action_scale"),
    ],
)
def test_mistakes_in_robot_toml_are_named(old, new, expected):
    with pytest.raises(PackError, match=expected):
        parse_pack(_example_text().replace(old, new, 1))


def test_every_problem_is_listed_at_once():
    text = _example_text().replace('key = "stick_biped"', 'key = "X"')
    text = text.replace("action_scale = 0.25", "action_scale = -1")
    with pytest.raises(PackError) as caught:
        parse_pack(text)
    assert len(caught.value.problems) == 2


def test_invalid_toml_says_so():
    with pytest.raises(PackError, match="not valid TOML"):
        parse_pack("key = ")


def test_added_robots_join_the_catalog(cache):
    assert "stick_biped" not in all_robots()
    info = register_pack(EXAMPLE)
    assert info.key == "stick_biped"
    assert robot_info("stick_biped").folder == EXAMPLE.resolve()
    assert list(all_robots())[: len(ROBOTS)] == list(ROBOTS)  # built-ins first
    assert (cache / "packs.json").is_file()
    unregister_pack("stick_biped")
    assert "stick_biped" not in all_robots()
    assert EXAMPLE.is_dir()  # removing never deletes files


def test_the_same_key_from_another_folder_is_refused(cache, pack_copy):
    register_pack(EXAMPLE)
    with pytest.raises(PackError, match="already added"):
        register_pack(pack_copy)


def test_a_missing_model_or_policy_is_refused(cache, pack_copy):
    (pack_copy / "policy.onnx").unlink()
    with pytest.raises(PackError, match="policy stand"):
        register_pack(pack_copy)


def test_a_moved_folder_is_reported_not_fatal(cache, pack_copy):
    register_pack(pack_copy)
    shutil.rmtree(pack_copy)
    assert "stick_biped" not in all_robots()
    folder, info, problem = registry_status()["stick_biped"]
    assert info is None and folder == pack_copy.resolve() and "robot.toml" in problem


def test_edits_to_robot_toml_are_picked_up(cache, pack_copy):
    register_pack(pack_copy)
    assert robot_info("stick_biped").title == "Stick biped"
    edit(pack_copy, "robot.toml", 'title = "Stick biped"', 'title = "Stick biped v2"')
    assert robot_info("stick_biped").title == "Stick biped v2"
