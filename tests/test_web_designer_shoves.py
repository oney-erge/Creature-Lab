"""The designer's shove test, "Improve it" and export. Runs the real engine, so it asserts shape
and invariants rather than exact physics numbers."""

from __future__ import annotations

import json
import random

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from creature_lab.editor import presets  # noqa: E402
from creature_lab.schema import CreatureSpec  # noqa: E402
from creature_lab.web import shoves  # noqa: E402
from creature_lab.web.creatures import clean_params  # noqa: E402
from creature_lab.web.server import create_app  # noqa: E402

HEADERS = {"X-Creature-Lab": "1"}


@pytest.fixture
def client(tmp_path):
    return TestClient(
        create_app(tmp_path, static_dir=tmp_path / "no-ui"),
        base_url="http://localhost:8080",
        headers=HEADERS,
    )


def _build(client, preset: str = "quadruped", simulate: bool = True) -> dict:
    response = client.post(
        "/api/creatures/build",
        json={"preset": preset, "params": {}, "goal": "move_forward", "simulate": simulate},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _id(built: dict) -> str:
    return built["scene"]["robot"]


# ---- the rules, without a simulator --------------------------------------------------------


def test_staying_up_through_more_shoves_beats_walking_farther():
    assert shoves._better((3, 0.2), (2, 5.0))
    assert not shoves._better((2, 5.0), (3, 0.2))


def test_with_equal_shoves_only_a_clear_gain_in_distance_counts():
    assert not shoves._better((2, 1.04), (2, 1.0))
    assert shoves._better((2, 1.06), (2, 1.0))
    assert not shoves._better((2, 0.5), (2, 1.0))


def test_a_creature_that_falls_alone_ranks_below_one_that_stays_up():
    assert shoves._better((0, -9.0), (-1, 9.0))


@pytest.mark.parametrize(
    ("test", "limit"),
    [
        ({"baselineFell": True, "survivesUpTo": None}, -1),
        ({"baselineFell": False, "survivesUpTo": None}, 0),
        ({"baselineFell": False, "survivesUpTo": shoves.SHOVE_SPEEDS[0]}, 1),
        (
            {"baselineFell": False, "survivesUpTo": shoves.SHOVE_SPEEDS[-1]},
            len(shoves.SHOVE_SPEEDS),
        ),
    ],
)
def test_the_limit_counts_ladder_steps_from_the_gentlest(test, limit):
    assert shoves._limit(test) == limit


@pytest.mark.parametrize("preset", list(presets.CREATURE_PRESETS))
def test_a_nudge_moves_one_slider_within_its_range_and_step(preset):
    values = clean_params(preset, None)
    specs = {p.key: p for p in presets.CREATURE_PRESETS[preset].params}
    rng = random.Random(1)
    for _ in range(60):
        moved = shoves._nudge(preset, values, rng)
        changed = [k for k in values if moved[k] != values[k]]
        assert len(changed) <= 1
        for key in changed:
            spec = specs[key]
            assert spec.minimum <= moved[key] <= spec.maximum
            if spec.kind == "int":
                assert moved[key] == round(moved[key])


def test_the_force_figure_is_the_kick_spread_over_a_check_up_shove():
    creature = presets.generate_creature("quadruped", clean_params("quadruped", None))
    mass = shoves.mass_kg(creature)
    assert shoves._newtons(creature, 1.0) == pytest.approx(mass / shoves.SHOVE_FOR_S)


# ---- the engine ----------------------------------------------------------------------------


def test_the_shove_test_reports_each_strength_from_both_sides(client):
    result = client.post(f"/api/creatures/{_id(_build(client))}/shove").json()
    assert result["massKg"] > 0 and not result["baselineFell"]
    assert [lv["speed"] for lv in result["levels"]] == list(shoves.SHOVE_SPEEDS)
    for level in result["levels"]:
        assert set(level) == {"speed", "newtons", "left", "right"}
        assert level["newtons"] == pytest.approx(result["massKg"] * level["speed"] / 0.2, abs=0.1)
    # "Survives up to" is the last strength of an unbroken run of passes from the gentlest.
    passed = []
    for level in result["levels"]:
        if not (level["left"] and level["right"]):
            break
        passed.append(level["speed"])
    assert result["survivesUpTo"] == (passed[-1] if passed else None)


def test_a_robust_hexapod_survives_a_gentle_shove_and_a_resting_preview_can_be_shoved_too(client):
    result = client.post(f"/api/creatures/{_id(_build(client, 'hexapod', simulate=False))}/shove")
    levels = result.json()["levels"]
    assert levels[0]["left"] and levels[0]["right"]


def test_improving_offers_a_better_design_only_with_the_numbers_to_prove_it(client):
    built = _build(client, "humanoid")
    result = client.post(f"/api/creatures/{_id(built)}/improve", json={"tries": 10}).json()
    assert result["tried"] == 10
    assert result["before"]["levels"] and isinstance(result["improved"], bool)
    if not result["improved"]:
        assert result["after"] is None and result["changes"] == []
        return
    before, after = result["before"], result["after"]
    assert shoves._better(
        (shoves._limit(after), after["score"]), (shoves._limit(before), before["score"])
    )
    assert result["changes"], "an improvement says what it changed"
    for change in result["changes"]:
        assert change["from"] != change["to"] and change["label"]
    assert result["scene"]["geoms"] and result["run"]["simulated"]
    assert result["creature"]["params"] != built["creature"]["params"]


def test_the_number_of_tries_is_clamped(client):
    built = _build(client, "worm")
    result = client.post(f"/api/creatures/{_id(built)}/improve", json={"tries": 100000}).json()
    assert result["tried"] == shoves.MAX_TRIES


# ---- export --------------------------------------------------------------------------------


def test_a_creature_can_be_downloaded_as_json_a_mujoco_model_or_a_urdf(client):
    creature_id = _id(_build(client, simulate=False))
    as_json = client.get(f"/api/creatures/{creature_id}/export/json")
    assert as_json.status_code == 200
    assert 'filename="' in as_json.headers["content-disposition"]
    assert CreatureSpec.model_validate(json.loads(as_json.text)).parts
    mjcf = client.get(f"/api/creatures/{creature_id}/export/mjcf")
    assert "<mujoco model=" in mjcf.text
    urdf = client.get(f"/api/creatures/{creature_id}/export/urdf")
    assert "<robot name=" in urdf.text


def test_the_exported_model_loads_in_mujoco(client):
    mujoco = pytest.importorskip("mujoco")
    mjcf = client.get(f"/api/creatures/{_id(_build(client, simulate=False))}/export/mjcf").text
    assert mujoco.MjModel.from_xml_string(mjcf).nbody > 1


def test_unknown_formats_and_creatures_are_refused_with_the_right_status(client):
    creature_id = _id(_build(client, simulate=False))
    assert client.get(f"/api/creatures/{creature_id}/export/exe").status_code == 400
    assert client.get("/api/creatures/nope/export/json").status_code == 404
    assert client.post("/api/creatures/nope/shove").status_code == 404
    assert client.post("/api/creatures/nope/improve", json={}).status_code == 404


def test_shoving_and_improving_need_the_custom_header(tmp_path):
    plain = TestClient(
        create_app(tmp_path, static_dir=tmp_path / "no-ui"), base_url="http://localhost:8080"
    )
    assert plain.post("/api/creatures/x/shove").status_code == 403
    assert plain.post("/api/creatures/x/improve", json={}).status_code == 403
