"""Failure-first experiment autopsy, independent of any physics backend."""

from __future__ import annotations

import html
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from creature_lab.diagnosis import diagnose
from creature_lab.diagnostics import summarize_episode
from creature_lab.qualification import (
    BUILTIN_PROFILES,
    QualificationProfile,
    task_setup_check,
    task_success,
)
from creature_lab.robustness import RobustnessResult, run_trials
from creature_lab.schema import CreatureSpec, EpisodeTrace, TaskSpec

SimulateFn = Callable[[CreatureSpec, TaskSpec], EpisodeTrace]


@dataclass(frozen=True)
class AutopsyEvidence:
    name: str
    passed: bool | None
    detail: str


@dataclass(frozen=True)
class TrialRecording:
    creature: CreatureSpec
    task: TaskSpec
    trace: EpisodeTrace


@dataclass(frozen=True)
class AutopsyResult:
    creature: str
    task: str
    profile: str
    primary_cause: str
    confidence: str
    summary: str
    evidence: list[AutopsyEvidence]
    recommendations: list[str]
    baseline_trace: EpisodeTrace = field(repr=False)
    reference_trace: EpisodeTrace | None = field(repr=False)
    other_backend_trace: EpisodeTrace | None = field(default=None, repr=False)
    robustness: RobustnessResult | None = field(default=None, repr=False)
    trial_recordings: list[TrialRecording] = field(default_factory=list, repr=False)

    def to_json_dict(self) -> dict[str, object]:
        robustness = None
        if self.robustness is not None:
            robustness = {
                "trials": len(self.robustness.trials),
                "mean_score": self.robustness.mean_score,
                "std_score": self.robustness.std_score,
                "fail_rate": self.robustness.fail_rate,
                "trial_details": [asdict(trial) for trial in self.robustness.trials],
            }
        return {
            "creature": self.creature,
            "task": self.task,
            "profile": self.profile,
            "primary_cause": self.primary_cause,
            "confidence": self.confidence,
            "confidence_method": "heuristic; not a calibrated probability",
            "summary": self.summary,
            "evidence": [evidence.__dict__ for evidence in self.evidence],
            "recommendations": self.recommendations,
            "baseline": {
                "run_id": self.baseline_trace.run_id,
                "backend": self.baseline_trace.backend,
                "score": self.baseline_trace.score,
            },
            "reference": (
                {
                    "run_id": self.reference_trace.run_id,
                    "backend": self.reference_trace.backend,
                    "score": self.reference_trace.score,
                }
                if self.reference_trace is not None
                else None
            ),
            "other_backend": (
                {
                    "run_id": self.other_backend_trace.run_id,
                    "backend": self.other_backend_trace.backend,
                    "score": self.other_backend_trace.score,
                }
                if self.other_backend_trace is not None
                else None
            ),
            "robustness": robustness,
            "evidence_packs": {
                "reference": "evidence/reference" if self.reference_trace is not None else None,
                "other_backend": (
                    "evidence/other_backend" if self.other_backend_trace is not None else None
                ),
                "trials": [
                    {"path": f"evidence/trial_{index + 1:03d}", "run_id": item.trace.run_id}
                    for index, item in enumerate(self.trial_recordings)
                ],
            },
        }


def infer_profile(task: TaskSpec) -> QualificationProfile:
    if task.target is not None:
        return BUILTIN_PROFILES["target-reach"]
    if task.damage_event is not None or task.impulse_event is not None:
        return BUILTIN_PROFILES["push-recovery"]
    return BUILTIN_PROFILES["basic-locomotion"]


def distinct_curated_reference(creature: CreatureSpec, controller: str) -> bool:
    """Only claim a counterfactual when exact controller snapshots differ."""
    from creature_lab.controllers.factory import curated_controller
    from creature_lab.exporting import file_hash, resolve_controller_bundle

    reference = curated_controller(creature)
    selected = reference if controller == "curated" else controller
    try:
        a = resolve_controller_bundle(creature, selected)
        b = resolve_controller_bundle(creature, reference)
        if not a.exact or not b.exact:
            return False

        def behavior(bundle):
            data = bundle.spec.model_dump(mode="json", exclude_none=True)
            for key in ("name", "creature_hash", "task_hash", "runtime_versions"):
                data.pop(key, None)
            if bundle.policy_source is not None:
                data["policy_file"] = file_hash(bundle.policy_source)
            return data

        return behavior(a) != behavior(b)
    except (OSError, ValueError):
        return False


