"""Tests for environment checks and episode summaries."""

import creature_lab.diagnostics as diagnostics
from creature_lab.diagnostics import collect_doctor_checks, summarize_episode
from creature_lab.schema import CreatureSpec, EpisodeTrace, TaskSpec


def test_doctor_checks_cover_platform_and_extras():
    checks = {check.name: check for check in collect_doctor_checks()}
    assert "platform" in checks
    assert checks["platform"].status == "info"
    for name in (
        "sim (pybullet)",
        "mujoco",
        "viz (viser)",
        "export (imageio)",
        "app (browser)",
        "llm (litellm)",
    ):
        assert name in checks
        assert checks[name].status in {"ok", "missing", "warn", "info"}
    assert "examples run" in checks


def _trace() -> EpisodeTrace:
    return EpisodeTrace.model_validate(
        {
            "run_id": "r1",
            "creature_name": "tripod",
            "task_name": "crawl_forward",
            "backend": "pybullet",
            "score": 1.5,
            "frames": [
                {
                    "t": 0.0,
                    "parts": {"a": {"position": [0.0, 0.0, 1.0]}},
                    "joint_angles": {"j": 0.0},
                    "contacts": [{"part_id": "a", "position": [0, 0, 0]}],
                    "score": 0.0,
                },
                {
                    "t": 0.5,
                    "parts": {"a": {"position": [1.0, 0.0, 1.0]}},
                    "joint_angles": {"j": 0.3},
                    "contacts": [{"part_id": "a", "position": [0, 0, 0]}],
                    "score": 1.5,
                    "events": ["damage:leg_a"],
                },
            ],
            "meta": {
                "schema_version": "1",
                "lab_version": "0.1.0",
                "score_summary": {"forward": 1.5, "fall": 0.0, "total": 1.5},
                "warnings": ["something looked off"],
            },
        }
    )


def test_summarize_episode_basic_fields():
    summary = summarize_episode(_trace())
    assert summary.frame_count == 2
    assert summary.duration == 0.5  # final frame timestamp
    assert summary.final_score == 1.5
    assert summary.forward_displacement == 1.0
    assert summary.net_displacement == 1.0
    assert summary.total_joint_motion == 0.3  # |0.3 - 0.0|
    assert summary.fell is False  # fall component is 0
    assert summary.damage_events == ["damage:leg_a"]
    assert summary.contacts_by_part == {"a": 2}
    assert summary.warnings == ["something looked off"]


def test_summarize_episode_target_progress():
    task = TaskSpec.model_validate(
        {"name": "reach", "duration": 1.0, "target": {"position": [2.0, 0.0, 1.0]}}
    )
    summary = summarize_episode(_trace(), task)
    # Centroid moves from x=0 to x=1 toward a target at x=2: 1.0 closer.
    assert summary.target_progress == 1.0


def test_summarize_episode_without_meta_has_none_fell():
    trace = _trace().model_copy(update={"meta": None})
    summary = summarize_episode(trace)
    assert summary.fell is None
    assert summary.component_scores == {}
    assert summary.warnings == []


def _creature_with_root(part_id: str = "a") -> CreatureSpec:
    return CreatureSpec.model_validate(
        {"name": "c", "parts": [{"id": part_id, "shape": "sphere", "radius": 0.1, "mass": 1.0}]}
    )


def test_summarize_episode_fell_ignores_zero_fall_penalty_when_creature_given():
    """Regression: a task without reward.fall_penalty always scores the `fall`
    component as 0, so the old score-based check always reported fell=False even
    for a creature that visibly toppled. Passing `creature` switches to
    orientation-based detection (see diagnosis.first_fall_time), which does not
    depend on the reward weights at all."""
    trace = EpisodeTrace.model_validate(
        {
            "run_id": "r3",
            "creature_name": "c",
            "task_name": "t",
            "backend": "pybullet",
            "score": 0.0,
            "frames": [
                {"t": 0.0, "parts": {"a": {"position": [0, 0, 0.2]}}, "score": 0.0},
                {
                    "t": 0.5,
                    # Tipped: up_z = 1 - 2*(0.8^2) = 1 - 1.28 = -0.28 < 0.5 -> fallen.
                    "parts": {"a": {"position": [0, 0, 0.05], "orientation": [0.6, 0.8, 0, 0]}},
                    "score": 0.0,
                },
            ],
            # No fall_penalty, so the score component is 0 - this is exactly what
            # crawl_forward-style tasks look like.
            "meta": {
                "schema_version": "1",
                "lab_version": "0.1.0",
                "score_summary": {"forward": 0.0, "fall": 0.0, "total": 0.0},
            },
        }
    )

    without_creature = summarize_episode(trace)
    assert without_creature.fell is False  # the pre-fix (weak) signal

    with_creature = summarize_episode(trace, creature=_creature_with_root("a"))
    assert with_creature.fell is True  # the real answer


