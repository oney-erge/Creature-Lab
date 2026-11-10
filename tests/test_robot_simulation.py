"""End-to-end robot runs. Skipped unless the extra and the downloaded robot files are present.

Run ``creature-lab robots fetch microduck`` and ``... fetch unitree-g1`` once to enable them.
"""

import numpy as np
import pytest

pytest.importorskip("mujoco")
pytest.importorskip("onnxruntime")

from creature_lab.robots.analysis import analyze  # noqa: E402
from creature_lab.robots.api import run_scenario  # noqa: E402
from creature_lab.robots.fetch import is_installed  # noqa: E402
from creature_lab.robots.policies import G1WalkPolicy  # noqa: E402
from creature_lab.robots.rollout import _convex_hull  # noqa: E402
from creature_lab.robots.types import Scenario  # noqa: E402

needs_duck = pytest.mark.skipif(not is_installed("microduck"), reason="Microduck not downloaded")
needs_g1 = pytest.mark.skipif(not is_installed("unitree_g1"), reason="Unitree G1 not downloaded")


def test_g1_policy_matches_the_original_torchscript_outputs():
    """Outputs of Unitree's motion.pt (TorchScript) for the same three steps of state."""
    policy = G1WalkPolicy()
    observation = np.linspace(-1, 1, 47).astype(np.float32)
    expected = [
        [
            -1.803228,
            -0.067767,
            -0.724691,
            -0.300648,
            0.545249,
            0.287157,
            -3.100703,
            -2.600426,
            1.205328,
            0.268723,
            -1.561178,
            -0.082276,
        ],
        [
            -1.640622,
            -0.798002,
            -0.919764,
            -0.566582,
            -2.267157,
            0.29939,
            -3.636679,
            -0.829345,
            -0.566848,
            0.557286,
            -1.148392,
            0.541625,
        ],
        [
            -2.838342,
            -0.594734,
            -1.526459,
            -1.143887,
            -4.05784,
            1.298493,
            -2.866506,
            -1.263854,
            -0.303654,
            0.876956,
            -1.649495,
            0.506532,
        ],
    ]
    for step in expected:
        np.testing.assert_allclose(policy.act(observation), step, atol=1e-4)


def test_convex_hull_drops_interior_points():
    points = np.array([[0, 0], [2, 0], [2, 2], [0, 2], [1, 1], [1, 0.5]], dtype=float)
    hull = _convex_hull(points)
    assert len(hull) == 4
    assert {tuple(p) for p in hull} == {(0, 0), (2, 0), (2, 2), (0, 2)}


@needs_duck
def test_microduck_walks_and_the_run_repeats_exactly():
    scenario = Scenario(robot="microduck", policy="velstand", seconds=4.0)
    first, second = run_scenario(scenario), run_scenario(scenario)
    np.testing.assert_array_equal(first.qpos, second.qpos)
    result = analyze(first)
    assert result.outcome == "walked"
    assert result.distance_m > 0.3
    assert first.provenance["policy_sha256"]


@needs_duck
def test_microduck_on_near_ice_slips_and_falls():
    run = run_scenario(Scenario(robot="microduck", policy="velstand", grip=0.15))
    result = analyze(run)
    assert result.fell
    assert result.cause == "slipped"


@needs_duck
def test_a_big_shove_topples_the_walk_only_policy_and_it_stays_down():
    run = run_scenario(Scenario(robot="microduck", policy="alpha_walking", push_n=8.0))
    assert analyze(run).outcome == "fell"


@needs_g1
def test_g1_walks_forward_without_falling():
    run = run_scenario(Scenario(robot="unitree_g1", policy="motion", seconds=6.0))
    result = analyze(run)
    assert result.outcome == "walked"
    assert result.distance_m > 2.0


@needs_g1
def test_g1_falls_to_a_very_hard_shove():
    run = run_scenario(Scenario(robot="unitree_g1", policy="motion", push_n=300.0))
    result = analyze(run)
    assert result.fell and result.cause == "pushed"
