"""Tests for editor undo/redo, snapshots, dirty-state, mode, and delete-impact."""

from creature_lab.editor.history import EditorHistory
from creature_lab.editor.session import EditorSession

# -- EditorHistory (in isolation) ----------------------------------------------


def test_history_undo_redo_two_stack_model():
    history = EditorHistory()
    assert not history.can_undo and not history.can_redo

    history.push({"v": 0})  # about to move to state 1
    restored = history.undo({"v": 1})
    assert restored == {"v": 0}
    assert history.can_redo

    back = history.redo({"v": 0})
    assert back == {"v": 1}


def test_history_new_push_clears_redo_branch():
    history = EditorHistory()
    history.push({"v": 0})
    history.undo({"v": 1})
    assert history.can_redo

    history.push({"v": 0})  # a fresh edit invalidates redo
    assert not history.can_redo


def test_history_respects_limit():
    history = EditorHistory(limit=3)
    for i in range(10):
        history.push({"v": i})
    # Only the last 3 are retained; undoing more than that runs out.
    count = 0
    current = {"v": 99}
    while history.undo(current) is not None:
        count += 1
    assert count == 3


# -- Session undo / redo -------------------------------------------------------


def test_session_undo_redo_restores_body_param():
    session = EditorSession(template="worm")
    original = len(session.creature.parts)

    session.set_body_param("segments", original + 2)
    changed = len(session.creature.parts)
    assert changed != original
    assert session.can_undo

    assert session.undo() is True
    assert len(session.creature.parts) == original
    assert session.can_redo

    assert session.redo() is True
    assert len(session.creature.parts) == changed


def test_session_undo_with_no_history_is_a_no_op():
    session = EditorSession()
    assert session.undo() is False
    assert "Nothing to undo" in session.last_message
    assert session.redo() is False
    assert "Nothing to redo" in session.last_message


def test_add_and_delete_limb_are_undoable():
    session = EditorSession()
    parts = len(session.creature.parts)

    session.select_part("torso")
    session.add_limb()
    assert len(session.creature.parts) == parts + 1

    session.undo()
    assert len(session.creature.parts) == parts

    session.redo()
    assert len(session.creature.parts) == parts + 1

    session.delete_selected_part()
    assert len(session.creature.parts) == parts
    session.undo()
    assert len(session.creature.parts) == parts + 1


def test_selection_does_not_create_history():
    session = EditorSession()
    assert not session.can_undo

    session.select_part("leg_0l")
    session.select_motor("hip_0l")

    assert not session.can_undo


# -- Dirty tracking ------------------------------------------------------------


def test_dirty_flag_lifecycle(tmp_path):
    session = EditorSession(template="quadruped", out_path=tmp_path / "c.json")
    assert not session.is_dirty

    session.select_part("leg_0l")
    session.update_selected_part(mass=2.0)
    assert session.is_dirty

    session.save()
    assert not session.is_dirty

    session.update_selected_part(mass=2.5)
    assert session.is_dirty


# -- Named snapshots -----------------------------------------------------------


def test_named_snapshot_save_and_restore():
    session = EditorSession()
    session.select_part("leg_0l")
    session.update_selected_part(mass=1.0)
    session.save_snapshot("baseline")
    assert "baseline" in session.snapshot_names()

    session.update_selected_part(mass=3.0)
    restored_mass = next(p for p in session.creature.parts if p.id == "leg_0l").mass
    assert restored_mass == 3.0

    assert session.restore_snapshot("baseline") is True
    part = next(p for p in session.creature.parts if p.id == "leg_0l")
    assert part.mass == 1.0
    # Restoring is itself undoable.
    session.undo()
    part = next(p for p in session.creature.parts if p.id == "leg_0l")
    assert part.mass == 3.0


def test_restore_unknown_snapshot_is_a_no_op():
    session = EditorSession()
    assert session.restore_snapshot("nope") is False


# -- Reset to template ---------------------------------------------------------