def run_autopsy(
    creature: CreatureSpec,
    task: TaskSpec,
    *,
    simulate: SimulateFn,
    simulate_reference: SimulateFn | None,
    profile: QualificationProfile | None = None,
    simulate_other_backend: SimulateFn | None = None,
    robustness_trials: int = 5,
) -> AutopsyResult:
    """Run baseline/counterfactual/perturbation/backend evidence and attribute failure."""
    profile = profile or infer_profile(task)
    setup = task_setup_check(profile, task)
    if setup is not None and not setup.passed:
        raise ValueError(f"Task/profile mismatch: {setup.detail}")
    if profile.max_sim2sim_gap is not None and simulate_other_backend is None:
        raise ValueError("This profile requires a second physics backend.")
    baseline = simulate(creature, task)
    baseline_summary = summarize_episode(baseline, task, creature)
    baseline_ok = task_success(profile, baseline, baseline_summary)

    reference = simulate_reference(creature, task) if simulate_reference is not None else None
    reference_summary = summarize_episode(reference, task, creature) if reference else None
    reference_ok = task_success(profile, reference, reference_summary) if reference else None
    trial_recordings: list[TrialRecording] = []

    def evaluate(c: CreatureSpec, t: TaskSpec) -> tuple[float, bool, bool]:
        trace = simulate(c, t)
        trial_recordings.append(TrialRecording(c, t, trace))
        summary = summarize_episode(trace, t, c)
        return trace.score, bool(summary.fell), task_success(profile, trace, summary)

    robustness = run_trials(
        creature,
        task,
        evaluate,
        trials=robustness_trials,
        mass_jitter=profile.robustness_mass_jitter,
        friction_jitter=profile.robustness_friction_jitter,
    )
    robust_ok = robustness.fail_rate <= profile.max_fail_rate

    other = simulate_other_backend(creature, task) if simulate_other_backend is not None else None
    portability_ok = True
    normalized_gap = None
    if other is not None:
        normalized_gap = abs(baseline.score - other.score) / max(
            1.0, abs(baseline.score), abs(other.score)
        )
        threshold = profile.max_sim2sim_gap if profile.max_sim2sim_gap is not None else 0.2
        portability_ok = normalized_gap <= threshold

    diagnosis = diagnose(baseline, creature, task)
    evidence = [
        AutopsyEvidence(
            "Selected controller task success",
            baseline_ok,
            f"score={baseline.score:.4f}, fell={bool(baseline_summary.fell)}",
        ),
        AutopsyEvidence(
            "Curated-controller counterfactual",
            reference_ok,
            (
                f"score={reference.score:.4f}, fell={bool(reference_summary.fell)}"
                if reference is not None and reference_summary is not None
                else "Not run: selected and curated controllers cannot be distinguished."
            ),
        ),
        AutopsyEvidence(
            "Perturbation robustness",
            robust_ok,
            f"task failure rate={robustness.fail_rate:.0%} over {len(robustness.trials)} trials",
        ),
    ]
    if other is not None:
        evidence.append(
            AutopsyEvidence(
                "Backend agreement",
                portability_ok,
                f"normalized score gap={normalized_gap:.3f} "
                f"({baseline.backend} vs {other.backend})",
            )
        )

    if not baseline_ok and reference_ok is None:
        cause = "undetermined"
        confidence = "low"
        summary = "No distinct controller counterfactual was available; the cause is unknown."
        recommendations = ["Select a different controller and rerun the analysis."]
    elif not baseline_ok and reference_ok:
        cause = "controller"
        confidence = "high"
        summary = "The same body and task succeed with the curated controller."
        recommendations = [
            "Compare joint targets and phase relationships against the curated controller.",
            "Reduce gait amplitude/frequency or migrate the curated gait into controller.json.",
        ]
    elif not baseline_ok and not reference_ok:
        cause = "undetermined"
        confidence = "low"
        summary = (
            "Both tested controllers failed. The evidence does not distinguish a controller "
            "problem from a body or task problem."
        )
        recommendations = [
            "Try another controller or change one body or task variable at a time.",
            "Check task scale, target/event placement, support polygon, and center of mass.",
        ]
    elif not robust_ok:
        cause = "fragility"
        confidence = "high"
        summary = "The baseline works, but small mass/friction changes frequently break it."
        recommendations = [
            "Widen the stance, lower the center of mass, or slow the controller.",
            "Tune against a distribution of perturbations instead of one nominal setup.",
        ]
    elif not portability_ok:
        cause = "backend_sensitivity"
        confidence = "medium"
        summary = "Nominal behavior depends strongly on one backend's contact dynamics."
        recommendations = [
            "Inspect trajectory divergence and reduce contact-model-sensitive gait tuning.",
            "Treat the artifact as structurally portable, not behaviorally portable yet.",
        ]
    else:
        cause = "no_failure_detected"
        confidence = "high"
        summary = "The selected controller passed nominal, perturbation, and requested checks."
        recommendations = [
            "Increase perturbation strength or add a more demanding task-specific threshold."
        ]

    if diagnosis.patterns:
        recommendations.extend(diagnosis.suggestions[:2])
    return AutopsyResult(
        creature=creature.name,
        task=task.name,
        profile=profile.name,
        primary_cause=cause,
        confidence=confidence,
        summary=summary,
        evidence=evidence,
        recommendations=list(dict.fromkeys(recommendations)),
        baseline_trace=baseline,
        reference_trace=reference,
        other_backend_trace=other,
        robustness=robustness,
        trial_recordings=trial_recordings,
    )


