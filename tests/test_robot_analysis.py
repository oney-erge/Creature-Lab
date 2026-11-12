"""Failure analysis: outcome, timing, and which recorded signal explains a fall."""

import numpy as np
import pytest
from pydantic import ValidationError
from robot_helpers import synthetic_run

from creature_lab.robots.analysis import (
    _signed_distance_to_hull,
    analyze,
    balance_margin_cm,
)
from creature_lab.robots.types import RobotRun, Scenario


def test_a_clean_walk_is_a_walk():
    result = analyze(synthetic_run())
    assert result.outcome == "walked"
    assert not result.fell
    assert result.distance_m == pytest.approx(2.0, abs=0.05)
    assert result.cause is None


def test_a_shove_that_does_not_topple_it_is_reported_with_the_lean():
    result = analyze(synthetic_run(push_n=1.0))
    assert result.outcome == "walked"
    assert "1 N side shove" in result.verdict


def test_falling_and_staying_down_names_the_get_up_gap():
    run = synthetic_run(policy="alpha_walking", fall_at=4.6, push_n=3.0, pushed_outside=True)
    result = analyze(run)
    assert result.outcome == "fell"
    assert result.fall_time_s == pytest.approx(4.6, abs=0.03)
    assert "stayed down" in result.verdict
    assert "no get-up behaviour" in result.verdict


def test_falling_then_standing_up_again_is_recovery():
    run = synthetic_run(fall_at=4.6, recover_at=5.5, push_n=4.0, pushed_outside=True)
    result = analyze(run)
    assert result.outcome == "fell_and_got_up"
    assert result.recovered_time_s == pytest.approx(5.5, abs=0.03)
    assert "back on its feet" in result.verdict


def test_a_brief_flicker_upright_is_not_recovery():
    run = synthetic_run(fall_at=4.6)
    run.upright[260:270] = 1.0  # ten frames (0.2 s) upright, shorter than the half-second hold
    assert analyze(run).outcome == "fell"


def test_a_shove_that_moves_the_balance_point_outside_the_feet_is_blamed():
    run = synthetic_run(fall_at=4.6, push_n=3.0, pushed_outside=True)
    result = analyze(run)
    assert result.cause == "pushed"
    assert result.min_balance_margin_cm < -10
    assert "outside the feet" in result.cause_text
    assert any("outside" in item.value for item in result.evidence)


def test_sliding_feet_without_a_shove_are_blamed_on_grip():
    run = synthetic_run(fall_at=4.5, slide=0.3, grip=0.15)
    result = analyze(run)
    assert result.cause == "slipped"
    assert "0.15" in result.cause_text


def test_slipping_with_a_get_up_policy_mentions_that_it_could_get_up():
    result = analyze(synthetic_run(fall_at=4.5, slide=0.3, grip=0.15))
    assert "can get up on a normal floor" in result.verdict


def test_servos_at_their_limit_are_blamed_when_nothing_else_is():
    result = analyze(synthetic_run(fall_at=4.5, load=0.99))
    assert result.cause == "servos_saturated"
    assert result.saturated_fraction == pytest.approx(1.0)


def test_an_unexplained_fall_is_called_unclear_not_guessed():
    result = analyze(synthetic_run(fall_at=4.5))
    assert result.cause == "unclear"
    assert "do not point to one cause" in result.cause_text


def test_a_shove_long_before_the_fall_is_not_blamed():
    result = analyze(synthetic_run(fall_at=9.0, push_n=3.0, push_at=2.0))
    assert result.cause != "pushed"


UNIT_SQUARE = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]])


@pytest.mark.parametrize(
    ("point", "expected"),
    [((0.5, 0.5), 0.5), ((0.9, 0.5), 0.1), ((1.5, 0.5), -0.5), ((2.0, 2.0), -(2**0.5))],
)
def test_signed_distance_to_a_square(point, expected):
    assert _signed_distance_to_hull(np.array(point), UNIT_SQUARE) == pytest.approx(expected)


