"""Tests for the build editor's pure session logic."""

import json
import os

import pytest
from pydantic import ValidationError

from creature_lab.editor import presets
from creature_lab.editor.session import EditorSession
from creature_lab.schema import CreatureSpec


def test_editor_session_default_is_valid():
    session = EditorSession()

    assert session.creature.name == "quadruped"
    assert session.status().ok
    assert session.preview_frame().parts


def test_editor_preset_body_params_regenerate_valid_humanoid():
    session = EditorSession(template="humanoid")

    session.set_body_param("dof", 12)
    session.set_body_param("upper_leg_ratio", 0.30)
    session.set_body_param("limb_radius_ratio", 0.04)

    assert session.status().ok
    assert len(session.creature.motors) == 12
    assert any(part.id == "foot_l" for part in session.creature.parts)


def test_editor_part_and_motor_edits_validate():
    session = EditorSession()
    session.select_part("leg_0l")
    session.update_selected_part(length=0.31, radius=0.04, color=(255, 64, 32))
    session.select_motor("hip_0l")
    session.update_selected_motor(amplitude=0.5, frequency=1.25, phase=0.2)

    part = next(part for part in session.creature.parts if part.id == "leg_0l")
    motor = next(motor for motor in session.creature.motors if motor.joint == "hip_0l")

    assert part.length == 0.31
    assert part.radius == 0.04
    assert part.color == (1.0, 64 / 255, 32 / 255)
    assert motor.amplitude == 0.5
    assert motor.frequency == 1.25
    assert motor.phase == 0.2
    assert session.status().ok


def test_editor_moves_selected_joint_anchor_from_preview_position():
    session = EditorSession()
    session.select_part("leg_0l")

    session.move_selected_anchor_to((0.2, 0.2, 0.1))

    joint = next(joint for joint in session.creature.joints if joint.child == "leg_0l")
    assert joint.anchor == pytest.approx((0.2, 0.2, 0.06))
    assert session.status().ok


def test_editor_add_delete_limb_round_trips():
    session = EditorSession()
    original_parts = len(session.creature.parts)

    session.select_part("torso")
    session.add_limb()
    assert len(session.creature.parts) == original_parts + 1
    assert session.selected_part_id.startswith("limb_")
    assert session.status().ok

    session.delete_selected_part()
    assert len(session.creature.parts) == original_parts
    assert session.status().ok


def test_editor_save_and_load(tmp_path):
    out = tmp_path / "built.json"
    session = EditorSession(template="worm", out_path=out)
    session.set_body_param("segments", 7)
    saved = session.save()

    loaded = EditorSession.from_path(saved)

    assert saved == out
    assert loaded.creature.name == "worm"
    assert len(loaded.creature.parts) == 7
    assert CreatureSpec.model_validate(json.loads(saved.read_text())) == loaded.creature


def test_task_presets_are_valid():
    for name in presets.task_names():
        task = presets.generate_task(name)
        assert task.name == name
        assert task.step_count() > 0


def test_bind_project_creates_files_when_none_exist(tmp_path):
    project_dir = tmp_path / "mydude"
    session = EditorSession(template="worm")

    session.bind_project(project_dir)

    assert (project_dir / "creature.json").exists()
    assert (project_dir / "task.json").exists()
    assert session.creature.name == "worm"
    assert not session.external_change_pending


def test_bind_project_loads_existing_files(tmp_path):
    project_dir = tmp_path / "mydude"
    project_dir.mkdir()
    seed_session = EditorSession(template="hexapod")
    (project_dir / "creature.json").write_text(
        seed_session.creature.model_dump_json(indent=2, exclude_none=True)
    )
    (project_dir / "task.json").write_text(
        seed_session.task.model_dump_json(indent=2, exclude_none=True)
    )

    session = EditorSession(template="worm")
    session.bind_project(project_dir)

    assert session.creature.name == "hexapod"
    assert session.template == "custom"


def test_project_reopens_selected_controller_backend_and_seed(tmp_path):
    project = tmp_path / "experiment"
    session = EditorSession()
    session.backend = "mujoco"
    session.seed = 17
    session.bind_project(project)
    session.set_controller("sinusoid")
    session.autosave()

    reopened = EditorSession(project_dir=project)
    assert (reopened.controller, reopened.backend, reopened.seed) == ("sinusoid", "mujoco", 17)
    assert reopened.creature == session.creature
    assert reopened.task == session.task


def test_project_state_external_edit_is_detected_and_requires_restart_for_backend(tmp_path):
    project = tmp_path / "experiment"
    session = EditorSession(project_dir=project)
    state_path = project / "editor-state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["backend"] = "mujoco"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    assert session.poll_external_changes()
    with pytest.raises(ValueError, match="Restart the editor"):
        session.reload_project()
    assert session.backend == "pybullet"
    assert session.external_change_pending


def test_controller_change_is_undoable_and_autosaved(tmp_path):
    session = EditorSession(project_dir=tmp_path / "experiment")
    session.set_controller("cpg")
    session.autosave()
    assert EditorSession(project_dir=session.project_dir).controller == "cpg"
    assert session.undo()
    session.autosave()
    assert EditorSession(project_dir=session.project_dir).controller == "curated"


