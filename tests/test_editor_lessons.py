from creature_lab.editor.session import EditorSession
from creature_lab.hashing import spec_hash


def test_frozen_lesson_uses_editable_offline_controller_and_can_be_undone():
    session = EditorSession()
    previous = spec_hash(session.creature)
    session.load_failure_lesson("frozen-gait")
    assert session.controller == "sinusoid"
    assert session.creature.motors
    assert all(motor.amplitude == 0 for motor in session.creature.motors)
    session.undo()
    assert spec_hash(session.creature) == previous


def test_recorded_push_can_be_changed_and_undone():
    session = EditorSession()
    original = spec_hash(session.task)
    session.set_lateral_push(100)
    assert session.task.impulse_event is not None
    assert session.task.impulse_event.force == (0.0, 100.0, 0.0)
    assert session.task.impulse_event.time == session.task.duration / 2
    session.undo()
    assert spec_hash(session.task) == original
