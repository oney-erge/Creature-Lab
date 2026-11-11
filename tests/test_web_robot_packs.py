"""The browser app and robot packs: add, list and remove a robot, and draw one made of shapes."""

from __future__ import annotations

import numpy as np
import pytest
from pack_helpers import copy_example, edit

pytest.importorskip("fastapi")
mujoco = pytest.importorskip("mujoco")
pytest.importorskip("onnxruntime")

from fastapi.testclient import TestClient  # noqa: E402

from creature_lab.robots.visual import primitive_arrays, primitive_geoms  # noqa: E402
from creature_lab.web import scene as scene_module  # noqa: E402
from creature_lab.web.scene import SceneData  # noqa: E402
from creature_lab.web.server import create_app  # noqa: E402

HEADERS = {"X-Creature-Lab": "1"}


@pytest.fixture
def pack_dir(tmp_path):
    return copy_example(tmp_path / "my-robot")


@pytest.fixture
def client(tmp_path, monkeypatch):
    """The app with an empty robot cache, so the list of added robots starts empty."""
    monkeypatch.setenv("CREATURE_LAB_ROBOTS_DIR", str(tmp_path / "cache"))
    scene_module.load_scene.cache_clear()
    app = create_app(tmp_path / "checkups", static_dir=tmp_path / "no-ui")
    yield TestClient(app, base_url="http://localhost:8080", headers=HEADERS)
    scene_module.load_scene.cache_clear()


def _robots(client) -> dict:
    return {r["key"]: r for r in client.get("/api/robots").json()["robots"]}


def test_built_in_robots_are_not_marked_as_added(client):
    robots = _robots(client)
    assert robots["unitree_g1"]["custom"] is False and robots["unitree_g1"]["folder"] is None
    assert robots["unitree_g1"]["shoveReferenceN"] == 150
    assert robots["microduck"]["shoveReferenceN"] == 4


def test_a_folder_is_checked_without_being_added(client, pack_dir):
    report = client.post("/api/robots/validate", json={"path": str(pack_dir)}).json()
    assert report["ok"] and report["title"] == "Stick biped" and report["key"] == "stick_biped"
    assert any(f["name"] == "joints" and f["value"] == "6" for f in report["facts"])
    assert "stick_biped" not in _robots(client)


def test_a_broken_folder_comes_back_with_every_problem(client, pack_dir):
    edit(pack_dir, "robot.toml", 'trunk = "trunk"', 'trunk = "torso"')
    report = client.post("/api/robots/validate", json={"path": str(pack_dir)}).json()
    assert not report["ok"]
    assert any("no body named 'torso'" in line for line in report["errors"])


@pytest.mark.parametrize("path", ["", "   ", "/no/such/folder"])
def test_a_path_that_is_not_there_is_a_422_with_words(client, path):
    response = client.post("/api/robots/validate", json={"path": path})
    assert response.status_code == 422
    assert response.json()["detail"]


def test_adding_makes_the_robot_appear_and_removing_forgets_it(client, pack_dir):
    added = client.post("/api/robots/add", json={"path": f'"{pack_dir}"'}).json()  # pasted quotes
    assert added["ok"] and added["added"]
    robot = _robots(client)["stick_biped"]
    assert robot["custom"] and robot["installed"] and not robot["hasResults"]
    assert robot["folder"] == str(pack_dir.resolve())
    assert robot["firstRunSeconds"] == 0
    assert robot["policies"][0]["key"] == "stand"

    assert client.delete("/api/robots/stick_biped").json() == {"removed": "stick_biped"}
    assert "stick_biped" not in _robots(client)
    assert (pack_dir / "robot.toml").is_file()  # the author's files are untouched


def test_a_broken_folder_is_not_added(client, pack_dir):
    edit(pack_dir, "robot.toml", "physics_dt = 0.005", "physics_dt = 0.007")
    added = client.post("/api/robots/add", json={"path": str(pack_dir)}).json()
    assert not added["ok"] and not added["added"]
    assert "stick_biped" not in _robots(client)


def test_a_built_in_robot_cannot_be_removed(client):
    assert client.delete("/api/robots/unitree_g1").status_code == 409
    assert client.delete("/api/robots/nope").status_code == 404


def test_adding_and_removing_need_the_custom_header(client, pack_dir):
    plain = TestClient(client.app, base_url="http://localhost:8080")
    assert plain.post("/api/robots/add", json={"path": str(pack_dir)}).status_code == 403
    assert plain.delete("/api/robots/stick_biped").status_code == 403


