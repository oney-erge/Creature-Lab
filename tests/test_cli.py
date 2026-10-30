"""Tests for the command-line interface."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from creature_lab.cli import app

runner = CliRunner()
EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
EXAMPLE = EXAMPLES / "tripod.json"
TASK = EXAMPLES / "crawl_forward.json"


def test_version():
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "creature-lab" in result.stdout


def test_bare_invocation_runs_a_quick_episode(tmp_path, monkeypatch):
    """No subcommand should give an instant, terminal-only result (no browser/args)."""
    pytest.importorskip("pybullet")
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, [])

    assert result.exit_code == 0, result.stdout
    assert "score=" in result.stdout
    assert "quadruped" in result.stdout
    assert "creature-lab build" in result.stdout
    assert (tmp_path / "runs").exists()


def test_bare_invocation_does_not_swallow_subcommands():
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "creature-lab" in result.stdout
    assert "score=" not in result.stdout


def test_scaffold_humanoid_defaults_to_footed_12dof(tmp_path):
    out = tmp_path / "humanoid.json"

    result = runner.invoke(app, ["scaffold", "humanoid", "--out", str(out)])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(out.read_text())
    assert payload["name"] == "humanoid_12dof"
    assert len(payload["motors"]) == 12
    assert {"foot_l", "foot_r"} <= {part["id"] for part in payload["parts"]}


def test_doctor_runs_and_reports_checks():
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0, result.stdout
    assert "doctor" in result.stdout
    assert "platform" in result.stdout
    assert "examples run" in result.stdout


def test_inspect_reports_summary(tmp_path):
    pytest.importorskip("pybullet")
    runs_dir = tmp_path / "runs"
    run = runner.invoke(
        app, ["run", str(EXAMPLE), "--task", str(TASK), "--runs-dir", str(runs_dir)]
    )
    assert run.exit_code == 0, run.stdout
    [run_dir] = [path for path in runs_dir.iterdir() if path.is_dir()]

    result = runner.invoke(app, ["inspect", str(run_dir)])
    assert result.exit_code == 0, result.stdout
    assert "score breakdown" in result.stdout
    assert "contacts by part" in result.stdout
    assert "sha256:" in result.stdout
    assert "terrain" in result.stdout
    assert "plane" in result.stdout


def test_inspect_shows_non_flat_terrain(tmp_path):
    pytest.importorskip("pybullet")
    runs_dir = tmp_path / "runs"
    run = runner.invoke(
        app,
        ["zoo", "run", "quadruped", "--task", "slope_climb", "--runs-dir", str(runs_dir)],
    )
    assert run.exit_code == 0, run.stdout
    [run_dir] = [path for path in runs_dir.iterdir() if path.is_dir()]

    result = runner.invoke(app, ["inspect", str(run_dir)])
    assert result.exit_code == 0, result.stdout
    assert "slope" in result.stdout

    json_result = runner.invoke(app, ["inspect", str(run_dir), "--json"])
    payload = json.loads(json_result.stdout)
    assert "slope" in payload["terrain"]


def test_inspect_missing_path_exits_cleanly():
    result = runner.invoke(app, ["inspect", "does/not/exist"])
    assert result.exit_code == 2  # friendly file-not-found, not a raw traceback


def test_inspect_without_creature_json_still_summarizes(tmp_path):
    # A run dir / trace.json without a sibling creature.json must not crash inspect.
    trace = {
        "run_id": "r1",
        "creature_name": "c",
        "task_name": "t",
        "backend": "pybullet",
        "score": 0.5,
        "frames": [
            {"t": 0.1, "parts": {"a": {"position": [0, 0, 0]}}, "score": 0.0},
            {"t": 0.2, "parts": {"a": {"position": [1, 0, 0]}}, "score": 0.5},
        ],
    }
    (tmp_path / "trace.json").write_text(json.dumps(trace))
    result = runner.invoke(app, ["inspect", str(tmp_path)])
    assert result.exit_code == 0, result.stdout
    assert "final score" in result.stdout


def test_validate_example_creature():
    result = runner.invoke(app, ["validate", str(EXAMPLE)])
    assert result.exit_code == 0, result.stdout
    assert "valid" in result.stdout


def test_validate_missing_file():
    result = runner.invoke(app, ["validate", "does/not/exist.json"])
    assert result.exit_code == 2


def test_demo_missing_creature_exits():
    # The happy path serves a blocking viewer; exercise the spec-loading guard instead.
    result = runner.invoke(app, ["demo", "does/not/exist.json", "--task", "also/missing.json"])
    assert result.exit_code == 2


def test_validate_invalid_creature(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"name": "x"}))  # missing parts
    result = runner.invoke(app, ["validate", str(bad)])
    assert result.exit_code == 1
    assert "invalid CreatureSpec" in result.stdout


def test_validate_malformed_json(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    result = runner.invoke(app, ["validate", str(bad)])
    assert result.exit_code == 1
    assert "invalid JSON" in result.stdout


def test_run_saves_a_replayable_trace(tmp_path):
    pytest.importorskip("pybullet")
    runs_dir = tmp_path / "runs"
    result = runner.invoke(
        app, ["run", str(EXAMPLE), "--task", str(TASK), "--runs-dir", str(runs_dir)]
    )
    assert result.exit_code == 0, result.stdout
    assert "score=" in result.stdout

    [run_dir] = [path for path in runs_dir.iterdir() if path.is_dir()]
    replay_result = runner.invoke(app, ["replay", str(run_dir)])
    assert replay_result.exit_code == 0, replay_result.stdout
    assert "tripod" in replay_result.stdout
    assert "crawl_forward" in replay_result.stdout


def test_replay_missing_trace(tmp_path):
    result = runner.invoke(app, ["replay", str(tmp_path)])
    assert result.exit_code == 2


def _load(path: Path, model):
    return model.model_validate_json(path.read_text())


def test_simulate_reports_progress_via_on_step():
    """The editor's async job wiring depends on ``_simulate``'s on_step hook firing
    once per physics step, in order - this locks that contract in against real
    physics (not just a fake job)."""
    pytest.importorskip("pybullet")
    from creature_lab.cli import _simulate
    from creature_lab.schema import CreatureSpec, TaskSpec

    creature = _load(EXAMPLE, CreatureSpec)
    task = _load(TASK, TaskSpec)
    seen: list[tuple[int, int]] = []

    trace = _simulate(creature, task, on_step=lambda done, total: seen.append((done, total)))

    total = task.step_count()
    assert seen == [(i, total) for i in range(1, total + 1)]
    assert len(trace.frames) == total


def test_simulate_should_stop_produces_a_partial_trace():
    pytest.importorskip("pybullet")
    from creature_lab.cli import _simulate
    from creature_lab.schema import CreatureSpec, TaskSpec

    creature = _load(EXAMPLE, CreatureSpec)
    task = _load(TASK, TaskSpec)
    steps_done = 0

    def should_stop() -> bool:
        return steps_done >= 5

    def on_step(done: int, total: int) -> None:
        nonlocal steps_done
        steps_done = done

    trace = _simulate(creature, task, on_step=on_step, should_stop=should_stop)

    assert len(trace.frames) == 5
    assert steps_done == 5


def test_run_with_target_seek_controller_makes_real_progress_toward_the_target(tmp_path):
    """End-to-end through the real `run` command (not just the controller directly,
    which test_controllers.py already covers in detail): the saved trace should show
    the packaged quadruped finishing meaningfully closer to the target than it
    started. (A raw score comparison against a plain-cpg run is too fragile for this
    - contact-rich rigid-body dynamics are sensitive enough to small early heading
    corrections that score alone isn't a reliable signal run-to-run.)"""
    pytest.importorskip("pybullet")
    import math

    from creature_lab.runs import load_run

    quadruped = EXAMPLES / "quadruped.json"
    reach_target = EXAMPLES / "reach_target.json"
    runs_dir = tmp_path / "runs"

    result = runner.invoke(
        app,
        [
            "run",
            str(quadruped),
            "--task",
            str(reach_target),
            "--controller",
            "target_seek",
            "--runs-dir",
            str(runs_dir),
            "--json",
        ],
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)

    creature, task, trace = load_run(Path(payload["run_dir"]), runs_dir=runs_dir)
    root_id = next(
        part.id for part in creature.parts if part.id not in {j.child for j in creature.joints}
    )
    start_pos = trace.frames[0].parts[root_id].position
    final_pos = trace.frames[-1].parts[root_id].position
    tx, ty, _ = task.target.position
    initial_distance = math.hypot(tx - start_pos[0], ty - start_pos[1])
    final_distance = math.hypot(tx - final_pos[0], ty - final_pos[1])

    assert final_distance < initial_distance - 0.1


def test_run_target_seek_without_a_target_task_is_a_clean_error():
    pytest.importorskip("pybullet")
    result = runner.invoke(
        app, ["run", str(EXAMPLE), "--task", str(TASK), "--controller", "target_seek"]
    )
    assert result.exit_code != 0
    assert "requires a task with a target" in result.stdout


def test_qualify_passes_for_a_healthy_walker():
    pytest.importorskip("pybullet")
    quadruped = EXAMPLES / "quadruped.json"
    result = runner.invoke(
        app,
        [
            "qualify",
            str(quadruped),
            "--task",
            str(TASK),
            "--profile",
            "basic-locomotion",
            "--controller",
            "cpg",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["passed"] is True
    assert payload["primary_blocker"] is None
    assert {c["name"] for c in payload["checks"]} == {"Baseline task success", "Robustness"}


def test_qualify_fails_for_a_backward_drifting_creature_with_a_named_blocker():
    """The bundled tripod is known to drift backward (see test_diagnosis.py) - it
    should fail qualification's baseline check and name it as the primary blocker."""
    pytest.importorskip("pybullet")
    result = runner.invoke(
        app,
        [
            "qualify",
            str(EXAMPLE),
            "--task",
            str(TASK),
            "--profile",
            "basic-locomotion",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["passed"] is False
    assert payload["primary_blocker"] == "Baseline task success"
    assert payload["recommended_next_test"]


def test_qualify_robustness_check_detects_falls_on_a_task_without_fall_penalty(tmp_path):
    """Regression for the bug found in the Phase 3/4 audit: a creature that topples
    every trial must not report a 0% robustness fail rate just because the task
    (like the bundled crawl_forward) has no reward.fall_penalty."""
    pytest.importorskip("pybullet")
    creature_path = tmp_path / "faller.json"
    creature_path.write_text(
        json.dumps(
            {
                "name": "faller",
                "parts": [
                    {"id": "torso", "shape": "box", "size": [0.1, 0.1, 0.6], "mass": 2.0},
                    {
                        "id": "leg",
                        "shape": "capsule",
                        "length": 0.2,
                        "radius": 0.03,
                        "mass": 0.1,
                    },
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
    )

    result = runner.invoke(
        app,
        [
            "qualify",
            str(creature_path),
            "--task",
            str(TASK),  # crawl_forward: no reward.fall_penalty
            "--profile",
            "basic-locomotion",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    robustness = next(c for c in payload["checks"] if c["name"] == "Robustness")
    assert "fail rate 0%" not in robustness["detail"]


def test_qualify_push_recovery_rejects_a_task_without_a_disturbance_event():
    """Regression: push-recovery must not trivially pass a task that never pushes
    or damages the creature - nothing would have tested the actual claim."""
    pytest.importorskip("pybullet")
    result = runner.invoke(
        app,
        [
            "qualify",
            str(EXAMPLE),
            "--task",
            str(TASK),  # crawl_forward: no damage_event/impulse_event
            "--profile",
            "push-recovery",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["passed"] is False
    assert payload["primary_blocker"] == "Task setup"
    assert len(payload["checks"]) == 1
    assert payload["checks"][0]["name"] == "Task setup"
    assert payload["checks"][0]["passed"] is False
    assert "neither" in payload["checks"][0]["detail"]


def test_qualify_push_recovery_runs_normally_with_a_damage_event():
    pytest.importorskip("pybullet")
    result = runner.invoke(
        app,
        [
            "qualify",
            str(EXAMPLE),
            "--task",
            str(EXAMPLES / "recover_after_damage.json"),
            "--profile",
            "push-recovery",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert [c["name"] for c in payload["checks"]] == [
        "Task setup",
        "Baseline task success",
        "Robustness",
    ]
    assert payload["checks"][0]["passed"] is True


def test_qualify_target_reach_with_target_seek():
    pytest.importorskip("pybullet")
    quadruped = EXAMPLES / "quadruped.json"
    reach_target = EXAMPLES / "reach_target.json"
    result = runner.invoke(
        app,
        [
            "qualify",
            str(quadruped),
            "--task",
            str(reach_target),
            "--profile",
            "target-reach",
            "--controller",
            "target_seek",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    baseline = next(c for c in payload["checks"] if c["name"] == "Baseline task success")
    assert "target progress" in baseline["detail"]


def test_qualify_backend_portable_profile_runs_the_sim2sim_check():
    pytest.importorskip("pybullet")
    pytest.importorskip("mujoco")
    quadruped = EXAMPLES / "quadruped.json"
    result = runner.invoke(
        app,
        [
            "qualify",
            str(quadruped),
            "--task",
            str(TASK),
            "--profile",
            "backend-portable",
            "--controller",
            "cpg",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert any(c["name"] == "Backend portability" for c in payload["checks"])


def test_qualify_unknown_profile_is_a_clean_error():
    result = runner.invoke(
        app, ["qualify", str(EXAMPLE), "--task", str(TASK), "--profile", "not-a-real-profile"]
    )
    assert result.exit_code != 0
    assert "unknown profile" in result.stdout


def test_run_with_a_controller_json_path_matches_extracted_sinusoid(tmp_path):
    """--controller accepts a path to a controller.json (a ControllerSpec), not just
    a built-in name - an extracted sinusoid spec must reproduce the creature's own
    gait exactly, since that is the whole point of `controller extract`."""
    pytest.importorskip("pybullet")
    from creature_lab.controllers.factory import extract_sinusoid_spec
    from creature_lab.schema import CreatureSpec

    creature = CreatureSpec.model_validate_json(EXAMPLE.read_text())
    controller_path = tmp_path / "controller.json"
    controller_path.write_text(extract_sinusoid_spec(creature).model_dump_json())

    via_path = runner.invoke(
        app,
        [
            "run",
            str(EXAMPLE),
            "--task",
            str(TASK),
            "--controller",
            str(controller_path),
            "--json",
        ],
    )
    via_name = runner.invoke(
        app,
        ["run", str(EXAMPLE), "--task", str(TASK), "--controller", "sinusoid", "--json"],
    )
    assert via_path.exit_code == 0, via_path.stdout
    assert via_name.exit_code == 0, via_name.stdout
    assert json.loads(via_path.stdout)["score"] == json.loads(via_name.stdout)["score"]


def test_run_with_a_cpg_controller_json_path_applies_overrides(tmp_path):
    pytest.importorskip("pybullet")
    controller_path = tmp_path / "controller.json"
    controller_path.write_text(json.dumps({"type": "cpg", "amplitude": 0.05}))

    result = runner.invoke(
        app,
        [
            "run",
            str(EXAMPLE),
            "--task",
            str(TASK),
            "--controller",
            str(controller_path),
            "--json",
        ],
    )
    assert result.exit_code == 0, result.stdout


def test_run_with_a_missing_controller_json_path_is_a_clean_error():
    pytest.importorskip("pybullet")
    result = runner.invoke(
        app,
        [
            "run",
            str(EXAMPLE),
            "--task",
            str(TASK),
            "--controller",
            "does_not_exist.json",
        ],
    )
    assert result.exit_code != 0
    assert "file not found" in result.stdout.lower()


def test_run_with_an_invalid_controller_json_is_a_clean_error(tmp_path):
    pytest.importorskip("pybullet")
    controller_path = tmp_path / "controller.json"
    controller_path.write_text(json.dumps({"type": "sinusoid"}))  # missing required 'motors'

    result = runner.invoke(
        app,
        [
            "run",
            str(EXAMPLE),
            "--task",
            str(TASK),
            "--controller",
            str(controller_path),
        ],
    )
    assert result.exit_code != 0
    assert "invalid" in result.stdout.lower()


def test_build_rejects_a_controller_json_path():
    """The editor's Controller dropdown only ever offers the 3 built-in names, so a
    controller.json path must fail cleanly at launch, not silently break the
    dropdown's initial value."""
    result = runner.invoke(
        app, ["build", "--controller", "some_controller.json", "--no-open-browser"]
    )
    assert result.exit_code != 0
    assert "unknown controller" in result.stdout.lower()


def test_build_project_resumes_explicit_runtime_settings(tmp_path, monkeypatch):
    import creature_lab.editor.live as live

    seen = []
    monkeypatch.setattr(live, "run_editor", lambda session, **kwargs: seen.append(session))
    monkeypatch.setattr("creature_lab.cli.importlib.util.find_spec", lambda _name: None)
    project = tmp_path / "project"
    first = runner.invoke(
        app,
        [
            "build",
            "--project",
            str(project),
            "--controller",
            "sinusoid",
            "--backend",
            "mujoco",
            "--seed",
            "17",
            "--no-open-browser",
        ],
    )
    assert first.exit_code == 0, first.stdout
    second = runner.invoke(app, ["build", "--project", str(project), "--no-open-browser"])
    assert second.exit_code == 0, second.stdout
    assert (seen[-1].controller, seen[-1].backend, seen[-1].seed) == ("sinusoid", "mujoco", 17)


def test_controller_scaffold_cpg_writes_defaults_to_stdout():
    result = runner.invoke(app, ["controller", "scaffold", "cpg"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["type"] == "cpg"
    assert payload["amplitude"] == 0.8  # CPGController's own default


def test_controller_scaffold_target_seek_writes_defaults_to_a_file(tmp_path):
    out = tmp_path / "controller.json"
    result = runner.invoke(app, ["controller", "scaffold", "target_seek", "--out", str(out)])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(out.read_text())
    assert payload["type"] == "target_seek"
    assert payload["turn_gain"] == 1.2


def test_controller_scaffold_posture_writes_defaults_to_a_file(tmp_path):
    out = tmp_path / "controller.json"
    result = runner.invoke(app, ["controller", "scaffold", "posture", "--out", str(out)])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(out.read_text())
    assert payload["type"] == "posture"
    assert payload["kp"] == 40.0


def test_run_with_posture_controller_survives_a_forward_push(tmp_path):
    pytest.importorskip("pybullet")
    from creature_lab.editor import presets

    creature_path = tmp_path / "humanoid.json"
    creature_path.write_text(presets.generate_creature("humanoid").model_dump_json())
    task_path = tmp_path / "push.json"
    task_path.write_text(
        json.dumps(
            {
                "name": "posture_push",
                "duration": 3.0,
                "timestep": 1 / 60,
                "terrain": {"type": "plane", "friction": 1.0},
                "reward": {"forward_distance": 0.0, "survival": 1.0, "fall_penalty": 1.0},
                "impulse_event": {"time": 0.5, "part_id": "torso", "force": [400.0, 0.0, 0.0]},
            }
        )
    )
    result = runner.invoke(
        app,
        ["run", str(creature_path), "--task", str(task_path), "--controller", "posture", "--json"],
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["score"] >= 0  # survived and stayed upright -> survival reward, no fall


def test_controller_scaffold_rejects_sinusoid_and_unknown_types():
    for bad_type in ("sinusoid", "not_a_type"):
        result = runner.invoke(app, ["controller", "scaffold", bad_type])
        assert result.exit_code != 0
        assert "unknown controller type" in result.stdout.lower()


def test_controller_extract_reproduces_the_creatures_gait(tmp_path):
    out = tmp_path / "controller.json"
    result = runner.invoke(app, ["controller", "extract", str(EXAMPLE), "--out", str(out)])
    assert result.exit_code == 0, result.stdout

    from creature_lab.schema import ControllerSpec, CreatureSpec

    spec = ControllerSpec.model_validate_json(out.read_text())
    creature = CreatureSpec.model_validate_json(EXAMPLE.read_text())
    assert spec.type.value == "sinusoid"
    assert {m.joint for m in spec.motors} == {m.joint for m in creature.motors}


def test_controller_extract_rejects_a_motorless_creature(tmp_path):
    motorless = tmp_path / "motorless.json"
    motorless.write_text(
        json.dumps(
            {
                "name": "still",
                "parts": [{"id": "torso", "shape": "sphere", "radius": 0.1, "mass": 1.0}],
            }
        )
    )
    result = runner.invoke(app, ["controller", "extract", str(motorless)])
    assert result.exit_code != 0
    assert "no motors" in result.stdout.lower()


def test_controller_validate_accepts_a_matching_extracted_controller(tmp_path):
    out = tmp_path / "controller.json"
    runner.invoke(app, ["controller", "extract", str(EXAMPLE), "--out", str(out)])

    result = runner.invoke(app, ["controller", "validate", str(out), "--creature", str(EXAMPLE)])
    assert result.exit_code == 0, result.stdout
    assert "valid" in result.stdout.lower()


def test_controller_validate_rejects_a_creature_with_no_matching_motors(tmp_path):
    out = tmp_path / "controller.json"
    runner.invoke(app, ["controller", "extract", str(EXAMPLE), "--out", str(out)])  # tripod joints

    quadruped = EXAMPLES / "quadruped.json"
    result = runner.invoke(app, ["controller", "validate", str(out), "--creature", str(quadruped)])
    assert result.exit_code != 0
    assert "not hinges" in result.stdout.lower()


def test_controller_validate_target_seek_requires_a_target_task(tmp_path):
    out = tmp_path / "controller.json"
    runner.invoke(app, ["controller", "scaffold", "target_seek", "--out", str(out)])

    without_task = runner.invoke(
        app, ["controller", "validate", str(out), "--creature", str(EXAMPLE)]
    )
    assert without_task.exit_code != 0
    assert "requires a task with a target" in without_task.stdout

    with_task = runner.invoke(
        app,
        [
            "controller",
            "validate",
            str(out),
            "--creature",
            str(EXAMPLES / "quadruped.json"),
            "--task",
            str(EXAMPLES / "reach_target.json"),
        ],
    )
    assert with_task.exit_code == 0, with_task.stdout


def test_simulate_should_stop_before_any_step_raises():
    """Zero frames is treated as a hard failure by ``_simulate`` (a CLI concern); the
    editor's job wrapper is responsible for converting this into a clean cancellation
    when it was actually a cancel request (see ``editor/live.py``)."""
    pytest.importorskip("pybullet")
    import typer

    from creature_lab.cli import _simulate
    from creature_lab.schema import CreatureSpec, TaskSpec

    creature = _load(EXAMPLE, CreatureSpec)
    task = _load(TASK, TaskSpec)

    with pytest.raises(typer.Exit):
        _simulate(creature, task, should_stop=lambda: True)


def test_evolve_saves_best_creature(tmp_path):
    pytest.importorskip("pybullet")
    runs_dir = tmp_path / "runs"
    result = runner.invoke(
        app,
        [
            "evolve",
            str(EXAMPLE),
            "--task",
            str(TASK),
            "--attempts",
            "2",
            "--seed",
            "0",
            "--runs-dir",
            str(runs_dir),
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert "best" in result.stdout

    [run_dir] = [path for path in runs_dir.iterdir() if path.is_dir()]
    assert (run_dir / "creature.json").exists()
    assert (run_dir / "trace.json").exists()


def test_optimize_writes_a_controller_json_that_reproduces_its_own_score(tmp_path):
    pytest.importorskip("pybullet")
    pytest.importorskip("cmaes")
    out = tmp_path / "controller.json"
    result = runner.invoke(
        app,
        [
            "optimize",
            str(EXAMPLE),
            "--task",
            str(TASK),
            "--attempts",
            "6",
            "--seed",
            "0",
            "--out",
            str(out),
            "--json",
        ],
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["best_score"] >= payload["seed_score"]  # CMA-ES only keeps improvements
    assert out.exists()

    from creature_lab.schema import ControllerSpec

    spec = ControllerSpec.model_validate_json(out.read_text())
    assert spec.type.value == "sinusoid"
    assert spec.motors  # non-empty: extracted from the optimized creature's motors

    replay = runner.invoke(
        app, ["run", str(EXAMPLE), "--task", str(TASK), "--controller", str(out), "--json"]
    )
    assert replay.exit_code == 0, replay.stdout
    assert json.loads(replay.stdout)["score"] == pytest.approx(payload["best_score"])


def test_optimize_prints_to_stdout_when_no_out_given():
    pytest.importorskip("pybullet")
    pytest.importorskip("cmaes")
    result = runner.invoke(
        app, ["optimize", str(EXAMPLE), "--task", str(TASK), "--attempts", "4", "--seed", "0"]
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["type"] == "sinusoid"


def test_optimize_never_touches_the_creatures_body(tmp_path):
    pytest.importorskip("pybullet")
    pytest.importorskip("cmaes")
    out = tmp_path / "controller.json"
    runner.invoke(
        app,
        [
            "optimize",
            str(EXAMPLE),
            "--task",
            str(TASK),
            "--attempts",
            "4",
            "--seed",
            "0",
            "--out",
            str(out),
        ],
    )

    from creature_lab.schema import ControllerSpec, CreatureSpec

    original = CreatureSpec.model_validate_json(EXAMPLE.read_text())
    spec = ControllerSpec.model_validate_json(out.read_text())
    optimized_joints = {m.joint for m in spec.motors}
    original_joints = {m.joint for m in original.motors}
    assert optimized_joints == original_joints  # same motors, only gait params tuned


def test_train_writes_a_controller_json_and_policy_bundle(tmp_path):
    pytest.importorskip("stable_baselines3")
    pytest.importorskip("pybullet")
    task_path = tmp_path / "short_task.json"
    task_path.write_text(
        json.dumps(
            {
                "name": "train_test",
                "duration": 0.2,
                "timestep": 1 / 60,
                "terrain": {"type": "plane", "friction": 1.0},
                "reward": {"forward_distance": 1.0},
            }
        )
    )
    out = tmp_path / "trained"
    result = runner.invoke(
        app,
        [
            "train",
            str(EXAMPLE),
            "--task",
            str(task_path),
            "--timesteps",
            "256",
            "--eval-episodes",
            "1",
            "--seed",
            "0",
            "--out",
            str(out),
            "--json",
        ],
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["timesteps"] == 256
    assert isinstance(payload["baseline_mean_return"], float)
    assert isinstance(payload["trained_mean_return"], float)

    assert (out / "policy.zip").exists()
    from creature_lab.schema import ControllerSpec

    spec = ControllerSpec.model_validate_json((out / "controller.json").read_text())
    assert spec.type.value == "policy"
    assert spec.policy_file == "policy.zip"

    # the saved bundle must actually be runnable via --controller <path>
    replay = runner.invoke(
        app,
        [
            "run",
            str(EXAMPLE),
            "--task",
            str(task_path),
            "--controller",
            str(out / "controller.json"),
            "--json",
        ],
    )
    assert replay.exit_code == 0, replay.stdout


def test_export_creates_gif(tmp_path):
    pytest.importorskip("pybullet")
    pytest.importorskip("imageio")
    runs_dir = tmp_path / "runs"
    run_result = runner.invoke(
        app, ["run", str(EXAMPLE), "--task", str(TASK), "--runs-dir", str(runs_dir)]
    )
    assert run_result.exit_code == 0, run_result.stdout

    [run_dir] = [path for path in runs_dir.iterdir() if path.is_dir()]
    out = tmp_path / "clip.gif"
    result = runner.invoke(
        app, ["export", str(run_dir), "--out", str(out), "--width", "64", "--height", "48"]
    )
    assert result.exit_code == 0, result.stdout
    assert out.exists() and out.stat().st_size > 0


def test_export_reads_terrain_from_the_saved_task(tmp_path):
    # CLI wiring smoke test: `export` reads task.json from the run dir and passes it
    # through to render_trace, so a non-flat-terrain run doesn't render a flat floor.
    pytest.importorskip("pybullet")
    pytest.importorskip("imageio")
    runs_dir = tmp_path / "runs"
    run_result = runner.invoke(
        app,
        [
            "zoo",
            "run",
            "quadruped",
            "--task",
            "slope_climb",
            "--runs-dir",
            str(runs_dir),
        ],
    )
    assert run_result.exit_code == 0, run_result.stdout

    [run_dir] = [path for path in runs_dir.iterdir() if path.is_dir()]
    assert (run_dir / "task.json").exists()
    out = tmp_path / "clip.gif"
    result = runner.invoke(
        app, ["export", str(run_dir), "--out", str(out), "--width", "64", "--height", "48"]
    )
    assert result.exit_code == 0, result.stdout
    assert out.exists() and out.stat().st_size > 0


def test_export_pack_bundles_a_run_into_a_shareable_directory(tmp_path):
    pytest.importorskip("pybullet")
    runs_dir = tmp_path / "runs"
    run_result = runner.invoke(
        app,
        [
            "run",
            str(EXAMPLE),
            "--task",
            str(TASK),
            "--controller",
            "cpg",
            "--runs-dir",
            str(runs_dir),
        ],
    )
    assert run_result.exit_code == 0, run_result.stdout
    [run_dir] = [path for path in runs_dir.iterdir() if path.is_dir()]

    out_dir = tmp_path / "pack"
    result = runner.invoke(app, ["export-pack", str(run_dir), "--out", str(out_dir)])
    assert result.exit_code == 0, result.stdout
    assert "exported" in result.stdout.lower()

    for name in ("creature.json", "task.json", "controller.json", "trace.json", "manifest.json"):
        assert (out_dir / name).exists()

    from creature_lab.schema import ControllerSpec

    controller = ControllerSpec.model_validate_json((out_dir / "controller.json").read_text())
    assert controller.type.value == "cpg"

    manifest = json.loads((out_dir / "manifest.json").read_text())
    assert manifest["warnings"] == []  # 'cpg' reconstructs exactly


def test_export_pack_defaults_out_dir_to_outputs_run_id_pack(tmp_path, monkeypatch):
    pytest.importorskip("pybullet")
    monkeypatch.chdir(tmp_path)
    runs_dir = tmp_path / "runs"
    run_result = runner.invoke(
        app, ["run", str(EXAMPLE), "--task", str(TASK), "--runs-dir", str(runs_dir), "--json"]
    )
    assert run_result.exit_code == 0, run_result.stdout
    run_id = json.loads(run_result.stdout)["run_id"]

    result = runner.invoke(app, ["export-pack", "latest", "--runs-dir", str(runs_dir)])
    assert result.exit_code == 0, result.stdout
    assert (tmp_path / "outputs" / f"{run_id}_pack" / "manifest.json").exists()


def test_export_pack_warns_when_the_run_predates_controller_tracking(tmp_path):
    pytest.importorskip("pybullet")
    from creature_lab.schema import CreatureSpec, EpisodeTrace

    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    run_dir = runs_dir / "legacy"
    run_dir.mkdir()
    creature = CreatureSpec.model_validate_json(EXAMPLE.read_text())
    (run_dir / "creature.json").write_text(creature.model_dump_json())
    trace = EpisodeTrace.model_validate(
        {
            "run_id": "legacy",
            "creature_name": creature.name,
            "task_name": "crawl_forward",
            "backend": "pybullet",
            "score": 1.0,
            "frames": [{"t": 0.0, "parts": {"torso": {"position": [0, 0, 0.2]}}}],
        }
    )
    (run_dir / "trace.json").write_text(trace.model_dump_json())

    result = runner.invoke(app, ["export-pack", str(run_dir), "--out", str(tmp_path / "pack")])
    assert result.exit_code == 0, result.stdout
    assert "predates controller tracking" in result.stdout


def test_export_pack_missing_run_is_a_clean_error():
    result = runner.invoke(app, ["export-pack", "does/not/exist"])
    assert result.exit_code == 2
    assert "no trace.json" in result.stdout.lower() or "not found" in result.stdout.lower()


def test_export_pack_json_output(tmp_path):
    pytest.importorskip("pybullet")
    runs_dir = tmp_path / "runs"
    run_result = runner.invoke(
        app, ["run", str(EXAMPLE), "--task", str(TASK), "--runs-dir", str(runs_dir)]
    )
    assert run_result.exit_code == 0, run_result.stdout
    [run_dir] = [path for path in runs_dir.iterdir() if path.is_dir()]

    result = runner.invoke(
        app, ["export-pack", str(run_dir), "--out", str(tmp_path / "pack"), "--json"]
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["out_dir"] == str(tmp_path / "pack")
    assert payload["pack_version"] == "2"
