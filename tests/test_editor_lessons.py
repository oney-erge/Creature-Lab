from pathlib import Path

from creature_lab.controllers.factory import curated_controller
from creature_lab.editor.session import EditorSession
from creature_lab.hashing import spec_hash
from creature_lab.schema import ControllerSpec


def test_frozen_lesson_uses_editable_offline_controller_and_can_be_undone():
    session = EditorSession()
    previous = spec_hash(session.creature)
    session.load_failure_lesson("frozen-gait")
    assert session.controller == "sinusoid"
    assert session.creature.motors
    assert all(motor.amplitude == 0 for motor in session.creature.motors)
    session.undo()
    assert spec_hash(session.creature) == previous
    assert session.controller == "curated"


def test_editable_packaged_gait_is_used_and_undo_restores_controller():
    session = EditorSession()
    original = spec_hash(session.creature)
    packaged = ControllerSpec.model_validate_json(
        Path(curated_controller(session.creature)).read_text(encoding="utf-8")
    )
    session.use_editable_gait()
    assert session.controller == "sinusoid"
    by_joint = {motor.joint: motor for motor in session.creature.motors}
    for motor in packaged.motors or []:
        assert by_joint[motor.joint].amplitude == motor.amplitude
        assert by_joint[motor.joint].phase == motor.phase
    session.apply_gait("still")
    assert all(motor.amplitude == 0 for motor in session.creature.motors)
    session.undo()
    session.undo()
    assert session.controller == "curated"
    assert spec_hash(session.creature) == original


def test_refit_selects_its_sinusoid_and_undo_restores_curated():
    session = EditorSession()
    tuned = session.creature.model_copy(deep=True)
    session.apply_refit_gait(tuned)
    assert session.controller == "sinusoid"
    session.undo()
    assert session.controller == "curated"


def test_body_resize_preserves_an_edited_gait():
    session = EditorSession()
    session.use_editable_gait()
    session.update_selected_motor(amplitude=0.2)
    joint = session.selected_motor()
    session.set_body_param("leg_length", 0.3)
    motor = next(motor for motor in session.creature.motors if motor.joint == joint)
    assert session.controller == "sinusoid"
    assert motor.amplitude == 0.2


def test_recorded_push_can_be_changed_and_undone():
    session = EditorSession()
    original = spec_hash(session.task)
    session.set_lateral_push(100)
    assert session.task.impulse_event is not None
    assert session.task.impulse_event.force == (0.0, 100.0, 0.0)
    assert session.task.impulse_event.time == session.task.duration / 2
    session.undo()
    assert spec_hash(session.task) == original
