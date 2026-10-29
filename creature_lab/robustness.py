"""Score robustness under small seeded perturbations (backend-agnostic).

Mirrors ``evolve.py``'s pattern: this module perturbs specs and computes trial
statistics, but never runs physics itself — the caller injects an ``evaluate``
function backed by whichever simulator it likes.
"""

from __future__ import annotations

import random
import statistics
from collections.abc import Callable
from dataclasses import dataclass

from creature_lab.schema import CreatureSpec, TaskSpec

#: ``(creature, task) -> (score, fell)`` for legacy survival sweeps, or
#: ``(score, fell, succeeded)`` when a task/profile supplies a real success
#: predicate. The latter prevents "did not fall" from being reported as "won".
EvaluateFn = Callable[[CreatureSpec, TaskSpec], tuple[float, bool] | tuple[float, bool, bool]]


@dataclass(frozen=True)
class RobustnessTrial:
    seed: int
    score: float
    fell: bool
    mass_scale: float
    friction_scale: float
    succeeded: bool | None = None


@dataclass(frozen=True)
class RobustnessResult:
    trials: list[RobustnessTrial]
    mean_score: float
    std_score: float
    min_score: float
    max_score: float
    fail_rate: float


def perturb(
    creature: CreatureSpec,
    task: TaskSpec,
    seed: int,
    *,
    mass_jitter: float = 0.05,
    friction_jitter: float = 0.05,
) -> tuple[CreatureSpec, TaskSpec, float, float]:
    """Deterministically perturb part masses and ground friction for one trial.

    Returns the perturbed ``(creature, task)`` plus the scale factors actually used
    (for reporting). Re-validates both specs, since a multiplicative jitter can only
    ever keep a positive field positive, but this keeps the safety net explicit.
    """
    rng = random.Random(seed)
    mass_scale = 1.0 + rng.uniform(-mass_jitter, mass_jitter)
    friction_scale = 1.0 + rng.uniform(-friction_jitter, friction_jitter)

    creature_data = creature.model_dump()
    for part in creature_data["parts"]:
        part["mass"] *= mass_scale
    perturbed_creature = CreatureSpec.model_validate(creature_data)

    task_data = task.model_dump()
    task_data["terrain"]["friction"] = max(task.terrain.friction * friction_scale, 0.0)
    perturbed_task = TaskSpec.model_validate(task_data)

    return perturbed_creature, perturbed_task, mass_scale, friction_scale


def run_trials(
    creature: CreatureSpec,
    task: TaskSpec,
    evaluate: EvaluateFn,
    *,
    trials: int = 10,
    seed: int = 0,
    mass_jitter: float = 0.05,
    friction_jitter: float = 0.05,
    on_trial: Callable[[int, int], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> RobustnessResult:
    """Evaluate ``trials`` deterministically perturbed variants and summarize scores.

    ``on_trial(completed, total)`` is called after each trial finishes, so a caller
    running this in a background thread can report progress. ``should_stop()`` is
    checked before each trial; if it returns true, the sweep stops early and
    summarizes whatever trials completed (used for cooperative cancellation - see
    ``creature_lab.editor.jobs``). Both are no-ops by default, so existing callers are
    unaffected.
    """
    if trials < 1:
        raise ValueError("trials must be at least 1")

    results: list[RobustnessTrial] = []
    for i in range(trials):
        if should_stop is not None and should_stop():
            break
        trial_seed = seed + i
        perturbed_creature, perturbed_task, mass_scale, friction_scale = perturb(
            creature, task, trial_seed, mass_jitter=mass_jitter, friction_jitter=friction_jitter
        )
        evaluation = evaluate(perturbed_creature, perturbed_task)
        if len(evaluation) == 2:
            score, fell = evaluation
            succeeded = not fell
        else:
            score, fell, succeeded = evaluation
        results.append(
            RobustnessTrial(
                trial_seed,
                score,
                fell,
                mass_scale,
                friction_scale,
                succeeded=succeeded,
            )
        )
        if on_trial is not None:
            on_trial(len(results), trials)

    if not results:
        raise ValueError("no trials completed")
    scores = [trial.score for trial in results]
    return RobustnessResult(
        trials=results,
        mean_score=statistics.fmean(scores),
        std_score=statistics.pstdev(scores) if len(scores) > 1 else 0.0,
        min_score=min(scores),
        max_score=max(scores),
        fail_rate=sum(not bool(trial.succeeded) for trial in results) / len(results),
    )


#: Beginner-facing trial-count presets. Mass/friction jitter stay at the ``run_trials``
#: defaults for these; Advanced mode exposes the raw jitter sliders directly instead.
ROBUSTNESS_LEVELS: dict[str, int] = {"Quick": 5, "Standard": 10, "Thorough": 25}


def plain_language_verdict(result: RobustnessResult) -> str:
    """One-sentence, non-technical read of a robustness sweep's outcome."""
    trials = len(result.trials)
    if not trials:
        return "No trials completed."
    passed = sum(
        (not trial.fell) if trial.succeeded is None else trial.succeeded for trial in result.trials
    )
    spread = (
        result.std_score / abs(result.mean_score) if result.mean_score not in (0.0, -0.0) else 0.0
    )
    detail = (
        f"met the evaluation criterion in {passed} of {trials} trials, "
        f"with scores varying by about {spread:.0%}. "
        f"Observed mass scales {min(t.mass_scale for t in result.trials):.2f}–"
        f"{max(t.mass_scale for t in result.trials):.2f} and friction scales "
        f"{min(t.friction_scale for t in result.trials):.2f}–"
        f"{max(t.friction_scale for t in result.trials):.2f}."
    )
    if result.fail_rate == 0.0 and spread < 0.1:
        return f"Passed these checks — {detail}"
    if result.fail_rate <= 0.2 and spread < 0.25:
        return f"Some sensitivity in these checks — {detail}"
    return f"Failures or variation in these checks — {detail}"
