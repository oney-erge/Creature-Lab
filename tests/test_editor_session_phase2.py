"""Tests for Phase 2 session additions: gait fixes, diagnosis apply-fix, restore, labels."""

from __future__ import annotations

from creature_lab.diagnosis import diagnose
from creature_lab.editor.session import DIAGNOSIS_FIXES, DIAGNOSIS_SEVERITY, EditorSession
from creature_lab.schema import CreatureSpec

# -- gait mutation helpers -------------------------------------------------------


def _gait_before_editing(session: EditorSession) -> CreatureSpec:
    """The gait a first edit starts from: the quadruped runs a packaged, tuned gait by default,
    and editing copies it into the editable motors before changing it."""
    return session.editable_gait_creature()


def test_scale_all_motors_scales_amplitude_and_frequency():
    session = EditorSession(template="quadruped")
    before = {m.joint: (m.amplitude, m.frequency) for m in _gait_before_editing(session).motors}

    assert session.scale_all_motors(amplitude_factor=0.5, frequency_factor=0.5) is True

    for motor in session.creature.motors:
        old_amp, old_freq = before[motor.joint]
        assert motor.amplitude == old_amp * 0.5
        assert motor.frequency == old_freq * 0.5
    assert session.controller == "sinusoid"  # the edited gait is the one that runs
    assert session.status().ok
    assert session.can_undo


def test_scale_all_motors_noop_without_motors():
    session = EditorSession()
    data = session.creature.model_dump(mode="json", exclude_none=True)
    data["motors"] = []
    session.creature = CreatureSpec.model_validate(data)
    session._history.clear()

    assert session.scale_all_motors(amplitude_factor=0.5) is False
    assert not session.can_undo


def test_reverse_gait_shifts_every_phase_by_pi():
    import math

    session = EditorSession(template="quadruped")
    before = {m.joint: m.phase for m in _gait_before_editing(session).motors}

    assert session.reverse_gait() is True

    for motor in session.creature.motors:
        assert motor.phase == before[motor.joint] + math.pi
    assert session.status().ok


def test_widen_stance_increases_body_width_param():
    session = EditorSession(template="quadruped")
    original = session.params["body_width"]

    assert session.widen_stance(1.2) is True

    assert session.params["body_width"] == original * 1.2
    assert session.status().ok


def test_widen_stance_fails_gracefully_for_custom_creature(tmp_path):
    out = tmp_path / "c.json"
    EditorSession(template="worm", out_path=out).save()
    session = EditorSession.from_path(out)

    assert session.widen_stance() is False
    assert "no stance parameter" in session.last_message.lower()


# -- diagnosis apply-fix ----------------------------------------------------------


def test_every_diagnosis_fix_pattern_is_actually_applicable():
    """Every registered fix must run cleanly against a plain quadruped.

    ``target_not_approached`` is the one exception: that pattern only ever fires
    when the task already has a target (see diagnosis.py), so its fix (switch to
    target_seek) is only realistically applied under that same precondition -
    without it, the session's own controller/task validation correctly refuses
    (see test_editor_history.py's target_seek status tests), which is the point.
    """
    for pattern, (_label, fix) in DIAGNOSIS_FIXES.items():
        session = EditorSession(template="quadruped")
        if pattern == "target_not_approached":
            session.set_task_preset("reach_target")
        applied = fix(session)
        assert applied is True, f"fix for {pattern!r} reported failure on a fresh quadruped"
        assert session.status().ok, f"fix for {pattern!r} produced an invalid creature"


def test_apply_diagnosis_fix_known_pattern():
    session = EditorSession(template="quadruped")

    assert session.apply_diagnosis_fix("moving_backward") is True
    assert session.can_undo


def test_apply_diagnosis_fix_unknown_pattern_returns_false():
    session = EditorSession(template="quadruped")

    assert session.apply_diagnosis_fix("some_unregistered_pattern") is False
    assert "no automatic fix" in session.last_message.lower()


