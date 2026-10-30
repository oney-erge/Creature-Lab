"""Fast backend-neutral tests for failure attribution and Failure Zoo artifacts."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from creature_lab.autopsy import (
    autopsy_to_html,
    distinct_curated_reference,
    run_autopsy,
    write_autopsy_evidence,
)
from creature_lab.cli import app
from creature_lab.exporting import verify_design_pack
from creature_lab.failure_zoo import build_failure_case, list_failure_cases
from creature_lab.qualification import QualificationProfile
from creature_lab.schema import CreatureSpec, EpisodeTrace, TaskSpec

runner = CliRunner()

CREATURE = CreatureSpec.model_validate(
    {
        "name": "boxbot",
        "parts": [{"id": "root", "shape": "box", "size": [0.2, 0.2, 0.2], "mass": 1}],
    }
)
TASK = TaskSpec.model_validate({"name": "move", "duration": 1.0})


def _trace(score: float, *, fell: bool = False) -> EpisodeTrace:
    orientation = [0.8, 0.6, 0, 0] if fell else [1, 0, 0, 0]
    return EpisodeTrace.model_validate(
        {
            "run_id": f"run_{str(score).replace('.', '_').replace('-', 'n')}",
            "creature_name": "boxbot",
            "task_name": "move",
            "backend": "fake",
            "score": score,
            "frames": [
                {"t": 0, "parts": {"root": {"position": [0, 0, 0.1]}}},
                {
                    "t": 1,
                    "parts": {
                        "root": {"position": [max(0, score), 0, 0.1], "orientation": orientation}
                    },
                    "score": score,
                },
            ],
        }
    )


def test_autopsy_attributes_controller_when_curated_counterfactual_succeeds():
    profile = QualificationProfile(name="move", description="", min_score=0.05, robustness_trials=2)
    result = run_autopsy(
        CREATURE,
        TASK,
        simulate=lambda _c, _t: _trace(0.0),
        simulate_reference=lambda _c, _t: _trace(0.5),
        profile=profile,
        robustness_trials=2,
    )

    assert result.primary_cause == "controller"
    assert result.confidence == "high"
    assert "Experiment Autopsy" in autopsy_to_html(result)


def test_autopsy_attributes_fragility_after_nominal_success():
    calls = 0

    def selected(_c, _t):
        nonlocal calls
        calls += 1
        return _trace(0.5) if calls == 1 else _trace(-1.0, fell=True)

    profile = QualificationProfile(
        name="move", description="", min_score=0.05, robustness_trials=3, max_fail_rate=0.2
    )
    result = run_autopsy(
        CREATURE,
        TASK,
        simulate=selected,
        simulate_reference=lambda _c, _t: _trace(0.5),
        profile=profile,
        robustness_trials=3,
    )

    assert result.primary_cause == "fragility"


def test_missing_controller_counterfactual_does_not_attribute_failure():
    profile = QualificationProfile(name="move", description="", min_score=0.05)
    result = run_autopsy(
        CREATURE,
        TASK,
        simulate=lambda _c, _t: _trace(0.0),
        simulate_reference=None,
        profile=profile,
        robustness_trials=2,
    )
    assert result.primary_cause == "undetermined"
    assert result.reference_trace is None
    assert result.evidence[1].passed is None
    assert result.to_json_dict()["robustness"]["trial_details"][0]["seed"] == 0
    assert not distinct_curated_reference(CREATURE, "curated")


def test_two_failing_controllers_do_not_establish_a_body_or_task_cause():
    profile = QualificationProfile(name="move", description="", min_score=0.05)
    result = run_autopsy(
        CREATURE,
        TASK,
        simulate=lambda _c, _t: _trace(0.0),
        simulate_reference=lambda _c, _t: _trace(0.0),
        profile=profile,
        robustness_trials=2,
    )
    assert result.primary_cause == "undetermined"
    assert "Both tested controllers failed" in result.summary


def test_autopsy_rejects_mismatched_profile_before_simulating():
    profile = QualificationProfile(name="push", description="", require_disturbance_event=True)

    def unexpected_simulation(_creature, _task):
        raise AssertionError("simulation must not start for an invalid task")

    with pytest.raises(ValueError, match="Task/profile mismatch"):
        run_autopsy(
            CREATURE, TASK, simulate=unexpected_simulation, simulate_reference=None, profile=profile
        )


def test_autopsy_evidence_preserves_each_trial_and_reference(tmp_path: Path):
    profile = QualificationProfile(name="move", description="", min_score=0.05)
    result = run_autopsy(
        CREATURE,
        TASK,
        simulate=lambda _c, _t: _trace(0.0),
        simulate_reference=lambda _c, _t: _trace(0.5),
        profile=profile,
        robustness_trials=2,
    )
    write_autopsy_evidence(result, CREATURE, TASK, tmp_path)
    for name in ("reference", "trial_001", "trial_002"):
        assert verify_design_pack(tmp_path / "evidence" / name).valid
    assert len(result.to_json_dict()["evidence_packs"]["trials"]) == 2


def test_failure_zoo_cases_build_valid_artifacts():
    assert len(list_failure_cases()) >= 6
    for case in list_failure_cases():
        creature, task, controller, restored = build_failure_case(case.id)
        assert creature.parts and task.step_count() > 0 and controller.name
        assert restored == case


def test_failure_export_cli_writes_a_teaching_bundle(tmp_path: Path):
    out = tmp_path / "failure"
    result = runner.invoke(app, ["failure", "export", "frozen-gait", "--out", str(out)])

    assert result.exit_code == 0, result.stdout
    assert {"creature.json", "task.json", "controller.json", "expected.json", "README.md"} <= {
        path.name for path in out.iterdir()
    }
