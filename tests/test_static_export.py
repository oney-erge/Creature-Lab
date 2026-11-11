"""Writing the app and a recorded check-up as plain files for a web site."""

from __future__ import annotations

import json

import pytest
from robot_helpers import saved_checkup

pytest.importorskip("fastapi")
mujoco = pytest.importorskip("mujoco")

from fastapi.testclient import TestClient  # noqa: E402
from typer.testing import CliRunner  # noqa: E402

from creature_lab.cli import app as cli  # noqa: E402
from creature_lab.web import scene as scene_module  # noqa: E402
from creature_lab.web import server as server_module  # noqa: E402
from creature_lab.web.server import create_app  # noqa: E402
from creature_lab.web.static_export import STATIC_FLAG, ExportError, export_static  # noqa: E402

# A trunk and an arm drawn from tiny meshes: nq = 8, as in the app's own tests.
ROBOT_XML = """
<mujoco>
  <asset><mesh name="tri" vertex="0 0 0  1 0 0  0 1 0  0 0 1"/></asset>
  <worldbody>
    <body name="trunk" pos="0 0 0.5">
      <freejoint/>
      <geom type="mesh" mesh="tri" group="2" rgba="1 0.5 0 1" mass="1"/>
      <body name="arm" pos="0.2 0 0">
        <joint type="hinge" axis="0 1 0"/>
        <geom type="mesh" mesh="tri" group="2" rgba="1 1 1 1" mass="0.1"/>
      </body>
    </body>
  </worldbody>
</mujoco>
"""


@pytest.fixture
def results(tmp_path):
    """Saved check-ups for the G1 (BSD) and the Microduck (CC BY-NC-SA meshes)."""
    root = tmp_path / "checkups"
    saved_checkup(
        root / "unitree_g1-1" / "motion",
        "motion",
        stays_down=True,
        robot="unitree_g1",
        qpos_width=8,
    )
    saved_checkup(root / "microduck-1" / "velstand", "velstand", stays_down=False, qpos_width=8)
    return root


@pytest.fixture(autouse=True)
def installed(monkeypatch):
    monkeypatch.setattr(server_module, "is_installed", lambda key: True)
    monkeypatch.setattr(
        scene_module, "_load_model", lambda robot: mujoco.MjModel.from_xml_string(ROBOT_XML)
    )
    scene_module.load_scene.cache_clear()
    yield
    scene_module.load_scene.cache_clear()


def _json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_the_export_holds_the_page_and_every_file_it_will_ask_for(results, tmp_path):
    out = tmp_path / "demo"
    summary = export_static(results, out)
    assert summary["robots"] == ["unitree_g1"] and summary["files"] > 10

    page = (out / "index.html").read_text(encoding="utf-8")
    assert STATIC_FLAG in page
    assert '"/assets/' not in page and '"./assets/' in page  # works from /demo/ as well as /
    assert all((out / "assets" / name).is_file() for name in _assets(page))

    robots = _json(out / "data" / "robots.json")["robots"]
    assert [r["key"] for r in robots] == ["unitree_g1"]
    scene = _json(out / "data" / "robots" / "unitree_g1" / "scene.json")
    for mesh in scene["meshes"]:
        assert (out / "data" / "robots" / "unitree_g1" / "mesh" / f"{mesh['id']}.bin").is_file()
    runs = _json(out / "data" / "robots" / "unitree_g1" / "runs.json")["runs"]
    assert len(runs) >= 3
    for run in runs:
        folder = out / "data" / "runs" / run["id"]
        assert {p.name for p in folder.iterdir()} >= {"detail.json", "poses.bin", "overlay.bin"}


def _assets(page: str) -> list[str]:
    import re

    return re.findall(r'"\./assets/([^"]+)"', page)


def test_a_non_commercial_robot_is_left_out_unless_asked_for(results, tmp_path):
    plain = export_static(results, tmp_path / "a")
    assert plain["skipped"] == ["microduck"]
    both = export_static(results, tmp_path / "b", include_non_commercial=True)
    assert both["robots"] == ["microduck", "unitree_g1"] and both["skipped"] == []


def test_only_the_robots_named_are_exported(results, tmp_path):
    summary = export_static(
        results, tmp_path / "demo", robots=["microduck"], include_non_commercial=True
    )
    assert summary["robots"] == ["microduck"]
    with pytest.raises(ExportError, match="no robot to export"):
        export_static(results, tmp_path / "none", robots=["unitree_h1"])


def test_the_files_are_what_the_live_app_serves_and_say_nothing_about_this_machine(
    results, tmp_path
):
    out = tmp_path / "demo"
    export_static(results, out)
    live = TestClient(
        create_app(results, static_dir=tmp_path / "no-ui"),
        base_url="http://localhost:8080",
        headers={"X-Creature-Lab": "1"},
    )
    run = _json(out / "data" / "robots" / "unitree_g1" / "runs.json")["runs"][0]["id"]
    assert (out / "data" / "runs" / run / "poses.bin").read_bytes() == live.get(
        f"/api/runs/{run}/poses"
    ).content
    detail = _json(out / "data" / "runs" / run / "detail.json")
    assert detail["whatIfs"] == []  # a recording cannot run a new "what if"

    robot = _json(out / "data" / "robots.json")["robots"][0]
    assert robot["installed"] and not robot["custom"] and robot["introClip"] is None
    assert robot["checkup"]["folder"] == "" and robot["folder"] is None
    # Not a trace of where it was made.
    here = str(tmp_path).replace("\\", "/")
    for file in (out / "data").rglob("*.json"):
        text = file.read_text(encoding="utf-8").replace("\\\\", "/")
        assert here not in text, file


def test_a_folder_with_other_things_in_it_is_never_written_to(results, tmp_path):
    mine = tmp_path / "site"
    (mine / "data").mkdir(parents=True)
    (mine / "data" / "precious.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(ExportError, match="not empty"):
        export_static(results, mine)
    assert (mine / "data" / "precious.txt").read_text(encoding="utf-8") == "keep"
    file = tmp_path / "a-file"
    file.write_text("x", encoding="utf-8")
    with pytest.raises(ExportError, match="is a file"):
        export_static(results, file)


def test_an_export_can_be_repeated_and_replaces_only_itself(results, tmp_path):
    out = tmp_path / "demo"
    export_static(results, out)
    (out / "CNAME").write_text("example.org", encoding="utf-8")  # the person's own file, beside it
    (out / "data" / "stale.json").write_text("{}", encoding="utf-8")
    export_static(results, out)
    assert not (out / "data" / "stale.json").exists()  # its own old output goes
    assert (out / "CNAME").read_text(encoding="utf-8") == "example.org"  # theirs stays


def test_the_command_writes_the_export_and_says_what_it_left_out(results, tmp_path):
    out = tmp_path / "site"
    result = CliRunner().invoke(
        cli, ["app", "--checkups", str(results), "--export-static", str(out)]
    )
    assert result.exit_code == 0, result.output
    assert "Wrote" in result.output and "unitree_g1" in result.output
    assert "microduck" in result.output and "include-non-commercial" in result.output
    assert (out / "index.html").is_file()


def test_the_command_says_when_there_is_nothing_to_export(tmp_path):
    result = CliRunner().invoke(
        cli, ["app", "--checkups", str(tmp_path / "empty"), "--export-static", str(tmp_path / "o")]
    )
    assert result.exit_code == 1 and "no robot to export" in result.output
