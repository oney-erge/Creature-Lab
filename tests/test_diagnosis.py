"""Tests for the failure-diagnosis engine (synthetic traces, no physics)."""

import math

from creature_lab.diagnosis import diagnose
from creature_lab.schema import CreatureSpec, EpisodeTrace, TaskSpec


def _creature(motor_amplitude: float = 0.3, limit=(-1.0, 1.0)) -> CreatureSpec:
    """A torso with two legs; motor amplitude/limit are tunable for over-limit tests."""
    return CreatureSpec.model_validate(
        {
            "name": "biped",
            "parts": [
                {"id": "torso", "shape": "box", "size": [0.4, 0.2, 0.1], "mass": 1.0},
                {"id": "leg_a", "shape": "capsule", "length": 0.3, "radius": 0.04, "mass": 0.2},
                {"id": "leg_b", "shape": "capsule", "length": 0.3, "radius": 0.04, "mass": 0.2},
            ],
            "joints": [
                {
                    "id": "hip_a",
                    "parent": "torso",
                    "child": "leg_a",
                    "type": "hinge",
                    "axis": [0, 1, 0],
                    "limit": list(limit),
                },
                {
                    "id": "hip_b",
                    "parent": "torso",
                    "child": "leg_b",
                    "type": "hinge",
                    "axis": [0, 1, 0],
                    "limit": list(limit),
                },
            ],
            "motors": [
                {"joint": "hip_a", "amplitude": motor_amplitude, "frequency": 1.0},
                {"joint": "hip_b", "amplitude": motor_amplitude, "frequency": 1.0},
            ],
        }
    )


def _frame(t, x, y=0.0, *, orn=(1.0, 0.0, 0.0, 0.0), contacts=None, angles=None):
    return {
        "t": t,
        "parts": {
            "torso": {"position": [x, y, 0.2], "orientation": list(orn)},
            "leg_a": {"position": [x, y + 0.1, 0.05]},
            "leg_b": {"position": [x, y - 0.1, 0.05]},
        },
        "contacts": contacts or [],
        "joint_angles": angles or {},
        "score": 0.0,
    }


def _trace(frames) -> EpisodeTrace:
    return EpisodeTrace.model_validate(
        {
            "run_id": "test",
            "creature_name": "biped",
            "task_name": "t",
            "backend": "synthetic",
            "score": 0.0,
            "frames": frames,
        }
    )


def _ground(part_id):
    return {"part_id": part_id, "position": [0.0, 0.0, 0.0]}


def test_motor_over_limit_is_detected_from_the_spec():
    creature = _creature(motor_amplitude=2.0, limit=(-0.5, 0.5))  # 2.0 > 0.5
    # A clean, contacting, forward-moving trace so only the over-limit pattern fires.
    frames = [
        _frame(t / 10, x=t / 10 * 0.3, contacts=[_ground("leg_a"), _ground("leg_b")])
        for t in range(30)
    ]
    result = diagnose(_trace(frames), creature)
    assert "motor_over_limit" in result.patterns


def test_moving_backward_is_detected():
    frames = [_frame(t / 10, x=-t / 10 * 0.5, contacts=[_ground("leg_a")]) for t in range(30)]
    result = diagnose(_trace(frames), _creature())
    assert "moving_backward" in result.patterns
    assert result.metrics["forward_displacement"] < 0


def test_no_ground_contact_is_detected():
    # Never touches the ground (no contacts anywhere).
    frames = [_frame(t / 10, x=t / 10 * 0.3) for t in range(30)]
    result = diagnose(_trace(frames), _creature())
    assert "no_ground_contact" in result.patterns


def test_early_fall_is_detected():
    # Tip the torso early: up_z = 1 - 2*(x^2+y^2) = 1 - 2*0.36 = 0.28 < 0.5.
    tipped = (0.8, 0.6, 0.0, 0.0)
    frames = [
        _frame(
            t / 10,
            x=0.01 * t,
            orn=tipped if t >= 2 else (1.0, 0.0, 0.0, 0.0),
            contacts=[_ground("leg_a"), _ground("leg_b")],
        )
        for t in range(30)
    ]
    result = diagnose(_trace(frames), _creature())
    assert "early_fall" in result.patterns
    assert 0 < result.metrics["fall_time"] < 1.0