def test_autosave_writes_edits_back_to_project_files(tmp_path):
    project_dir = tmp_path / "mydude"
    session = EditorSession(template="quadruped")
    session.bind_project(project_dir)

    session.select_part("leg_0l")
    session.update_selected_part(mass=2.5)
    session.autosave()

    on_disk = CreatureSpec.model_validate(json.loads((project_dir / "creature.json").read_text()))
    part = next(part for part in on_disk.parts if part.id == "leg_0l")
    assert part.mass == 2.5


def test_autosave_is_a_no_op_without_a_bound_project(tmp_path):
    session = EditorSession(template="quadruped")

    session.autosave()  # must not raise or write anywhere

    assert session.project_dir is None


def test_save_and_load_round_trip_through_urdf(tmp_path):
    urdf_path = tmp_path / "built.urdf"
    session = EditorSession(template="quadruped")

    saved = session.save(urdf_path)
    assert saved == urdf_path
    assert "<robot" in urdf_path.read_text()

    loaded = EditorSession.from_path(urdf_path)
    assert loaded.creature.parts  # imported something
    assert loaded.template == "custom"


def test_load_path_reports_urdf_import_warnings(tmp_path):
    # "sensor_mount" has only mesh geometry (no box/sphere/cylinder) and is
    # unsupported/dropped by import_urdf; "torso" is a valid box so the import as a
    # whole succeeds, and the mesh warning should surface in last_message instead
    # of silently losing detail.
    mixed_urdf = """<?xml version="1.0"?>
    <robot name="mixed_bot">
      <link name="torso">
        <visual><geometry><box size="0.4 0.2 0.1"/></geometry></visual>
        <inertial><mass value="1.0"/></inertial>
      </link>
      <link name="sensor_mount">
        <visual><geometry><mesh filename="unused.stl"/></geometry></visual>
      </link>
    </robot>
    """
    path = tmp_path / "mixed.urdf"
    path.write_text(mixed_urdf)

    session = EditorSession()
    session.load_path(path)

    assert session.creature.name == "mixed_bot"
    assert [part.id for part in session.creature.parts] == ["torso"]
    assert "skipped" in session.last_message.lower()
    assert "sensor_mount" in session.last_message


def test_save_to_mjcf_does_not_raise(tmp_path):
    xml_path = tmp_path / "built.xml"
    session = EditorSession(template="worm")

    saved = session.save(xml_path)

    assert saved == xml_path
    assert "<mujoco" in xml_path.read_text()


def test_poll_external_changes_detects_edit_and_reload_clears_it(tmp_path):
    project_dir = tmp_path / "mydude"
    session = EditorSession(template="quadruped")
    session.bind_project(project_dir)

    assert session.poll_external_changes() is False

    other = EditorSession(template="hexapod")
    creature_path = project_dir / "creature.json"
    # Ensure the mtime actually advances on filesystems with coarse resolution.
    os.utime(creature_path, (creature_path.stat().st_mtime + 5, creature_path.stat().st_mtime + 5))
    creature_path.write_text(other.creature.model_dump_json(indent=2, exclude_none=True))

    assert session.poll_external_changes() is True
    assert session.external_change_pending is True
    # Edge-triggered: stays quiet until reload, even though the file is still changed.
    assert session.poll_external_changes() is False

    session.reload_project()

    assert session.creature.name == "hexapod"
    assert session.external_change_pending is False


def test_project_autosave_clears_dirty_state(tmp_path):
    session = EditorSession(template="quadruped")
    session.bind_project(tmp_path / "project")
    session.select_part("leg_0l")
    session.update_selected_part(mass=2.0)
    assert session.is_dirty is True

    session.autosave()

    assert session.is_dirty is False


def test_external_deletion_is_detected_and_autosave_will_not_overwrite_it(tmp_path):
    project = tmp_path / "project"
    session = EditorSession(template="quadruped")
    session.bind_project(project)
    (project / "task.json").unlink()

    assert session.poll_external_changes() is True
    session.select_part("leg_0l")
    session.update_selected_part(mass=2.0)
    with pytest.raises(RuntimeError, match="changed on disk"):
        session.autosave()
    assert not (project / "task.json").exists()


def test_reload_is_transactional_when_one_artifact_is_invalid(tmp_path):
    project = tmp_path / "project"
    session = EditorSession(template="quadruped")
    session.bind_project(project)
    original = session.creature
    replacement = EditorSession(template="hexapod").creature
    (project / "creature.json").write_text(replacement.model_dump_json())
    (project / "task.json").write_text("{}")

    with pytest.raises(ValidationError):
        session.reload_project()

    assert session.creature == original


def test_preview_composes_nested_parent_rotations():
    half = 2**-0.5
    creature = CreatureSpec.model_validate(
        {
            "name": "rotated",
            "parts": [
                {"id": name, "shape": "box", "size": [0.1, 0.1, 0.1], "mass": 1.0}
                for name in ("root", "middle", "tip")
            ],
            "joints": [
                {
                    "id": "a",
                    "parent": "root",
                    "child": "middle",
                    "type": "fixed",
                    "anchor": [1, 0, 0],
                    "rest_orientation": [half, 0, 0, half],
                },
                {
                    "id": "b",
                    "parent": "middle",
                    "child": "tip",
                    "type": "fixed",
                    "anchor": [1, 0, 0],
                },
            ],
        }
    )

    frame = EditorSession(creature=creature).preview_frame()

    assert frame.parts["middle"].position == pytest.approx((1, 0, 0.05))
    assert frame.parts["tip"].position == pytest.approx((1, 1, 0.05))
