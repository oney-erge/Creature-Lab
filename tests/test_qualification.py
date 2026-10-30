"""Tests for qualification profiles and the pass/fail/primary-blocker logic.

Uses synthetic injected ``simulate`` functions (no physics) so the *logic* -
baseline success, robustness aggregation, sim2sim gap, primary-blocker selection -
is tested deterministically and fast. Real-physics coverage lives in test_cli.py's
`qualify` command tests.
"""

from __future__ import annotations

from creature_lab.qualification import (
    BUILTIN_PROFILES,
    QualificationProfile,
    qualify,
)
from creature_lab.schema import CreatureSpec, EpisodeTrace, TaskSpec

_CREATURE = CreatureSpec.model_validate(
    {
        "name": "test_bot",
        "parts": [{"id": "torso", "shape": "box", "size": [0.4, 0.2, 0.1], "mass": 1.0}],
    }
)


def _task(*, target: tuple[float, float] | None = None) -> TaskSpec:
    data: dict = {"name": "t", "duration": 1.0}
    if target is not None:
        data["target"] = {"position": [target[0], target[1], 0.15], "radius": 0.15}
    return TaskSpec.model_validate(data)


# up_z = 1 - 2*(x^2+y^2) = 1 - 2*0.36 = 0.28 < 0.5 -> toppled (see diagnosis.is_upright).
_TIPPED_ORIENTATION = (0.8, 0.6, 0.0, 0.0)
_UPRIGHT_ORIENTATION = (1.0, 0.0, 0.0, 0.0)


def _trace(score: float, *, fell: bool = False, backend: str = "fake") -> EpisodeTrace:
    orientation = _TIPPED_ORIENTATION if fell else _UPRIGHT_ORIENTATION
    return EpisodeTrace.model_validate(
        {
            "run_id": "t",
            "creature_name": "test_bot",
            "task_name": "t",
            "backend": backend,
            "score": score,
            "frames": [
                {"t": 0.0, "parts": {"torso": {"position": (0.0, 0.0, 0.1)}}, "score": 0.0},
                {
                    "t": 0.1,
                    "parts": {"torso": {"position": (0.3, 0.0, 0.1), "orientation": orientation}},
                    "score": score,
                },
            ],
            "meta": {
                "schema_version": "1",
                "lab_version": "test",
                # Kept in sync with `orientation` so the fixture is correct via either
                # fall-detection path (orientation-based, when creature is given; the
                # score-component fallback otherwise).
                "score_summary": {"fall": -1.0 if fell else 0.0},
            },
        }
    )


def _fixed_simulate(score: float, *, fell: bool = False):
    def simulate(creature: CreatureSpec, task: TaskSpec) -> EpisodeTrace:
        return _trace(score, fell=fell)

    return simulate


def test_all_checks_pass():
    profile = QualificationProfile(
        name="p", description="", min_score=0.05, robustness_trials=3, max_fail_rate=0.5
    )
    result = qualify(_CREATURE, _task(), profile, simulate=_fixed_simulate(0.5))

    assert result.passed is True
    assert result.primary_blocker is None
    assert result.recommended_next_test is None
    assert [c.name for c in result.checks] == ["Baseline task success", "Robustness"]
    assert all(c.passed for c in result.checks)


def test_baseline_failure_is_the_primary_blocker():
    profile = QualificationProfile(
        name="p", description="", min_score=0.5, robustness_trials=3, max_fail_rate=0.5
    )
    result = qualify(_CREATURE, _task(), profile, simulate=_fixed_simulate(0.1))

    assert result.passed is False
    assert result.primary_blocker == "Baseline task success"
    recommendation = result.recommended_next_test
    assert "target_seek" in recommendation or "diagnose" in recommendation
    # Robustness still ran and is reported even though baseline already failed.
    assert any(c.name == "Robustness" for c in result.checks)


def test_baseline_fails_on_fall_even_with_good_score():
    profile = QualificationProfile(name="p", description="", min_score=0.0, robustness_trials=2)
    result = qualify(_CREATURE, _task(), profile, simulate=_fixed_simulate(1.0, fell=True))

    baseline = result.checks[0]
    assert baseline.passed is False
    assert "fell=True" in baseline.detail


def test_robustness_failure_is_the_primary_blocker_when_baseline_passes():
    calls = {"n": 0}

    def flaky_simulate(creature: CreatureSpec, task: TaskSpec) -> EpisodeTrace:
        calls["n"] += 1
        # First call (the baseline) succeeds; every trial after that falls.
        return _trace(0.5, fell=calls["n"] > 1)

    profile = QualificationProfile(
        name="p", description="", min_score=0.05, robustness_trials=5, max_fail_rate=0.2
    )
    result = qualify(_CREATURE, _task(), profile, simulate=flaky_simulate)

    assert result.checks[0].passed is True  # baseline (call 1) was fine
    assert result.primary_blocker == "Robustness"
    assert "Widen the stance" in result.recommended_next_test