def test_summarize_episode_fell_false_when_creature_stays_upright():
    summary = summarize_episode(_trace(), creature=_creature_with_root("a"))
    assert summary.fell is False


def test_summarize_episode_fell_detects_a_real_toppling_creature_on_crawl_forward():
    """End-to-end version of the synthetic regression above: a tall, top-heavy
    creature that topples under its own gait, on a real crawl_forward-style task
    (no reward.fall_penalty) - the exact scenario `qualify`'s Robustness check and
    the editor's robustness verdict depend on getting right."""
    import pytest

    pytest.importorskip("pybullet")
    from creature_lab.cli import _simulate

    creature = CreatureSpec.model_validate(
        {
            "name": "faller",
            "parts": [
                {"id": "torso", "shape": "box", "size": [0.1, 0.1, 0.6], "mass": 2.0},
                {"id": "leg", "shape": "capsule", "length": 0.2, "radius": 0.03, "mass": 0.1},
            ],
            "joints": [
                {
                    "id": "hip",
                    "parent": "torso",
                    "child": "leg",
                    "type": "hinge",
                    "anchor": [0, 0, -0.3],
                    "axis": [0, 1, 0],
                    "limit": [-1.5, 1.5],
                }
            ],
            "motors": [{"joint": "hip", "amplitude": 1.5, "frequency": 3.0}],
        }
    )
    task = TaskSpec.model_validate(
        {
            "name": "crawl_forward",
            "duration": 2.0,
            "terrain": {"friction": 1.0},
            "reward": {"forward_distance": 1.0},  # no fall_penalty
        }
    )
    trace = _simulate(creature, task)

    assert summarize_episode(trace, task).fell is False  # the pre-fix (weak) signal
    assert summarize_episode(trace, task, creature).fell is True  # the real answer


def test_duration_is_final_frame_timestamp_not_span():
    # Frames at t=0.1 and t=0.3: duration is the final timestamp (0.3), not the span (0.2).
    trace = EpisodeTrace.model_validate(
        {
            "run_id": "r2",
            "creature_name": "c",
            "task_name": "t",
            "backend": "pybullet",
            "score": 0.0,
            "frames": [
                {"t": 0.1, "parts": {"a": {"position": [0, 0, 0]}}, "score": 0.0},
                {"t": 0.3, "parts": {"a": {"position": [0, 0, 0]}}, "score": 0.0},
            ],
        }
    )
    assert summarize_episode(trace).duration == 0.3


def test_doctor_viz_check_reports_trimesh_and_numpy():
    viz = {check.name: check for check in collect_doctor_checks()}["viz (viser)"]
    assert viz.status in {"ok", "warn", "missing"}
    if viz.status == "ok":
        assert "trimesh" in viz.detail and "numpy" in viz.detail


def test_doctor_never_crashes_when_a_check_raises(monkeypatch):
    def boom() -> diagnostics.DoctorCheck:
        raise RuntimeError("simulated broken environment")

    monkeypatch.setattr(diagnostics, "_examples_check", boom)
    checks = {check.name: check for check in collect_doctor_checks()}  # must not raise
    assert checks["examples run"].status == "warn"
    assert "simulated broken environment" in checks["examples run"].detail
    # Other checks are unaffected.
    assert checks["platform"].status == "info"


def test_doctor_names_the_app_extras_when_they_are_missing(monkeypatch):
    monkeypatch.setattr(diagnostics, "_installed", lambda module: module != "fastapi")
    check = {c.name: c for c in collect_doctor_checks()}["app (browser)"]
    assert check.status == "info"
    assert "fastapi" in check.detail and "--extra web --extra robots" in check.detail
