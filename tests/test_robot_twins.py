"""Twin runs: a shove saved under one policy is also run under the others, at the same moment."""

from __future__ import annotations

import pytest
from robot_helpers import saved_checkup, synthetic_run

from creature_lab.robots.checkup import add_twins
from creature_lab.web.library import Library

# The fake simulator replaces run_scenario in creature_lab.robots.api, which imports MuJoCo.
pytest.importorskip("mujoco")


def _fake_simulator(monkeypatch):
    calls = []

    def run_scenario(scenario):
        calls.append(scenario)
        return synthetic_run(
            policy=scenario.policy,
            push_n=scenario.push_n,
            push_at=scenario.push_at_s,
            title=scenario.title,
        )

    monkeypatch.setattr("creature_lab.robots.api.run_scenario", run_scenario)
    return calls


def test_a_shove_only_one_policy_saved_is_run_for_the_other(tmp_path, monkeypatch):
    root = tmp_path / "microduck-1"
    walk, getup = root / "alpha_walking", root / "velstand"
    saved_checkup(walk, "alpha_walking", stays_down=True)
    saved_checkup(getup, "velstand", stays_down=False)
    # The get-up policy also saved a shove at a moment the walk-only policy never saw.
    synthetic_run(policy="velstand", push_n=3.0, push_at=4.3, title="3 N shove").save(
        getup / "runs" / "shove_3N_late"
    )
    calls = _fake_simulator(monkeypatch)

    assert add_twins({"alpha_walking": walk, "velstand": getup}) == 1
    assert [(c.policy, c.push_n, c.push_at_s) for c in calls] == [("alpha_walking", 3.0, 4.3)]
    assert (walk / "runs" / "shove_3N_left_4.30s" / "robot_run.json").is_file()
    assert add_twins({"alpha_walking": walk, "velstand": getup}) == 0  # nothing left to add


def test_the_app_shows_the_twin_beside_the_run_it_was_made_for(tmp_path, monkeypatch):
    root = tmp_path / "checkups" / "microduck-1"
    walk, getup = root / "alpha_walking", root / "velstand"
    saved_checkup(walk, "alpha_walking", stays_down=True)
    saved_checkup(getup, "velstand", stays_down=False)
    synthetic_run(policy="velstand", push_n=3.0, push_at=4.3, title="3 N shove").save(
        getup / "runs" / "shove_3N_late"
    )
    _fake_simulator(monkeypatch)
    add_twins({"alpha_walking": walk, "velstand": getup})

    runs = Library(tmp_path / "checkups").runs("microduck")
    late = next(r for r in runs if r.policy == "velstand" and r.name == "shove_3N_late")
    twin = next(r for r in runs if r.id == late.pair)
    assert twin.policy == "alpha_walking" and twin.name == "shove_3N_left_4.30s"


def test_one_policy_needs_no_twins(tmp_path, monkeypatch):
    folder = tmp_path / "velstand"
    saved_checkup(folder, "velstand", stays_down=False)
    calls = _fake_simulator(monkeypatch)
    assert add_twins({"velstand": folder}) == 0 and calls == []


def test_with_three_policies_every_run_lists_both_twins_and_opens_on_the_one_that_differs(
    tmp_path, monkeypatch
):
    import dataclasses

    from creature_lab.robots.catalog import PolicyInfo, robot_info

    # A stand-in robot with a third policy (a robot pack can list as many as it likes).
    duck = robot_info("microduck")
    third = PolicyInfo("steady", "Steady policy", "A third policy.", "policies/steady.onnx")
    three = dataclasses.replace(duck, policies=(*duck.policies, third))
    for module in ("creature_lab.web.library", "creature_lab.robots.analysis"):
        monkeypatch.setattr(f"{module}.robot_info", lambda key: three)
    root = tmp_path / "checkups" / "microduck-1"
    # Two policies stay down after the shove; the third gets back up, so it is the comparison
    # worth opening first.
    for policy, stays_down in (("velstand", True), ("alpha_walking", True), ("steady", False)):
        saved_checkup(root / policy, policy, stays_down=stays_down)
    runs = Library(tmp_path / "checkups").runs("microduck")
    fall = next(r for r in runs if r.policy == "velstand" and r.name == "shove_3N_fall")
    policy_of = {r.id: r.policy for r in runs}
    assert [policy_of[i] for i in fall.pairs] == ["alpha_walking", "steady"]  # policy order
    assert policy_of[fall.pair] == "steady"
    assert fall.card()["pairs"] == fall.pairs