def test_target_reach_profile_uses_target_progress_not_score():
    profile = BUILTIN_PROFILES["target-reach"]
    task = _task(target=(1.0, 0.0))

    # Score is 0 (irrelevant for this profile) but the body moved toward the target.
    result = qualify(_CREATURE, task, profile, simulate=_fixed_simulate(0.0))

    assert [c.name for c in result.checks] == ["Task setup", "Baseline task success", "Robustness"]
    baseline = result.checks[1]
    assert baseline.passed is True
    assert "target progress" in baseline.detail


def test_target_reach_profile_fails_with_no_progress():
    profile = BUILTIN_PROFILES["target-reach"]
    task = _task(target=(-5.0, 0.0))  # behind the body's forward motion

    result = qualify(_CREATURE, task, profile, simulate=_fixed_simulate(0.0))

    assert result.checks[1].passed is False
    assert result.primary_blocker == "Baseline task success"


def test_target_reach_profile_short_circuits_on_a_target_less_task():
    """Regression: previously the baseline check ran anyway and reported a
    confusing "target progress +0.000 m" - now it's caught up front as a task/
    profile mismatch, without running any physics at all."""
    profile = BUILTIN_PROFILES["target-reach"]
    task = _task()  # no target

    calls = []
    result = qualify(_CREATURE, task, profile, simulate=lambda c, t: calls.append(1) or _trace(0.0))

    assert calls == []  # simulate was never called
    assert result.passed is False
    assert result.primary_blocker == "Task setup"
    assert [c.name for c in result.checks] == ["Task setup"]
    assert "has none" in result.checks[0].detail


def test_push_recovery_profile_fails_without_a_disturbance_event():
    """Regression: previously push-recovery passed trivially on a task that never
    pushes/damages the creature at all, since nothing tested the actual claim."""
    profile = BUILTIN_PROFILES["push-recovery"]
    task = _task()  # no damage_event or impulse_event

    calls = []
    result = qualify(_CREATURE, task, profile, simulate=lambda c, t: calls.append(1) or _trace(1.0))

    assert calls == []
    assert result.passed is False
    assert result.primary_blocker == "Task setup"
    assert "neither" in result.checks[0].detail


def test_push_recovery_profile_runs_normally_with_a_disturbance_event():
    profile = BUILTIN_PROFILES["push-recovery"]
    task_data = _task().model_dump(mode="json")
    task_data["impulse_event"] = {"time": 0.5, "part_id": "torso", "force": [5.0, 0.0, 0.0]}
    task = TaskSpec.model_validate(task_data)

    result = qualify(_CREATURE, task, profile, simulate=_fixed_simulate(1.0))

    assert [c.name for c in result.checks] == ["Task setup", "Baseline task success", "Robustness"]
    assert result.checks[0].passed is True
    assert result.passed is True


def test_sim2sim_gap_is_checked_when_a_second_backend_is_given():
    profile = QualificationProfile(
        name="p",
        description="",
        min_score=0.0,
        robustness_trials=2,
        max_fail_rate=1.0,
        max_sim2sim_gap=0.1,
    )

    def other_backend_simulate(creature: CreatureSpec, task: TaskSpec) -> EpisodeTrace:
        return _trace(0.9, backend="other")  # far from the 0.5 baseline

    result = qualify(
        _CREATURE,
        _task(),
        profile,
        simulate=_fixed_simulate(0.5),
        simulate_other_backend=other_backend_simulate,
    )

    portability = next(c for c in result.checks if c.name == "Backend portability")
    assert portability.passed is False
    assert result.primary_blocker == "Backend portability"


def test_sim2sim_profile_requires_a_second_backend():
    profile = QualificationProfile(
        name="p", description="", min_score=0.0, robustness_trials=2, max_sim2sim_gap=0.1
    )
    result = qualify(_CREATURE, _task(), profile, simulate=_fixed_simulate(0.5))

    assert result.primary_blocker == "Backend portability"
    assert result.checks[0].passed is False


def test_qualify_passes_through_robustness_progress_and_cancellation():
    """The on_trial/should_stop kwargs must reach run_trials unchanged - this is
    what lets the editor's Qualify panel show progress and actually cancel."""
    profile = QualificationProfile(
        name="p", description="", min_score=0.0, robustness_trials=10, max_fail_rate=1.0
    )
    seen: list[tuple[int, int]] = []
    stop_after = 3

    result = qualify(
        _CREATURE,
        _task(),
        profile,
        simulate=_fixed_simulate(0.5),
        on_trial=lambda done, total: seen.append((done, total)),
        should_stop=lambda: len(seen) >= stop_after,
    )

    assert seen == [(1, 10), (2, 10), (3, 10)]
    robustness = next(c for c in result.checks if c.name == "Robustness")
    assert "3/10 trials" in robustness.detail
    assert "stopped early" in robustness.detail


def test_builtin_profiles_are_internally_consistent():
    for key, profile in BUILTIN_PROFILES.items():
        assert profile.name == key
        assert profile.description