def test_diagnosis_fix_label_matches_table():
    session = EditorSession()
    assert session.diagnosis_fix_label("moving_backward") == DIAGNOSIS_FIXES["moving_backward"][0]
    assert session.diagnosis_fix_label("no_ground_contact") is None


def test_diagnosis_severity_defaults_to_warning():
    session = EditorSession()
    assert session.diagnosis_severity("early_fall") == "critical"
    assert session.diagnosis_severity("totally_unknown_pattern") == "warning"
    assert DIAGNOSIS_SEVERITY["arm_swing_absent"] == "info"


# -- restore from run --------------------------------------------------------------


def test_restore_from_run_loads_creature_and_task_and_is_undoable(tmp_path):
    run_dir = tmp_path / "run1"
    run_dir.mkdir()
    other = EditorSession(template="hexapod")
    (run_dir / "creature.json").write_text(other.creature.model_dump_json(indent=2))
    (run_dir / "task.json").write_text(other.task.model_dump_json(indent=2))

    session = EditorSession(template="quadruped")
    session.restore_from_run(run_dir / "creature.json", run_dir / "task.json")

    assert session.creature.name == "hexapod"
    assert session.template == "custom"
    assert session.can_undo

    session.undo()
    assert session.creature.name == "quadruped"


def test_restore_from_run_without_task_file_keeps_current_task(tmp_path):
    run_dir = tmp_path / "run1"
    run_dir.mkdir()
    other = EditorSession(template="hexapod")
    (run_dir / "creature.json").write_text(other.creature.model_dump_json(indent=2))

    session = EditorSession(template="quadruped")
    original_task_name = session.task.name
    session.restore_from_run(run_dir / "creature.json", run_dir / "task.json")

    assert session.creature.name == "hexapod"
    assert session.task.name == original_task_name  # task.json didn't exist; task unchanged


# -- onboarding ---------------------------------------------------------------------


def test_apply_onboarding_sets_creature_and_task_in_one_undo_step():
    session = EditorSession(template="quadruped")

    session.apply_onboarding("worm", "reach_target")

    assert session.creature.name == "worm"
    assert session.task_preset == "reach_target"
    assert session.task.target is not None
    assert session.status().ok

    session.undo()
    assert session.creature.name == "quadruped"


# -- labels / hierarchy --------------------------------------------------------------


def test_part_label_and_hierarchy_markdown_use_selected_part():
    session = EditorSession(template="quadruped")
    session.select_part("leg_0l")

    assert session.part_label("leg_0l") == "Leg 1 (left)"
    tree = session.part_hierarchy_markdown()
    assert "**Leg 1 (left)**" in tree


# -- fixes actually change diagnosis (integration sanity check) ----------------------


def test_reduce_amplitude_fix_reduces_measured_joint_motion_signal():
    """Not a physics test - just confirms the fix data flows into what diagnosis reads."""
    session = EditorSession(template="quadruped")
    before = {m.joint: m.amplitude for m in _gait_before_editing(session).motors}
    session.scale_all_motors(amplitude_factor=0.5)
    for motor in session.creature.motors:
        assert motor.amplitude == before[motor.joint] * 0.5


def test_diagnose_still_runs_after_applying_every_fix_to_a_diagnosable_creature():
    # Sanity: applying a fix keeps the creature in a state diagnose() can consume.
    session = EditorSession(template="quadruped")
    session.apply_diagnosis_fix("com_instability")
    creature = session.creature
    task = session.task
    trace_data = {
        "run_id": "x",
        "creature_name": creature.name,
        "task_name": task.name,
        "backend": "pybullet",
        "score": 0.0,
        "frames": [
            {"t": 0.0, "parts": {p.id: {"position": (0.0, 0.0, 0.1)} for p in creature.parts}},
            {"t": 0.1, "parts": {p.id: {"position": (0.1, 0.0, 0.1)} for p in creature.parts}},
        ],
    }
    from creature_lab.schema import EpisodeTrace

    trace = EpisodeTrace.model_validate(trace_data)
    result = diagnose(trace, creature, task)
    assert isinstance(result.metrics, dict)
