"""Qualification: combine task success, robustness, and backend portability into one
pass/fail result with a named primary blocker and a recommended next test.

Mirrors ``robustness.py``'s and ``evolve.py``'s pattern: this module never runs physics
itself. The caller injects a ``simulate`` (and optionally ``simulate_other_backend``)
function backed by whichever simulator/controller it likes, so qualification composes
the existing pieces (a baseline run, a robustness sweep, a cross-backend comparison)
instead of being a new isolated feature.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from creature_lab.diagnostics import summarize_episode
from creature_lab.robustness import run_trials
from creature_lab.schema import CreatureSpec, EpisodeSummary, EpisodeTrace, TaskSpec

#: (creature, task) -> EpisodeTrace, backend/controller already bound by the caller.
SimulateFn = Callable[[CreatureSpec, TaskSpec], EpisodeTrace]


@dataclass(frozen=True)
class QualificationProfile:
    """What "good enough" means for one kind of task. See ``BUILTIN_PROFILES``."""

    name: str
    description: str
    #: Minimum baseline score. None disables the score half of the success check.
    min_score: float | None = None
    require_no_fall: bool = True
    #: If the task has a target, require the baseline run to have net closed the
    #: distance to it (used instead of min_score for target-reaching profiles).
    #: Also makes the task-setup check require the task to actually have a target.
    require_target_progress: bool = False
    #: Task-setup check requires ``task.damage_event`` or ``task.impulse_event`` -
    #: there is something to actually survive (used by push-recovery-style profiles).
    require_disturbance_event: bool = False
    robustness_trials: int = 10
    robustness_mass_jitter: float = 0.05
    robustness_friction_jitter: float = 0.05
    max_fail_rate: float = 0.2
    #: None disables the cross-backend check.
    max_sim2sim_gap: float | None = None


@dataclass(frozen=True)
class QualificationCheck:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class QualificationResult:
    profile: str
    passed: bool
    checks: list[QualificationCheck] = field(default_factory=list)
    #: Name of the first failing check, in priority order (None if passed).
    primary_blocker: str | None = None
    recommended_next_test: str | None = None


BUILTIN_PROFILES: dict[str, QualificationProfile] = {
    "basic-locomotion": QualificationProfile(
        name="basic-locomotion",
        description="Walks without falling, and is robust to small mass/friction perturbations.",
        min_score=0.05,
        robustness_trials=10,
        max_fail_rate=0.2,
    ),
    "target-reach": QualificationProfile(
        name="target-reach",
        description="Makes positive progress toward the target; does not require arrival.",
        require_target_progress=True,
        robustness_trials=10,
        max_fail_rate=0.2,
    ),
    "push-recovery": QualificationProfile(
        name="push-recovery",
        description="Survives the task's impulse/damage event without falling.",
        min_score=None,
        require_disturbance_event=True,
        robustness_trials=10,
        max_fail_rate=0.3,
    ),
    "backend-portable": QualificationProfile(
        name="backend-portable",
        description="Behaves consistently across PyBullet and MuJoCo.",
        robustness_trials=5,
        max_fail_rate=0.3,
        max_sim2sim_gap=0.2,
    ),
}

# Threshold used when the caller explicitly requests a portability check for a
# profile that does not otherwise define one.
DEFAULT_SIM2SIM_GAP = 0.2

_RECOMMENDATIONS: dict[str, str] = {
    "Task setup": (
        "This is a task/profile mismatch, not a creature problem - edit the task JSON "
        "to add what the profile needs (a `target`, or a `damage_event`/`impulse_event`), "
        "or pick a different profile."
    ),
    "Baseline task success": (
        "Run `creature-lab diagnose` on this run and apply a suggested fix; if the "
        "task has a target, try `--controller target_seek`."
    ),
    "Robustness": (
        "Widen the stance, lower the centre of mass, or slow the gait, then rerun "
        "the robustness sweep - a fragile result usually means the gait is tuned to "
        "one exact body/terrain."
    ),
    "Backend portability": (
        "Run `creature-lab sim2sim` on this run to see where trajectories diverge; "
        "avoid gait tuning that depends on one backend's exact contact model."
    ),
}


def task_setup_check(profile: QualificationProfile, task: TaskSpec) -> QualificationCheck | None:
    """Whether the task itself meets this profile's precondition.

    Checked first and short-circuits the rest of ``qualify`` when it fails: without
    a target, target-reach's baseline check degrades to a confusing "0 m progress"
    that happens to fail for the wrong reason; without a disturbance event,
    push-recovery would trivially pass by never being tested at all. Returns None
    for profiles with no such precondition (nothing to report).
    """
    if profile.require_target_progress:
        has_target = task.target is not None
        detail = (
            "target present"
            if has_target
            else "profile requires a task with a target, but this task has none"
        )
        return QualificationCheck("Task setup", has_target, detail)
    if profile.require_disturbance_event:
        has_event = task.damage_event is not None or task.impulse_event is not None
        detail = (
            "impulse/damage event present"
            if has_event
            else "profile requires an impulse_event or damage_event, but this task has neither"
        )
        return QualificationCheck("Task setup", has_event, detail)
    return None


def qualify(
    creature: CreatureSpec,
    task: TaskSpec,
    profile: QualificationProfile,
    *,
    simulate: SimulateFn,
    simulate_other_backend: SimulateFn | None = None,
    on_trial: Callable[[int, int], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> QualificationResult:
    """Run a profile's checks against one creature/task and return a pass/fail result.

    Checks run in priority order (task setup, then baseline success, then
    robustness, then backend portability); the first one to fail becomes
    ``primary_blocker``. A failed task-setup check short-circuits everything else
    (there is nothing meaningful to simulate yet - see ``task_setup_check``); the
    checks downstream of a failed baseline still run and are reported, since a
    creature-level failure doesn't invalidate what robustness/portability show.

    ``on_trial``/``should_stop`` pass straight through to the robustness sweep's
    ``run_trials`` (the most expensive part of a qualify run) so a caller running
    this in a background job - see ``creature_lab.editor.live`` - can report
    progress and cooperatively cancel, same as a standalone robustness sweep.
    Stopping early still returns a ``QualificationResult`` built from whatever
    trials completed; the caller decides whether that should count as "cancelled".
    """
    setup_check = task_setup_check(profile, task)
    if setup_check is not None and not setup_check.passed:
        return QualificationResult(
            profile=profile.name,
            passed=False,
            checks=[setup_check],
            primary_blocker=setup_check.name,
            recommended_next_test=_RECOMMENDATIONS[setup_check.name],
        )

    if profile.max_sim2sim_gap is not None and simulate_other_backend is None:
        return QualificationResult(
            profile=profile.name,
            passed=False,
            checks=[
                QualificationCheck(
                    "Backend portability",
                    False,
                    "A second physics backend is required but unavailable.",
                )
            ],
            primary_blocker="Backend portability",
            recommended_next_test="Install the other physics backend before running this profile.",
        )

    checks: list[QualificationCheck] = []
    if setup_check is not None:
        checks.append(setup_check)

    baseline_trace = simulate(creature, task)
    baseline_summary = summarize_episode(baseline_trace, task, creature)
    checks.append(_baseline_check(profile, baseline_trace, baseline_summary))

    def evaluate(trial_creature: CreatureSpec, trial_task: TaskSpec) -> tuple[float, bool, bool]:
        trace = simulate(trial_creature, trial_task)
        summary = summarize_episode(trace, trial_task, trial_creature)
        success = _baseline_check(profile, trace, summary).passed
        return trace.score, bool(summary.fell), success

    robustness_result = run_trials(
        creature,
        task,
        evaluate,
        trials=profile.robustness_trials,
        mass_jitter=profile.robustness_mass_jitter,
        friction_jitter=profile.robustness_friction_jitter,
        on_trial=on_trial,
        should_stop=should_stop,
    )
    completed = len(robustness_result.trials) == profile.robustness_trials
    robust_ok = completed and robustness_result.fail_rate <= profile.max_fail_rate
    ran = len(robustness_result.trials)
    if ran == profile.robustness_trials:
        trial_note = f"{ran} trials"
    else:
        trial_note = f"{ran}/{profile.robustness_trials} trials - stopped early"
    checks.append(
        QualificationCheck(
            "Robustness",
            robust_ok,
            f"fail rate {robustness_result.fail_rate:.0%} <= {profile.max_fail_rate:.0%} "
            f"({trial_note}, mean score {robustness_result.mean_score:.4f})",
        )
    )

    if simulate_other_backend is not None:
        other_trace = simulate_other_backend(creature, task)
        threshold = (
            profile.max_sim2sim_gap if profile.max_sim2sim_gap is not None else DEFAULT_SIM2SIM_GAP
        )
        absolute_gap = abs(baseline_trace.score - other_trace.score)
        # Normalize so the same threshold remains meaningful across tasks whose
        # score scales differ, while retaining intuitive behavior around zero.
        gap = absolute_gap / max(1.0, abs(baseline_trace.score), abs(other_trace.score))
        gap_ok = gap <= threshold
        checks.append(
            QualificationCheck(
                "Backend portability",
                gap_ok,
                f"normalized score gap {gap:.4f} <= {threshold:.4f} "
                f"(absolute gap {absolute_gap:.4f}; "
                f"{baseline_trace.backend} vs {other_trace.backend})",
            )
        )

    passed = all(check.passed for check in checks)
    failing = next((check for check in checks if not check.passed), None)
    primary_blocker = failing.name if failing is not None else None
    recommended = _RECOMMENDATIONS.get(primary_blocker) if primary_blocker else None

    return QualificationResult(
        profile=profile.name,
        passed=passed,
        checks=checks,
        primary_blocker=primary_blocker,
        recommended_next_test=recommended,
    )


def _baseline_check(
    profile: QualificationProfile, trace: EpisodeTrace, summary: EpisodeSummary
) -> QualificationCheck:
    fell = bool(summary.fell)
    if profile.require_target_progress:
        progress = summary.target_progress or 0.0
        ok = progress > 0.0 and (not fell or not profile.require_no_fall)
        detail = f"target progress {progress:+.3f} m, fell={fell}"
    else:
        score_ok = profile.min_score is None or trace.score >= profile.min_score
        fall_ok = not profile.require_no_fall or not fell
        ok = score_ok and fall_ok
        threshold = f" >= {profile.min_score}" if profile.min_score is not None else ""
        detail = f"score={trace.score:.4f}{threshold}, fell={fell}"
    return QualificationCheck("Baseline task success", ok, detail)


def task_success(
    profile: QualificationProfile,
    trace: EpisodeTrace,
    summary: EpisodeSummary,
) -> bool:
    """Public task/profile success predicate shared by qualification and autopsy."""
    return _baseline_check(profile, trace, summary).passed
