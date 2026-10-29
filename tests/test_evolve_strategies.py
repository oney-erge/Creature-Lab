"""Tests for the Phase 7 evolution strategies and mutation operators."""

import random

import pytest

from creature_lab.evolve import (
    Evaluation,
    crossover,
    genetic,
    make_mutator,
    map_elites,
    mutate_controller,
    mutate_morphology,
)
from creature_lab.schema import CreatureSpec

SEED = {
    "name": "quad",
    "parts": [
        {"id": "torso", "shape": "box", "size": [0.4, 0.25, 0.08], "mass": 1.0},
        {"id": "leg_l", "shape": "capsule", "length": 0.22, "radius": 0.03, "mass": 0.15},
        {"id": "leg_r", "shape": "capsule", "length": 0.22, "radius": 0.03, "mass": 0.15},
    ],
    "joints": [
        {
            "id": "hip_l",
            "parent": "torso",
            "child": "leg_l",
            "type": "hinge",
            "anchor": [0, 0.16, 0],
            "axis": [0, 1, 0],
            "limit": [-1.0, 1.0],
        },
        {
            "id": "hip_r",
            "parent": "torso",
            "child": "leg_r",
            "type": "hinge",
            "anchor": [0, -0.16, 0],
            "axis": [0, 1, 0],
            "limit": [-1.0, 1.0],
        },
    ],
    "motors": [
        {"joint": "hip_l", "amplitude": 0.6, "frequency": 2.0, "phase": 0.0},
        {"joint": "hip_r", "amplitude": 0.6, "frequency": 2.0, "phase": 3.14},
    ],
}


def _seed() -> CreatureSpec:
    return CreatureSpec.model_validate(SEED)


def _amp(spec: CreatureSpec) -> float:
    return sum(m.amplitude for m in spec.motors)


def test_mutation_operators_return_valid_creatures():
    rng = random.Random(0)
    for _ in range(50):
        assert isinstance(mutate_controller(_seed(), rng), CreatureSpec)
        assert isinstance(mutate_morphology(_seed(), rng), CreatureSpec)


def test_morphology_mutation_keeps_motors_untouched_when_changing_body():
    # Repeated morphology mutations should never invalidate the spec.
    rng = random.Random(3)
    spec = _seed()
    for _ in range(30):
        spec = mutate_morphology(spec, rng)
        CreatureSpec.model_validate(spec.model_dump())


def test_crossover_produces_valid_creature():
    rng = random.Random(1)
    a = _seed()
    b = mutate_controller(mutate_controller(_seed(), rng), rng)
    child = crossover(a, b, rng)
    assert isinstance(child, CreatureSpec)
    # Same topology as parent a (parts/joints preserved).
    assert [p.id for p in child.parts] == [p.id for p in a.parts]
    assert [j.id for j in child.joints] == [j.id for j in a.joints]


def test_make_mutator_controller_only_never_changes_morphology():
    rng = random.Random(5)
    mutate_fn = make_mutator(body=False, controller=True)
    seed = _seed()
    for _ in range(40):
        out = mutate_fn(seed, rng)
        assert [(p.id, p.size, p.length) for p in out.parts] == [
            (p.id, p.size, p.length) for p in seed.parts
        ]


def test_genetic_improves_a_synthetic_objective():
    # Maximize total amplitude; GA should beat the seed.
    result = genetic(_seed(), _amp, attempts=40, rng=random.Random(2), population=6)
    assert result.best_score >= result.history[0].score
    assert _amp(result.best) == pytest.approx(result.best_score)


def test_genetic_is_deterministic():
    a = genetic(_seed(), _amp, attempts=20, rng=random.Random(9))
    b = genetic(_seed(), _amp, attempts=20, rng=random.Random(9))
    assert a.best == b.best
    assert a.best_score == b.best_score


def test_map_elites_fills_cells_and_assigns_them():
    # Features spread across cells: (avg frequency, fraction of positive-phase motors).
    def feature_evaluate(spec: CreatureSpec) -> Evaluation:
        freqs = [m.frequency for m in spec.motors]
        avg_freq = sum(freqs) / len(freqs)
        pos = sum(1 for m in spec.motors if m.phase > 0) / len(spec.motors)
        return Evaluation(score=_amp(spec), features=(avg_freq - 2.0, pos))

    result = map_elites(_seed(), feature_evaluate, attempts=60, rng=random.Random(4))
    assert result.archive  # at least one cell filled
    # Every history node has a cell, and the best equals the top archive cell.
    assert all(node.cell is not None for node in result.history)
    best_cell_score = max(entry["score"] for entry in result.archive.values())
    assert result.best_score == pytest.approx(best_cell_score)


