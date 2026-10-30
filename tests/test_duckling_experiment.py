"""Contracts for the visual duckling and guided experiment."""

from creature_lab.controllers.factory import controller_fits
from creature_lab.editor.session import EditorSession
from creature_lab.scaffold.duckling import generate_duckling
from creature_lab.schema import ShapeType
from creature_lab.viewers.appearance import decorations, visual_part
from creature_lab.zoo import zoo_optimized_controller


def test_duckling_has_a_matching_gait_and_visual_only_shell():
    creature = generate_duckling()
    controller = zoo_optimized_controller(creature.name)
    assert controller is not None and controller_fits(controller, creature)
    assert {joint.id for joint in creature.joints if joint.axis == (1, 0, 0)} >= {
        "hip_roll_l",
        "hip_roll_r",
    }
    torso = next(part for part in creature.parts if part.id == "torso")
    assert torso.shape == ShapeType.BOX
    assert visual_part(creature, torso).shape == ShapeType.SPHERE
    assert {detail.name for detail in decorations(creature)} == {"beak", "eye_l", "eye_r"}
    assert next(part for part in creature.parts if part.id == "torso").shape == ShapeType.BOX


def test_guided_duck_experiment_has_undoable_baseline_and_gait():
    session = EditorSession()
    original = session.creature.model_dump(mode="json")
    session.load_guided_experiment("duckling")
    assert all(motor.amplitude == 0 and motor.offset == 0 for motor in session.creature.motors)
    baseline = session.creature.model_dump(mode="json")
    session.apply_guided_gait()
    assert any(motor.amplitude != 0 for motor in session.creature.motors)
    session.undo()
    assert session.creature.model_dump(mode="json") == baseline
    session.undo()
    assert session.creature.model_dump(mode="json") == original


def test_push_example_preserves_a_reversible_task_and_controller():
    session = EditorSession()
    before = session.creature.model_dump(mode="json")
    session.load_duckling_push_demo()
    assert session.creature.name == "duckling"
    assert session.controller == "sinusoid"
    assert session.task.impulse_event is not None
    assert session.task.impulse_event.force == (0, 10, 0)
    session.undo()
    assert session.creature.model_dump(mode="json") == before


def test_biped_preview_places_feet_on_the_floor():
    for template in ("duckling", "humanoid"):
        session = EditorSession(template=template)
        frame = session.preview_frame()
        feet = [part for part in session.creature.parts if part.id.startswith("foot_")]
        assert feet
        assert min(frame.parts[part.id].position[2] - part.size[2] / 2 for part in feet) >= -1e-8