def write_autopsy_evidence(
    result: AutopsyResult,
    creature: CreatureSpec,
    task: TaskSpec,
    out: Path,
    *,
    overwrite: bool = False,
) -> None:
    """Save hash-verifiable packs for each recorded counterfactual and trial."""
    import shutil

    from creature_lab.exporting import export_design_pack, verify_design_pack

    evidence_dir = out / "evidence"
    if evidence_dir.exists():
        if not overwrite:
            raise FileExistsError(f"evidence directory already exists: {evidence_dir}")
        if evidence_dir.is_symlink() or evidence_dir.resolve().parent != out.resolve():
            raise ValueError("refusing to replace an evidence directory outside the report")
        shutil.rmtree(evidence_dir)
    recordings: list[tuple[str, CreatureSpec, TaskSpec, EpisodeTrace]] = []
    if result.reference_trace is not None:
        recordings.append(("reference", creature, task, result.reference_trace))
    if result.other_backend_trace is not None:
        recordings.append(("other_backend", creature, task, result.other_backend_trace))
    for index, trial in enumerate(result.trial_recordings):
        recordings.append((f"trial_{index + 1:03d}", trial.creature, trial.task, trial.trace))
    for name, body, scenario, trace in recordings:
        destination = evidence_dir / name
        export_design_pack(body, scenario, trace, out_dir=destination)
        verification = verify_design_pack(destination)
        if not verification.valid:
            raise ValueError(
                f"{name} evidence verification failed: {'; '.join(verification.errors)}"
            )


def autopsy_to_markdown(result: AutopsyResult) -> str:
    lines = [
        f"# Creature Lab Experiment Autopsy: {result.creature}",
        "",
        f"**Candidate explanation:** `{result.primary_cause}` (heuristic)",
        "",
        "This rule-based assessment is not a calibrated probability or proof of causation.",
        "",
        result.summary,
        "",
        "## Evidence",
        "",
    ]
    for item in result.evidence:
        status = "SKIPPED" if item.passed is None else "PASS" if item.passed else "FAIL"
        lines.append(f"- {status} — **{item.name}:** {item.detail}")
    lines.extend(["", "## Recommended next experiments", ""])
    lines.extend(f"- {item}" for item in result.recommendations)
    lines.append("")
    return "\n".join(lines)


def autopsy_to_html(result: AutopsyResult) -> str:
    payload = result.to_json_dict()
    evidence = "".join(
        f"<li class='{'skipped' if item.passed is None else 'pass' if item.passed else 'fail'}'>"
        "<strong>"
        f"{html.escape(item.name)}</strong>: {html.escape(item.detail)}</li>"
        for item in result.evidence
    )
    recommendations = "".join(f"<li>{html.escape(item)}</li>" for item in result.recommendations)
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Creature Lab Autopsy</title>
<style>body{{font:16px system-ui;max-width:900px;margin:3rem auto;padding:0 1rem;color:#172033}}
.card{{border:1px solid #ccd3df;border-radius:12px;padding:1.2rem;margin:1rem 0}}
.pass{{color:#176b3a}}.fail{{color:#a52b2b}}code{{background:#eef1f6;padding:.15rem .35rem}}
</style></head><body><h1>Experiment Autopsy: {html.escape(result.creature)}</h1>
<div class="card"><h2>Candidate explanation: <code>{html.escape(result.primary_cause)}</code></h2>
<p>{html.escape(result.summary)}</p><p>This rule-based assessment is not a calibrated
probability or proof of causation.</p></div>
<h2>Evidence</h2><ul>{evidence}</ul><h2>Recommended next experiments</h2>
<ul>{recommendations}</ul><details><summary>Machine-readable result</summary>
<pre>{html.escape(json.dumps(payload, indent=2))}</pre></details></body></html>"""
