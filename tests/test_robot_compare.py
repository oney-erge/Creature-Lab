"""Comparing check-ups and drawing the robustness card: saved results only, no simulator."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET

import pytest
from robot_helpers import saved_checkup
from typer.testing import CliRunner

from creature_lab.robots.card import card_svg, claim, markdown, write_card
from creature_lab.robots.cli import robots_app
from creature_lab.robots.compare import (
    CompareError,
    compare_checkups,
    compare_folders,
    find_checkup,
    write_json,
)

runner = CliRunner()


@pytest.fixture
def good(tmp_path):
    """A policy that falls at 3 N but always gets back up."""
    folder = tmp_path / "good"
    return saved_checkup(folder, "velstand", stays_down=False), folder


@pytest.fixture
def bad(tmp_path):
    """The same robot with a policy that stays on the floor after most 3 N shoves."""
    folder = tmp_path / "bad"
    return saved_checkup(folder, "alpha_walking", stays_down=True), folder


def test_identical_results_do_not_regress(good):
    checkup, _ = good

    comparison = compare_checkups(checkup, checkup)

    assert not comparison.regressed and not comparison.improvements
    assert comparison.summary().startswith("No change")
    assert comparison.skipped == []


def test_a_policy_that_stays_down_more_often_regressed(good, bad):
    comparison = compare_checkups(good[0], bad[0])

    assert comparison.regressed
    worse = {change.label for change in comparison.regressions}
    assert "3 N shove" in worse
    assert "1 N shove" not in worse  # 1 N: 7 up + 1 got up before, 8 up after, so better
    assert comparison.summary().startswith(("Regressed", "Mixed"))


def test_the_other_direction_is_mixed_because_getting_up_costs_something_at_1_n(good, bad):
    """The policy that gets up falls once at 1 N (cost 1) where the other never falls (cost 0)."""
    comparison = compare_checkups(bad[0], good[0])

    assert [c.label for c in comparison.improvements] == ["3 N shove"]
    assert [c.label for c in comparison.regressions] == ["1 N shove"]
    assert comparison.summary().startswith("Mixed")


def test_a_clear_improvement_reads_as_one(good):
    checkup, _ = good
    worse_row = checkup.shoves[1].model_copy(update={"stayed_up": 3, "got_up": 4, "stayed_down": 1})
    worse = checkup.model_copy(update={"shoves": [checkup.shoves[0], worse_row]})

    comparison = compare_checkups(worse, checkup)

    assert not comparison.regressed
    assert comparison.summary().startswith("Improved")


def test_a_shove_that_leaves_the_robot_down_costs_more_than_one_it_recovers_from(good):
    checkup, _ = good
    worse_row = checkup.shoves[1].model_copy(update={"stayed_up": 3, "got_up": 4, "stayed_down": 1})
    variant = checkup.model_copy(update={"shoves": [checkup.shoves[0], worse_row]})

    strict = compare_checkups(checkup, variant)
    lenient = compare_checkups(checkup, variant, tolerance=2)

    assert [c.label for c in strict.regressions] == ["3 N shove"]  # cost 5 -> 6
    assert not lenient.regressed  # within the tolerance


def test_a_test_that_passed_and_now_falls_is_a_regression(good):
    checkup, _ = good
    passed = checkup.conditions[0].model_copy(update={"passed": True})
    before = checkup.model_copy(update={"conditions": [passed]})
    after = checkup

    comparison = compare_checkups(before, after)

    assert [c.label for c in comparison.regressions] == ["Floor grip at 0.15× normal"]
    assert compare_checkups(after, before).improvements[0].kind == "condition"


def test_strengths_only_one_side_ran_are_listed_not_compared(good):
    checkup, _ = good
    shorter = checkup.model_copy(update={"shoves": checkup.shoves[:1]})

    comparison = compare_checkups(checkup, shorter)

    assert comparison.skipped == ["3 N shove"]
    assert not comparison.regressed


def test_different_robots_cannot_be_compared(tmp_path, good):
    other = saved_checkup(tmp_path / "g1", "motion", stays_down=True, robot="unitree_g1")
    with pytest.raises(CompareError, match="different robots"):
        compare_checkups(good[0], other)


def test_finding_a_checkup_folder(tmp_path, good, bad):
    _, good_folder = good
    root = tmp_path / "root"
    saved_checkup(root / "velstand", "velstand", stays_down=False)
    saved_checkup(root / "alpha_walking", "alpha_walking", stays_down=True)

    assert find_checkup(good_folder) == good_folder  # the folder itself
    assert find_checkup(root, "alpha_walking") == root / "alpha_walking"
    with pytest.raises(CompareError, match="several policies"):
        find_checkup(root)
    with pytest.raises(CompareError, match="no policy 'nope'"):
        find_checkup(root, "nope")
    with pytest.raises(CompareError, match="no check-up results"):
        find_checkup(tmp_path / "empty")


def test_comparing_folders_writes_json_and_markdown(good, bad, tmp_path):
    comparison = compare_folders(good[1], bad[1])

    path = write_json(comparison, tmp_path / "out" / "compare.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["regressed"] is True and payload["summary"].startswith(("Regressed", "Mixed"))
    assert payload["schema_id"] == "creature-lab.robot-compare/1"

    table = comparison.to_markdown()
    assert "| 3 N shove |" in table and "**worse**" in table
    assert "microduck" in table.splitlines()[0]


def test_the_compare_command_can_fail_a_build(good, bad, tmp_path):
    out = tmp_path / "report"
    args = ["compare", str(good[1]), str(bad[1]), "--json", str(out / "c.json")]
    args += ["--markdown", str(out / "c.md")]

    plain = runner.invoke(robots_app, args)
    strict = runner.invoke(robots_app, [*args, "--fail-on-regression"])
    clean = runner.invoke(
        robots_app, ["compare", str(good[1]), str(good[1]), "--fail-on-regression"]
    )

    assert plain.exit_code == 0, plain.stdout
    assert strict.exit_code == 1  # worse, and asked to fail
    assert clean.exit_code == 0 and "No change" in clean.stdout
    assert (out / "c.json").is_file() and "worse" in (out / "c.md").read_text(encoding="utf-8")


def test_the_compare_command_explains_a_missing_folder(tmp_path, good):
    result = runner.invoke(robots_app, ["compare", str(tmp_path / "nope"), str(good[1])])
    assert result.exit_code == 2 and "no check-up results" in result.stdout


# ---- the robustness card ------------------------------------------------------------------------


def test_the_card_is_valid_svg_that_says_what_it_measured(good):
    checkup, _ = good

    svg = card_svg(checkup)

    root = ET.fromstring(svg)  # well-formed
    text = " ".join(root.itertext())
    assert root.tag.endswith("svg")
    assert "Microduck" in text and "Walk + get-up policy" in text
    assert "simulation" in text.lower() and "Pollen Robotics" in text  # credit and honesty
    assert "1 N" in text and "3 N" in text
    assert svg.count("<rect") > 16  # a coloured cell per simulated shove


def test_the_claim_names_the_limits_and_the_counts(good, bad):
    standing = claim(good[0])
    floor = claim(bad[0])

    assert "Microduck" in standing and "Walk + get-up policy" in standing
    assert "fell even at 1 N" in standing
    assert "never stayed on the floor in any test" in standing  # it always gets back up
    assert "10 of 16 simulated shoves ended standing and 0 left it on the floor" in standing
    assert "never fell up to 1 N; never stayed on the floor up to 1 N" in floor
    assert "9 of 16 simulated shoves ended standing and 7 left it on the floor" in floor


def test_markdown_embeds_the_picture_only_when_asked(good):
    checkup, _ = good
    assert "![" not in markdown(checkup)
    assert "![Robustness card for microduck / velstand](card.svg)" in markdown(checkup, "card.svg")


def test_the_card_command_writes_the_svg_and_prints_the_claim(good, tmp_path):
    target = tmp_path / "cards" / "duck.svg"

    result = runner.invoke(robots_app, ["card", str(good[1]), "--out", str(target)])

    assert result.exit_code == 0, result.stdout
    assert target.is_file() and ET.parse(target).getroot().tag.endswith("svg")
    assert "Paste this into your README" in result.stdout
    assert "![Robustness card for microduck / velstand](duck.svg)" in result.stdout
    assert write_card(good[0], tmp_path / "again.svg").is_file()


def test_the_card_command_explains_a_missing_folder(tmp_path):
    result = runner.invoke(robots_app, ["card", str(tmp_path / "nope")])
    assert result.exit_code == 2 and "no check-up results" in result.stdout