def test_signed_distance_degenerate_outlines_are_never_inside():
    one = np.array([[0.0, 0.0]])
    two = np.array([[0.0, 0.0], [1.0, 0.0]])
    assert _signed_distance_to_hull(np.array([0.0, 1.0]), one) == pytest.approx(-1.0)
    assert _signed_distance_to_hull(np.array([0.5, 0.2]), two) == pytest.approx(-0.2)


def test_balance_margin_is_nan_when_no_foot_touches():
    run = synthetic_run()
    run.support[:] = np.nan
    assert np.isnan(balance_margin_cm(run)).all()


def test_balance_margin_leads_with_the_velocity():
    run = synthetic_run()
    run.com_vel[:, 0] = 5.0  # moving fast: the extrapolated point is far ahead of the feet
    assert balance_margin_cm(run).max() < 0


def test_scenario_rejects_nonsense():
    with pytest.raises(ValidationError):
        Scenario(robot="microduck", policy="velstand", push_n=-1)
    with pytest.raises(ValidationError):
        Scenario(robot="microduck", policy="velstand", surprise=1)  # unknown field


def test_scenario_digest_is_stable_and_sensitive():
    a = Scenario(robot="microduck", policy="velstand", push_n=3.0)
    assert a.digest() == Scenario(robot="microduck", policy="velstand", push_n=3.0).digest()
    assert a.digest() != Scenario(robot="microduck", policy="velstand", push_n=3.5).digest()


def test_a_saved_run_reads_back_identically(tmp_path):
    run = synthetic_run(fall_at=4.6, push_n=3.0, pushed_outside=True)
    run.save(tmp_path / "run")
    loaded = RobotRun.read(tmp_path / "run")
    assert loaded.scenario == run.scenario
    assert loaded.joint_names == run.joint_names
    for name in RobotRun.ARRAYS:
        np.testing.assert_array_equal(getattr(loaded, name), getattr(run, name))
    assert analyze(loaded) == analyze(run)


def _stalled_at(run, stop_s: float):
    """The same walk, standing still from ``stop_s`` on (a robot pressing against an obstacle)."""
    x = run.trunk_pos[:, 0]
    stop = int(np.searchsorted(run.time, stop_s))
    x[stop:] = x[stop]
    run.com[:, 0] = x
    return run


def test_a_walk_that_stops_making_headway_is_stalled():
    """The G1 at the foot of a 24-degree ramp read "Walked 0.7 m up a ramp" and passed."""
    result = analyze(_stalled_at(synthetic_run(), 5.0))
    assert result.outcome == "walked" and not result.fell
    assert result.stalled
    assert result.verdict == "Stopped making headway after 1.0 m, still on its feet."


def test_a_walk_that_only_slows_down_is_not_stalled():
    run = synthetic_run()
    slow = run.time >= 8.0
    run.trunk_pos[slow, 0] = run.trunk_pos[slow, 0][0] + 0.12 * (run.time[slow] - 8.0)  # 60% pace
    assert not analyze(run).stalled
    assert not analyze(synthetic_run()).stalled


def test_a_stall_on_a_course_says_where_it_stopped():
    from creature_lab.robots.terrain import Terrain

    for start_m, stop_s, where in (
        (1.0, 4.5, "at the foot of the 24° ramp"),
        (0.3, 5.0, "partway up the 24° ramp"),
    ):
        run = _stalled_at(synthetic_run(), stop_s)
        terrain = Terrain(kind="ramp", level=24.0, unit_m=0.05, start_m=start_m)
        run = RobotRun(
            **{**run.__dict__, "scenario": run.scenario.model_copy(update={"terrain": terrain})}
        )
        result = analyze(run)
        assert result.stalled
        assert result.verdict.startswith(f"Stopped {where} after "), result.verdict


def test_a_shove_is_never_called_stalled():
    # A shove's question is whether it stayed up; how far it got is not the test.
    assert not analyze(_stalled_at(synthetic_run(push_n=1.0), 5.0)).stalled
