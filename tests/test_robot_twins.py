"""Twin runs: a shove saved under one policy is also run under the others, at the same moment."""

from __future__ import annotations

from robot_helpers import saved_checkup, synthetic_run

from creature_lab.robots.checkup import add_twins
from creature_lab.web.library import Library


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
