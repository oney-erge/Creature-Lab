"""The HTML report is built from saved check-ups alone, so it needs no simulator."""

import pytest
from robot_helpers import synthetic_run

from creature_lab.robots.analysis import analyze
from creature_lab.robots.checkup import Checkup, ConditionResult, ShoveRow
from creature_lab.robots.report import PolicyResult, limit_text, write_report


def _checkup(tmp_path, policy: str, *, stays_down: bool) -> PolicyResult:
    folder = tmp_path / policy
    baseline = synthetic_run(policy=policy)
    baseline.save(folder / "runs" / "baseline")
    fall = synthetic_run(
        policy=policy,
        fall_at=4.6,
        recover_at=None if stays_down else 5.6,
        push_n=3.0,
        pushed_outside=True,
    )
    fall.save(folder / "runs" / "shove_3N_fall")
    ice = synthetic_run(policy=policy, fall_at=4.5, slide=0.3, grip=0.15)
    ice.save(folder / "runs" / "grip_0.15")
    row = lambda force, up, got, down: ShoveRow(  # noqa: E731
        force_n=force,
        total=8,
        stayed_up=up,
        got_up=got,
        stayed_down=down,
        example_fall_run="shove_3N_fall" if down + got else None,
    )
    shoves = (
        [row(1, 8, 0, 0), row(3, 1, 0, 7)] if stays_down else [row(1, 7, 1, 0), row(3, 3, 5, 0)]
    )
    checkup = Checkup(
        robot="microduck",
        policy=policy,
        command=0.5,
        baseline=analyze(baseline),
        baseline_run="baseline",
        shoves=shoves,
        conditions=[
            ConditionResult(
                key="grip_0.15",
                label="Floor grip at 0.15× normal",
                passed=False,
                distance_m=0.3,
                relative_distance=0.2,
                analysis=analyze(ice),
                run="grip_0.15",
            )
        ],
    )
    return PolicyResult(checkup, folder)


def test_two_policy_report_tells_the_before_and_after_story(tmp_path):
    results = [
        _checkup(tmp_path, "velstand", stays_down=False),  # given out of order on purpose
        _checkup(tmp_path, "alpha_walking", stays_down=True),
    ]
    page = write_report(tmp_path, results, film="microduck-checkup.mp4").read_text("utf-8")
    assert "7 of 16 shoves leave it on the floor with the walk-only policy, 0 with the walk" in page
    assert page.index("Walk-only policy") < page.index("Walk + get-up policy")
    assert "Simulation, not hardware" in page
    assert "CC BY-NC-SA 4.0" in page
    assert 'src="microduck-checkup.mp4"' in page
    assert "outside the feet" in page  # the evidence behind a fall
    assert "creature-lab robots checkup microduck" in page
    assert "<script" not in page  # self-contained, no active content


def test_the_report_escapes_text(tmp_path):
    result = _checkup(tmp_path, "alpha_walking", stays_down=True)
    result.checkup.conditions[0].label = "<script>alert(1)</script>"
    page = write_report(tmp_path, [result]).read_text("utf-8")
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page


@pytest.mark.parametrize(
    ("limit", "expected"),
    [(None, "none (even 1 N)"), (1.0, "up to 1 N"), (3.0, "all tested (to 3 N)")],
)
def test_limit_text_says_what_was_tested(tmp_path, limit, expected):
    checkup = _checkup(tmp_path, "alpha_walking", stays_down=True).checkup
    assert limit_text(limit, checkup) == expected


def test_shove_limits_stop_at_the_first_failure(tmp_path):
    down = _checkup(tmp_path, "alpha_walking", stays_down=True).checkup
    up = _checkup(tmp_path, "velstand", stays_down=False).checkup
    assert down.never_falls_up_to_n == 1 and down.never_stays_down_up_to_n == 1
    assert up.never_falls_up_to_n is None and up.never_stays_down_up_to_n == 3