def test_map_elites_cell_binning():
    from creature_lab.evolve import _cell_of

    bounds = ((-1.0, 2.0), (0.0, 1.0))
    assert _cell_of((-1.0, 0.0), (10, 5), bounds) == (0, 0)
    assert _cell_of((2.0, 1.0), (10, 5), bounds) == (9, 4)  # clamped to last bin
    assert _cell_of((0.5, 0.5), (10, 5), bounds) == (5, 2)


def test_cmaes_initializes_and_runs():
    pytest.importorskip("cmaes")
    from creature_lab.evolve import cmaes

    result = cmaes(_seed(), _amp, attempts=8, rng=random.Random(0))
    assert result.best_score >= result.history[0].score
    assert len(result.history) >= 1


def test_cmaes_requires_motors():
    pytest.importorskip("cmaes")
    from creature_lab.evolve import cmaes

    no_motors = CreatureSpec.model_validate(
        {"name": "still", "parts": [{"id": "a", "shape": "sphere", "radius": 0.1, "mass": 1.0}]}
    )
    with pytest.raises(ValueError, match="at least one motor"):
        cmaes(no_motors, _amp, attempts=4, rng=random.Random(0))


def test_evolve_map_elites_cli_writes_archive_and_lineage(tmp_path):
    pytest.importorskip("pybullet")
    from typer.testing import CliRunner

    from creature_lab.cli import app

    runner = CliRunner()
    runs_dir = tmp_path / "runs"
    result = runner.invoke(
        app,
        [
            "evolve",
            "examples/quadruped.json",
            "--task",
            "examples/crawl_forward.json",
            "--strategy",
            "map_elites",
            "--attempts",
            "4",
            "--runs-dir",
            str(runs_dir),
        ],
    )
    assert result.exit_code == 0, result.stdout
    run_dir = next(p for p in runs_dir.iterdir() if p.is_dir())
    assert (run_dir / "archive.json").exists()
    assert (run_dir / "lineage.json").exists()

    import json

    archive = json.loads((run_dir / "archive.json").read_text())
    assert archive  # at least the seed cell is filled
    first_entry = next(iter(archive.values()))
    assert "spec" in first_entry  # archive export needs this

    # lineage command renders the tree without crashing.
    tree = runner.invoke(app, ["lineage", str(run_dir)])
    assert tree.exit_code == 0, tree.stdout
    assert "candidate" in tree.stdout


def test_evolve_llm_strategy_cli_writes_rationale_into_lineage(tmp_path):
    pytest.importorskip("pybullet")
    from typer.testing import CliRunner

    from creature_lab.cli import app

    runner = CliRunner()
    runs_dir = tmp_path / "runs"
    result = runner.invoke(
        app,
        [
            "evolve",
            "examples/quadruped.json",
            "--task",
            "examples/crawl_forward.json",
            "--strategy",
            "llm",
            "--attempts",
            "5",
            "--seed",
            "0",
            "--runs-dir",
            str(runs_dir),
        ],
    )
    assert result.exit_code == 0, result.stdout
    run_dir = next(p for p in runs_dir.iterdir() if p.is_dir())

    import json

    lineage = json.loads((run_dir / "lineage.json").read_text())
    assert lineage["strategy"] == "tool_random"
    mutated_nodes = [node for node in lineage["nodes"] if node["index"] > 0]
    assert mutated_nodes
    assert all("note" in node and node["note"] for node in mutated_nodes)

    # Same seed must reproduce the same best score (offline policy, no network).
    repeat = runner.invoke(
        app,
        [
            "evolve",
            "examples/quadruped.json",
            "--task",
            "examples/crawl_forward.json",
            "--strategy",
            "llm",
            "--attempts",
            "5",
            "--seed",
            "0",
            "--runs-dir",
            str(tmp_path / "runs2"),
            "--json",
        ],
    )
    first_payload = json.loads(
        runner.invoke(
            app,
            [
                "report",
                str(run_dir),
                "--json",
            ],
        ).stdout
    )
    repeat_payload = json.loads(repeat.stdout)
    assert repeat_payload["best_score"] == pytest.approx(first_payload["score"])


