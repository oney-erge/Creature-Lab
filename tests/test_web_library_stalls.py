"""The web app's run library: which saved runs count as stuck."""


def test_a_stand_still_policy_is_never_stuck():
    """The example pack's policy holds its pose: going nowhere is its walk, so its conditions are
    judged on falls alone, while a walking policy that stops at the foot of a ramp is stuck."""
    from types import SimpleNamespace

    import numpy as np
    from robot_helpers import synthetic_run

    from creature_lab.robots.analysis import analyze
    from creature_lab.web.library import _not_stuck_when_standing_is_normal

    def standing():
        run = synthetic_run()
        run.trunk_pos[:, 0] = 0.0
        return analyze(run)

    def stopped():
        run = synthetic_run()
        x = run.trunk_pos[:, 0]
        x[np.searchsorted(run.time, 5.0) :] = x[np.searchsorted(run.time, 5.0)]
        return analyze(run)

    walking = analyze(synthetic_run())
    entries = [
        SimpleNamespace(kind="baseline", policy="stand", analysis=standing()),
        SimpleNamespace(kind="grip", policy="stand", analysis=standing()),
        SimpleNamespace(kind="baseline", policy="walk", analysis=walking),
        SimpleNamespace(kind="terrain", policy="walk", analysis=stopped()),
    ]
    assert all(e.analysis.stalled for e in entries if e.policy == "stand")
    _not_stuck_when_standing_is_normal(entries)
    assert [e.analysis.stalled for e in entries] == [False, False, False, True]


def test_a_trial_walk_that_barely_moved_is_not_signed():
    """The example pack's trial walk read "moved -0.00 m", as if it had gone backwards."""
    from creature_lab.robots.packcheck import _signed_metres

    assert _signed_metres(-0.001) == "0.00"
    assert _signed_metres(0.004) == "0.00"
    assert _signed_metres(0.42) == "+0.42"
    assert _signed_metres(-0.1) == "-0.10"