def test_climbing_slope_uses_ground_relative_height():
    angle = 0.3
    frames = []
    for i in range(30):
        x = i * 0.05
        frame = _frame(i / 10, x=x, contacts=[_ground("leg_a"), _ground("leg_b")])
        for part in frame["parts"].values():
            part["position"][2] += x * math.tan(angle)
        frames.append(frame)
    task = TaskSpec.model_validate(
        {"name": "slope", "duration": 3, "terrain": {"type": "slope", "slope_angle": angle}}
    )
    result = diagnose(_trace(frames), _creature(), task)
    assert result.metrics["com_height_std"] < 0.05
    assert "com_instability" not in result.patterns


def test_recorded_motion_beyond_heightfield_is_reported():
    task = TaskSpec.model_validate({"name": "slope", "duration": 3, "terrain": {"type": "slope"}})
    frames = [_frame(0, 0), _frame(1, 4)]
    result = diagnose(_trace(frames), _creature(), task)
    assert result.metrics["terrain_outside_frames"] == 1
    assert "outside_terrain" in result.patterns


def test_lateral_drift_is_detected():
    # Moves sideways (y) far more than forward (x).
    frames = [
        _frame(t / 10, x=0.01 * t, y=0.05 * t, contacts=[_ground("leg_a"), _ground("leg_b")])
        for t in range(30)
    ]
    result = diagnose(_trace(frames), _creature())
    assert "lateral_drift" in result.patterns


def test_single_leg_drag_is_detected():
    # leg_a contacts every frame; leg_b almost never.
    frames = []
    for t in range(30):
        contacts = [_ground("leg_a")]
        if t < 3:
            contacts.append(_ground("leg_b"))
        frames.append(_frame(t / 10, x=0.02 * t, contacts=contacts))
    result = diagnose(_trace(frames), _creature())
    assert "single_leg_drag" in result.patterns


def test_healthy_run_reports_no_patterns():
    # Forward, upright, both legs sharing contact, modest joint motion.
    frames = []
    for t in range(30):
        angles = {"hip_a": 0.1 * (t % 3), "hip_b": 0.1 * (t % 3)}
        frames.append(
            _frame(t / 10, x=0.03 * t, contacts=[_ground("leg_a"), _ground("leg_b")], angles=angles)
        )
    result = diagnose(_trace(frames), _creature())
    assert result.patterns == []


def _task_with_target(x: float, y: float = 0.0) -> TaskSpec:
    return TaskSpec.model_validate(
        {
            "name": "reach",
            "duration": 3.0,
            "target": {"position": [x, y, 0.15], "radius": 0.15},
            "reward": {"target_distance": 1.0},
        }
    )


def test_target_not_approached_is_detected_when_stuck_near_the_start():
    task = _task_with_target(2.0)  # far ahead; the body below barely moves
    frames = [
        _frame(t / 10, x=0.001 * t, contacts=[_ground("leg_a"), _ground("leg_b")])
        for t in range(30)
    ]
    result = diagnose(_trace(frames), _creature(), task)
    assert "target_not_approached" in result.patterns
    assert result.metrics["target_progress"] < 0.05


def test_target_not_approached_absent_when_closing_in_on_the_target():
    task = _task_with_target(1.0)
    frames = [
        _frame(t / 10, x=0.03 * t, contacts=[_ground("leg_a"), _ground("leg_b")]) for t in range(30)
    ]
    result = diagnose(_trace(frames), _creature(), task)
    assert "target_not_approached" not in result.patterns
    assert result.metrics["target_progress"] > 0.05


def test_target_metrics_absent_when_task_has_no_target():
    frames = [_frame(t / 10, x=0.03 * t, contacts=[_ground("leg_a")]) for t in range(30)]
    result = diagnose(_trace(frames), _creature())  # no task at all
    assert "target_progress" not in result.metrics
    assert "target_not_approached" not in result.patterns


def test_diagnose_runs_on_a_real_episode():
    # Integration: the bundled tripod drifts backward, so diagnosis must flag it.
    import pytest

    pytest.importorskip("pybullet")
    from creature_lab.backends.pybullet_backend import PyBulletBackend
    from creature_lab.controllers.sinusoid import sinusoid_targets
    from creature_lab.zoo import zoo_creature

    creature, task = zoo_creature("tripod")
    backend = PyBulletBackend()
    try:
        backend.build(creature, task)
        frames = [
            backend.apply_motor_targets(sinusoid_targets(creature, i * task.timestep))
            or backend.step(task.timestep)
            for i in range(task.step_count())
        ]
    finally:
        backend.close()
    trace = _trace([f.model_dump() for f in frames])
    result = diagnose(trace, creature, task)
    assert "moving_backward" in result.patterns
