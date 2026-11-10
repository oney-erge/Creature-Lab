"""The HTML report is built from saved check-ups alone, so it needs no simulator."""

import pytest
from robot_helpers import saved_checkup

from creature_lab.robots.report import PolicyResult, limit_text, write_report


def _checkup(tmp_path, policy: str, *, stays_down: bool) -> PolicyResult:
    folder = tmp_path / policy
    return PolicyResult(saved_checkup(folder, policy, stays_down=stays_down), folder)


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
