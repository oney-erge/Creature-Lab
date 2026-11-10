"""Designing a creature in the browser: shapes as meshes, clean parameters, and the API."""

import numpy as np
import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from creature_lab.schema.creature import PartSpec, ShapeType  # noqa: E402
from creature_lab.web import creatures  # noqa: E402
from creature_lab.web.creatures import CreatureError, clean_params, part_mesh  # noqa: E402
from creature_lab.web.server import create_app  # noqa: E402

HEADERS = {"X-Creature-Lab": "1"}


def _extent(part):
    vertices, faces = part_mesh(part)
    assert faces.max() < len(vertices) and faces.min() >= 0
    return np.ptp(vertices, axis=0)


def test_a_box_mesh_has_the_box_size():
    part = PartSpec(id="b", shape=ShapeType.BOX, mass=1, size=(0.4, 0.2, 0.1))
    assert _extent(part) == pytest.approx([0.4, 0.2, 0.1], abs=1e-6)


def test_a_sphere_mesh_spans_its_diameter():
    part = PartSpec(id="s", shape=ShapeType.SPHERE, mass=1, radius=0.05)
    assert _extent(part) == pytest.approx([0.1, 0.1, 0.1], abs=0.005)


def test_a_capsule_is_longer_than_its_cylinder_by_two_radii():
    part = PartSpec(id="c", shape=ShapeType.CAPSULE, mass=1, radius=0.03, length=0.2)
    assert _extent(part)[2] == pytest.approx(0.2 + 0.06, abs=1e-6)  # centred, long axis along Z


def test_a_cylinder_has_its_length_along_z():
    part = PartSpec(id="y", shape=ShapeType.CYLINDER, mass=1, radius=0.03, length=0.2)
    assert _extent(part)[2] == pytest.approx(0.2, abs=1e-6)


def test_parameters_are_clamped_to_their_range_and_integers_rounded():
    values = clean_params("worm", {"segments": 99, "radius": -5, "amplitude": "nope", "junk": 1})
    assert values["segments"] == 12.0 and values["radius"] == 0.01
    assert values["amplitude"] == 1.0  # not a number: the preset's own default
    assert "junk" not in values
    assert clean_params("worm", {"segments": 4.6})["segments"] == 5.0


def test_an_unknown_preset_is_refused():
    with pytest.raises(CreatureError):
        clean_params("dragon", {})


@pytest.fixture
def client(tmp_path):
    return TestClient(
        create_app(tmp_path, static_dir=tmp_path / "no-ui"),
        base_url="http://localhost:8080",
        headers=HEADERS,
    )


def test_the_catalog_lists_every_preset_with_its_sliders_and_the_goals(client):
    catalog = client.get("/api/creatures/presets").json()
    assert [p["key"] for p in catalog["presets"]] == ["quadruped", "hexapod", "worm", "humanoid"]
    leg = next(p for p in catalog["presets"][0]["params"] if p["key"] == "leg_length")
    assert (leg["min"], leg["max"], leg["integer"]) == (0.08, 0.6, False)
    assert {g["key"] for g in catalog["goals"]} >= {"move_forward", "reach_target"}


def test_building_a_creature_needs_a_physics_engine(client, monkeypatch):
    def missing():
        raise creatures.EngineMissing("needs sim")

    monkeypatch.setattr(creatures, "_backend", missing)
    response = client.post("/api/creatures/build", json={"preset": "quadruped"})
    assert response.status_code == 409 and "needs sim" in response.json()["detail"]


def test_bad_requests_are_400_and_unknown_ids_404(client):
    pytest.importorskip("pybullet")
    assert client.post("/api/creatures/build", json={"preset": "dragon"}).status_code == 400
    assert (
        client.post("/api/creatures/build", json={"preset": "worm", "goal": "fly"}).status_code
        == 400
    )
    assert client.get("/api/creatures/nope/scene").status_code == 404


def test_a_preview_and_a_run_come_back_as_meshes_and_poses(client):
    pytest.importorskip("pybullet")
    preview = client.post(
        "/api/creatures/build", json={"preset": "quadruped", "params": {"leg_length": 0.3}}
    ).json()
    assert preview["run"]["simulated"] is False and preview["run"]["frames"] == 1
    assert preview["creature"]["params"]["leg_length"] == 0.3

    run = client.post("/api/creatures/build", json={"preset": "quadruped", "simulate": True}).json()
    parts = len(run["scene"]["geoms"])
    cid = run["scene"]["robot"]
    assert run["run"]["simulated"] is True and run["run"]["frames"] > 100
    assert run["run"]["verdict"] and run["run"]["fps"] == pytest.approx(60.0)
    poses = client.get(f"/api/creatures/{cid}/poses").content
    assert len(poses) == run["run"]["frames"] * parts * creatures.POSE_STRIDE * 4
    overlay = client.get(f"/api/creatures/{cid}/overlay").content
    assert len(overlay) == run["run"]["frames"] * creatures.OVERLAY_STRIDE * 4
    mesh = client.get(f"/api/creatures/{cid}/mesh/0")
    assert mesh.status_code == 200 and len(mesh.content) > 8
    assert client.get(f"/api/creatures/{cid}/mesh/{parts}").status_code == 404


def test_only_the_last_few_builds_are_kept(client):
    pytest.importorskip("pybullet")
    first = client.post("/api/creatures/build", json={"preset": "worm"}).json()["scene"]["robot"]
    for _ in range(creatures._KEEP):
        client.post("/api/creatures/build", json={"preset": "worm"})
    assert client.get(f"/api/creatures/{first}/scene").status_code == 404