def test_archive_show_and_export_cli(tmp_path):
    pytest.importorskip("pybullet")
    from typer.testing import CliRunner

    from creature_lab.cli import app

    runner = CliRunner()
    runs_dir = tmp_path / "runs"
    evolve_result = runner.invoke(
        app,
        [
            "evolve",
            "examples/quadruped.json",
            "--task",
            "examples/crawl_forward.json",
            "--strategy",
            "map_elites",
            "--attempts",
            "4",
            "--runs-dir",
            str(runs_dir),
        ],
    )
    assert evolve_result.exit_code == 0, evolve_result.stdout
    run_dir = next(p for p in runs_dir.iterdir() if p.is_dir())

    show_result = runner.invoke(app, ["archive", "show", str(run_dir)])
    assert show_result.exit_code == 0, show_result.stdout
    assert "filled cell" in show_result.stdout

    import json

    archive = json.loads((run_dir / "archive.json").read_text())
    cell_key = next(iter(archive))

    html_out = tmp_path / "archive.html"
    html_result = runner.invoke(app, ["archive", "show", str(run_dir), "--html", str(html_out)])
    assert html_result.exit_code == 0, html_result.stdout
    page = html_out.read_text()
    assert "archive-cell" in page
    assert "http://" not in page and "https://" not in page

    export_out = tmp_path / "elite.json"
    export_result = runner.invoke(
        app, ["archive", "export", str(run_dir), "--cell", cell_key, "--out", str(export_out)]
    )
    assert export_result.exit_code == 0, export_result.stdout
    from creature_lab.schema import CreatureSpec

    exported = CreatureSpec.model_validate_json(export_out.read_text())
    assert exported.parts


def test_archive_show_html_with_task_embeds_gifs_as_data_uris(tmp_path):
    pytest.importorskip("pybullet")
    pytest.importorskip("imageio")
    from typer.testing import CliRunner

    from creature_lab.cli import app

    runner = CliRunner()
    runs_dir = tmp_path / "runs"
    evolve_result = runner.invoke(
        app,
        [
            "evolve",
            "examples/quadruped.json",
            "--task",
            "examples/crawl_forward.json",
            "--strategy",
            "map_elites",
            "--attempts",
            "4",
            "--runs-dir",
            str(runs_dir),
        ],
    )
    assert evolve_result.exit_code == 0, evolve_result.stdout
    run_dir = next(p for p in runs_dir.iterdir() if p.is_dir())

    html_out = tmp_path / "archive.html"
    result = runner.invoke(
        app,
        [
            "archive",
            "show",
            str(run_dir),
            "--html",
            str(html_out),
            "--task",
            "examples/crawl_forward.json",
        ],
    )
    assert result.exit_code == 0, result.stdout
    page = html_out.read_text()
    assert "data:image/gif;base64," in page
    assert "http://" not in page and "https://" not in page
    # Self-contained: no sibling image directory or file should have been created.
    assert not any(p.is_dir() and p.name.endswith("_cells") for p in tmp_path.iterdir())


def test_archive_export_unknown_cell_errors(tmp_path):
    pytest.importorskip("pybullet")
    from typer.testing import CliRunner

    from creature_lab.cli import app

    runner = CliRunner()
    runs_dir = tmp_path / "runs"
    runner.invoke(
        app,
        [
            "evolve",
            "examples/quadruped.json",
            "--task",
            "examples/crawl_forward.json",
            "--strategy",
            "map_elites",
            "--attempts",
            "2",
            "--runs-dir",
            str(runs_dir),
        ],
    )
    run_dir = next(p for p in runs_dir.iterdir() if p.is_dir())

    result = runner.invoke(
        app,
        [
            "archive",
            "export",
            str(run_dir),
            "--cell",
            "99,99",
            "--out",
            str(tmp_path / "elite.json"),
        ],
    )
    assert result.exit_code == 2
    assert "unknown cell" in result.stdout

    top = runner.invoke(app, ["lineage", str(run_dir), "--best", "2"])
    assert top.exit_code == 0, top.stdout


def test_evolve_rejects_bad_strategy(tmp_path):
    from typer.testing import CliRunner

    from creature_lab.cli import app

    result = CliRunner().invoke(
        app,
        [
            "evolve",
            "examples/quadruped.json",
            "--task",
            "examples/crawl_forward.json",
            "--strategy",
            "bogus",
            "--runs-dir",
            str(tmp_path / "runs"),
        ],
    )
    assert result.exit_code == 2
    assert "strategy must be" in result.stdout