def test_an_added_robot_made_of_shapes_is_drawn_and_its_check_up_can_start(client, pack_dir):
    client.post("/api/robots/add", json={"path": str(pack_dir)})
    scene = client.get("/api/robots/stick_biped/scene").json()
    assert len(scene["geoms"]) == 7  # trunk, two thighs, two shins, two feet
    assert scene["bodyCount"] == 5
    payload = client.get(f"/api/robots/stick_biped/mesh/{scene['meshes'][0]['id']}").content
    assert len(payload) > 8
    assert client.get("/api/robots/stick_biped/runs").json() == {"runs": []}


def test_a_pack_thumbnail_is_kept_in_the_app_cache_not_in_the_authors_folder(
    client, pack_dir, tmp_path
):
    pytest.importorskip("PIL")
    client.post("/api/robots/add", json={"path": str(pack_dir)})
    response = client.get("/api/robots/stick_biped/thumbnail")
    if response.status_code == 503:
        pytest.skip("no OpenGL here")
    assert response.status_code == 200
    assert not (pack_dir / "thumb.jpg").exists()
    assert list((tmp_path / "cache" / "pack-thumbs").glob("stick_biped-*.jpg"))


# ---- drawing shapes -------------------------------------------------------------------------

SHAPES = """
<mujoco>
  <worldbody>
    <body name="trunk" pos="0 0 1">
      <freejoint/>
      <geom type="box" size="0.1 0.2 0.3" mass="1"/>
      <geom type="sphere" size="0.1" pos="0 0 0.5" mass="1"/>
      <geom type="capsule" size="0.05 0.2" pos="0.3 0 0" mass="1"/>
      <geom type="cylinder" size="0.05 0.2" pos="-0.3 0 0" mass="1"/>
      <geom type="ellipsoid" size="0.1 0.2 0.3" pos="0 0.4 0" mass="1"/>
      <geom type="box" size="1 1 1" group="3" mass="0.001"/>
      <geom type="box" size="1 1 1" rgba="0 0 0 0" mass="0.001"/>
    </body>
  </worldbody>
</mujoco>
"""


def _volume(vertices, faces) -> float:
    a, b, c = (vertices[faces[:, i]].astype(float) for i in range(3))
    return float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6)


def test_shapes_are_found_and_the_hidden_ones_skipped():
    model = mujoco.MjModel.from_xml_string(SHAPES)
    assert primitive_geoms(model) == [0, 1, 2, 3, 4]  # not the group-3 helper nor the clear one


@pytest.mark.parametrize(
    ("geom", "volume"),
    [
        (0, 0.2 * 0.4 * 0.6),  # box
        (1, 4 / 3 * np.pi * 0.1**3),  # sphere
        (2, np.pi * 0.05**2 * 0.4 + 4 / 3 * np.pi * 0.05**3),  # capsule: side plus two caps
        (3, np.pi * 0.05**2 * 0.4),  # cylinder
        (4, 4 / 3 * np.pi * 0.1 * 0.2 * 0.3),  # ellipsoid
    ],
)
def test_each_shape_encloses_its_volume_with_outward_faces(geom, volume):
    model = mujoco.MjModel.from_xml_string(SHAPES)
    vertices, faces = primitive_arrays(model, geom)
    assert faces.max() < len(vertices)
    # Tessellation loses a little volume; a flipped face would make it far smaller or negative.
    assert _volume(vertices, faces) == pytest.approx(volume, rel=0.08)


def test_a_model_with_meshes_never_draws_its_shapes():
    xml = """
    <mujoco>
      <asset><mesh name="tri" vertex="0 0 0  1 0 0  0 1 0  0 0 1"/></asset>
      <worldbody>
        <body pos="0 0 1">
          <freejoint/>
          <geom type="mesh" mesh="tri" group="2" mass="1"/>
          <geom type="capsule" size="0.05 0.2" group="0" mass="0.1"/>
        </body>
      </worldbody>
    </mujoco>"""
    scene = SceneData.from_model("x", mujoco.MjModel.from_xml_string(xml))
    assert len(scene.geoms) == 1 and len(scene.meshes) == 1


def test_a_model_of_shapes_gets_one_entry_per_shape():
    scene = SceneData.from_model("x", mujoco.MjModel.from_xml_string(SHAPES))
    assert len(scene.geoms) == 5 and scene.description()["bodyCount"] == 1
    assert len({g["mesh"] for g in scene.geoms}) == 5