def test_reset_to_template_regenerates_defaults_and_is_undoable():
    session = EditorSession(template="quadruped")
    baseline_parts = len(session.creature.parts)

    session.select_part("torso")
    session.add_limb()
    assert len(session.creature.parts) == baseline_parts + 1

    session.reset_to_template()
    assert len(session.creature.parts) == baseline_parts

    session.undo()
    assert len(session.creature.parts) == baseline_parts + 1


def test_reset_to_template_noop_for_custom_loaded_json(tmp_path):
    out = tmp_path / "c.json"
    EditorSession(template="worm", out_path=out).save()
    session = EditorSession.from_path(out)
    assert session.template == "custom"

    session.reset_to_template()
    assert "no template" in session.last_message.lower()


# -- Delete impact -------------------------------------------------------------


def test_describe_delete_impact_root_cannot_be_deleted():
    session = EditorSession()
    session.select_part("torso")
    assert session.describe_delete_impact() == []


def test_describe_delete_impact_lists_part_and_descendants():
    session = EditorSession()
    session.select_part("leg_0l")
    assert session.describe_delete_impact() == ["leg_0l"]

    # Give leg_0l a child, then the impact must include it.
    session.add_limb()
    child = session.selected_part_id
    session.select_part("leg_0l")
    impact = session.describe_delete_impact()
    assert "leg_0l" in impact and child in impact


# -- Mode ----------------------------------------------------------------------


def test_mode_defaults_to_basic_and_switches():
    session = EditorSession()
    assert session.mode == "basic"

    session.set_mode("advanced")
    assert session.mode == "advanced"

    session.set_mode("bogus")
    assert session.mode == "advanced"  # unchanged on invalid input


# -- Controller ------------------------------------------------------------------


def test_controller_defaults_to_curated_and_switches():
    session = EditorSession()
    assert session.controller == "curated"

    session.set_controller("target_seek")
    assert session.controller == "target_seek"

    session.set_controller("not_a_real_controller")
    assert session.controller == "target_seek"  # unchanged on invalid input


def test_controller_choice_is_undoable_like_any_other_edit():
    """Choosing a controller changes what Simulate runs, so it is its own undo step."""
    session = EditorSession()
    session.select_part("leg_0l")
    session.update_selected_part(mass=2.0)  # creates real history
    original = session.controller

    session.set_controller("cpg")
    assert session.controller == "cpg"

    session.undo()  # undoes the controller choice only; the mass edit stays
    assert session.controller == original
    assert next(p for p in session.creature.parts if p.id == "leg_0l").mass == 2.0

    session.undo()  # now the mass edit
    assert next(p for p in session.creature.parts if p.id == "leg_0l").mass != 2.0


# -- controller-aware status (regression: blank "Failed: " in the editor) ------------


def test_status_blocks_target_seek_without_a_target():
    """Regression: previously Simulate would start a job that failed with a blank
    message (`typer.Exit` carries no text) instead of being disabled up front."""
    session = EditorSession(template="quadruped")
    session.set_task_preset("crawl_forward")  # no target
    session.set_controller("target_seek")

    status = session.status()

    assert status.ok is False
    assert any("target_seek" in error and "target" in error for error in status.errors)


def test_status_allows_target_seek_with_a_target_task():
    session = EditorSession(template="quadruped")
    session.set_task_preset("reach_target")
    session.set_controller("target_seek")

    status = session.status()

    assert status.ok is True
    assert not any("target_seek" in w for w in status.warnings)


def test_status_does_not_block_target_seek_for_other_controllers():
    session = EditorSession(template="quadruped")
    session.set_task_preset("crawl_forward")  # no target
    session.set_controller("cpg")  # not target_seek - no target requirement

    assert session.status().ok is True


def test_status_warns_when_target_seek_cannot_steer_a_custom_creature(tmp_path):
    """A creature with no l/r-suffixed motored joints (e.g. a worm) still runs under
    target_seek, but never turns - warn instead of silently doing nothing."""
    out = tmp_path / "worm.json"
    EditorSession(template="worm", out_path=out).save()
    session = EditorSession.from_path(out)
    session.set_task_preset("reach_target")
    session.set_controller("target_seek")

    status = session.status()

    assert status.ok is True  # not blocking - it still runs, just won't steer
    assert any("target_seek" in w and "steer" in w for w in status.warnings)
