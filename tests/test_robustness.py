"""Tests for the backend-agnostic robustness trial/perturbation logic (Phase 2)."""

from __future__ import annotations

import pytest

from creature_lab.robustness import (
    ROBUSTNESS_LEVELS,
    RobustnessResult,
    RobustnessTrial,
    perturb,
    plain_language_verdict,
    run_trials,
)
from creature_lab.schema import CreatureSpec, TaskSpec


def _creature() -> CreatureSpec:
    return CreatureSpec.model_validate(
        {
            "name": "test_bot",
            "parts": [
                {"id": "torso", "shape": "box", "size": [0.4, 0.2, 0.1], "mass": 1.0},
                {"id": "leg", "shape": "capsule", "length": 0.3, "radius": 0.04, "mass": 0.2},
            ],
            "joints": [
                {"id": "hip", "parent": "torso", "child": "leg", "type": "fixed"},
            ],
        }
    )


def _task() -> TaskSpec:
    return TaskSpec.model_validate({"name": "crawl_forward", "duration": 1.0})


def test_perturb_is_deterministic_for_a_given_seed():
    a = perturb(_creature(), _task(), seed=5)
    b = perturb(_creature(), _task(), seed=5)

    assert a[2] == b[2]  # mass_scale
    assert a[3] == b[3]  # friction_scale
    assert [p.mass for p in a[0].parts] == [p.mass for p in b[0].parts]


def test_perturb_different_seeds_differ():
    a = perturb(_creature(), _task(), seed=1)
    b = perturb(_creature(), _task(), seed=2)

    assert a[2] != b[2]


def test_perturb_stays_within_the_jitter_bound():
    creature, task, mass_scale, friction_scale = perturb(
        _creature(), _task(), seed=3, mass_jitter=0.1, friction_jitter=0.2
    )

    assert 0.9 <= mass_scale <= 1.1
    assert 0.8 <= friction_scale <= 1.2
    original = _creature()
    for original_part, perturbed_part in zip(original.parts, creature.parts, strict=True):
        assert perturbed_part.mass == pytest.approx(original_part.mass * mass_scale)
    assert task.terrain.friction == pytest.approx(_task().terrain.friction * friction_scale)


def test_perturb_never_produces_negative_friction():
    # A huge jitter would drive friction negative without the floor-at-zero clamp.
    _, task, _, friction_scale = perturb(_creature(), _task(), seed=7, friction_jitter=5.0)

    assert friction_scale < 0 or task.terrain.friction >= 0.0
    assert task.terrain.friction >= 0.0


def test_run_trials_computes_summary_statistics():
    scores = iter([0.5, 0.6, 0.4, 0.5, 0.5])

    def evaluate(creature: CreatureSpec, task: TaskSpec) -> tuple[float, bool]:
        return next(scores), False

    result = run_trials(_creature(), _task(), evaluate, trials=5, seed=0)

    assert len(result.trials) == 5
    assert result.mean_score == pytest.approx(0.5)
    assert result.min_score == pytest.approx(0.4)
    assert result.max_score == pytest.approx(0.6)
    assert result.fail_rate == 0.0


def test_run_trials_reports_fail_rate():
    fell_flags = iter([True, False, True, False])

    def evaluate(creature: CreatureSpec, task: TaskSpec) -> tuple[float, bool]:
        return 0.1, next(fell_flags)

    result = run_trials(_creature(), _task(), evaluate, trials=4, seed=0)

    assert result.fail_rate == 0.5


def test_run_trials_uses_sequential_seeds_from_the_base():
    seeds_seen = []

    def evaluate(creature: CreatureSpec, task: TaskSpec) -> tuple[float, bool]:
        return 0.0, False

    run_trials(_creature(), _task(), evaluate, trials=3, seed=10)
    # Re-run and capture seeds via perturb directly, since run_trials doesn't expose them.
    result = run_trials(_creature(), _task(), evaluate, trials=3, seed=10)
    seeds_seen = [t.seed for t in result.trials]

    assert seeds_seen == [10, 11, 12]


def test_run_trials_rejects_zero_trials():
    def evaluate(creature: CreatureSpec, task: TaskSpec) -> tuple[float, bool]:
        return 0.0, False

    with pytest.raises(ValueError):
        run_trials(_creature(), _task(), evaluate, trials=0)


def test_run_trials_reports_progress_after_each_trial():
    def evaluate(creature: CreatureSpec, task: TaskSpec) -> tuple[float, bool]:
        return 0.0, False

    seen: list[tuple[int, int]] = []
    run_trials(
        _creature(),
        _task(),
        evaluate,
        trials=4,
        on_trial=lambda done, total: seen.append((done, total)),
    )

    assert seen == [(1, 4), (2, 4), (3, 4), (4, 4)]


def test_run_trials_stops_early_and_summarizes_partial_results():
    calls = 0

    def evaluate(creature: CreatureSpec, task: TaskSpec) -> tuple[float, bool]:
        nonlocal calls
        calls += 1
        return 1.0, False

    result = run_trials(_creature(), _task(), evaluate, trials=10, should_stop=lambda: calls >= 3)

    assert calls == 3
    assert len(result.trials) == 3


def test_run_trials_stopping_before_any_trial_raises():
    def evaluate(creature: CreatureSpec, task: TaskSpec) -> tuple[float, bool]:
        return 0.0, False

    with pytest.raises(ValueError):
        run_trials(_creature(), _task(), evaluate, trials=5, should_stop=lambda: True)


def _result(*, scores: list[float], fell: list[bool]) -> RobustnessResult:
    import statistics as _stats

    trials = [
        RobustnessTrial(seed=i, score=s, fell=f, mass_scale=1.0, friction_scale=1.0)
        for i, (s, f) in enumerate(zip(scores, fell, strict=True))
    ]
    return RobustnessResult(
        trials=trials,
        mean_score=_stats.fmean(scores),
        std_score=_stats.pstdev(scores) if len(scores) > 1 else 0.0,
        min_score=min(scores),
        max_score=max(scores),
        fail_rate=sum(fell) / len(fell),
    )


def test_robustness_levels_are_ordered_trial_counts():
    assert (
        ROBUSTNESS_LEVELS["Quick"] < ROBUSTNESS_LEVELS["Standard"] < ROBUSTNESS_LEVELS["Thorough"]
    )


def test_plain_language_verdict_robust():
    result = _result(scores=[1.0, 1.02, 0.99, 1.01], fell=[False, False, False, False])
    verdict = plain_language_verdict(result)
    assert verdict.startswith("Passed these checks")
    assert "4 of 4 trials" in verdict
    assert "mass scales" in verdict and "friction scales" in verdict


def test_plain_language_verdict_fragile_on_high_fail_rate():
    result = _result(scores=[1.0, 0.1, 1.0, 0.1], fell=[False, True, False, True])
    verdict = plain_language_verdict(result)
    assert verdict.startswith("Failures or variation in these checks")
    assert "2 of 4 trials" in verdict


def test_plain_language_verdict_moderately_robust():
    result = _result(scores=[1.0, 0.85, 1.0, 1.0, 0.9], fell=[False, False, False, False, True])
    verdict = plain_language_verdict(result)
    assert verdict.startswith("Some sensitivity in these checks")


def test_plain_language_verdict_handles_zero_mean_score():
    result = _result(scores=[0.0, 0.0], fell=[False, False])
    verdict = plain_language_verdict(result)
    assert "0%" in verdict
