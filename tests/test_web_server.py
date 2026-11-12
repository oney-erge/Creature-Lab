"""The browser app's API: listing, run data, security guards, jobs and the static UI."""

import struct
import time
from types import SimpleNamespace

import numpy as np
import pytest
from robot_helpers import saved_checkup

pytest.importorskip("fastapi")
mujoco = pytest.importorskip("mujoco")

from fastapi.testclient import TestClient  # noqa: E402

from creature_lab.web import scene as scene_module  # noqa: E402
from creature_lab.web import server as server_module  # noqa: E402
from creature_lab.web.jobs import Jobs  # noqa: E402
from creature_lab.web.scene import OVERLAY_STRIDE, POSE_STRIDE  # noqa: E402
from creature_lab.web.server import create_app  # noqa: E402
from creature_lab.web.thumbs import Thumbnails  # noqa: E402

# A trunk, a collision twin that must not be drawn, and an arm: nq = 8.
ROBOT_XML = """
<mujoco>
  <asset><mesh name="tri" vertex="0 0 0  1 0 0  0 1 0  0 0 1"/></asset>
  <worldbody>
    <body name="trunk" pos="0 0 0.5">
      <freejoint/>
      <geom type="mesh" mesh="tri" group="2" rgba="1 0.5 0 1" mass="1"/>
      <geom type="mesh" mesh="tri" group="3" rgba="0 0 1 1" mass="0.001"/>
      <body name="arm" pos="0.2 0 0">
        <joint type="hinge" axis="0 1 0"/>
        <geom type="mesh" mesh="tri" group="2" rgba="1 1 1 1" mass="0.1"/>
      </body>
    </body>
  </worldbody>
</mujoco>
"""
HEADERS = {"X-Creature-Lab": "1"}


@pytest.fixture
def results(tmp_path):
    """A check-up folder like the CLI writes, with two policies of the Microduck."""
    root = tmp_path / "checkup"
    folder = root / "microduck-20261030"
    saved_checkup(folder / "alpha_walking", "alpha_walking", stays_down=True, qpos_width=8)
    saved_checkup(folder / "velstand", "velstand", stays_down=False, qpos_width=8)
    return root


@pytest.fixture
def installed(monkeypatch):
    """Pretend the robots are downloaded and give the scene loader a tiny stand-in model."""
    monkeypatch.setattr(server_module, "is_installed", lambda key: True)
    monkeypatch.setattr(
        scene_module, "_load_model", lambda robot: mujoco.MjModel.from_xml_string(ROBOT_XML)
    )
    scene_module.load_scene.cache_clear()
    yield
    scene_module.load_scene.cache_clear()


def _client(app, **kwargs) -> TestClient:
    kwargs.setdefault("base_url", "http://localhost:8080")
    return TestClient(app, **kwargs)


@pytest.fixture
def client(results, installed):
    app = create_app(results, static_dir=results / "no-ui")
    return _client(app, headers=HEADERS)


# ---- listing -------------------------------------------------------------------------------


def test_health_names_the_service(client):
    assert client.get("/api/health").json()["service"] == "creature-lab"


def test_each_robot_says_how_long_a_first_check_up_takes(client):
    robots = {r["key"]: r for r in client.get("/api/robots").json()["robots"]}
    # The app opens on the quickest one, so every robot needs a time and the G1 must be quickest.
    assert all(r["firstRunSeconds"] > 0 for r in robots.values())
    assert robots["unitree_g1"]["firstRunSeconds"] < robots["microduck"]["firstRunSeconds"]


def test_a_bundled_intro_clip_is_offered_only_when_it_exists(results, installed, tmp_path):
    static = tmp_path / "ui"
    (static / "clips").mkdir(parents=True)
    (static / "clips" / "unitree_g1.webp").write_bytes(b"RIFF....WEBP")
    client = _client(create_app(results, static_dir=static), headers=HEADERS)

    robots = {r["key"]: r for r in client.get("/api/robots").json()["robots"]}

    assert robots["unitree_g1"]["introClip"] == "/clips/unitree_g1.webp"
    assert robots["microduck"]["introClip"] is None  # CC BY-NC-SA media is never bundled
    # And the clip really is served from the same place as the app.
    assert client.get("/clips/unitree_g1.webp").status_code == 200


def test_a_robot_that_is_not_downloaded_has_a_picture_when_one_ships(results, installed, tmp_path):
    """Every card on a first visit was a blank tile: a robot is drawn only after its download."""
    static = tmp_path / "ui"
    (static / "previews").mkdir(parents=True)
    (static / "previews" / "unitree_g1.jpg").write_bytes(b"JFIF....")
    client = _client(create_app(results, static_dir=static), headers=HEADERS)

    robots = {r["key"]: r for r in client.get("/api/robots").json()["robots"]}

    assert robots["unitree_g1"]["preview"] == "/previews/unitree_g1.jpg"
    assert robots["microduck"]["preview"] is None  # CC BY-NC-SA meshes: no picture ships
    assert client.get("/previews/unitree_g1.jpg").status_code == 200


def test_robots_lists_every_robot_with_the_newest_check_up(client):
    data = client.get("/api/robots").json()
    keys = [r["key"] for r in data["robots"]]
    assert keys == ["microduck", "unitree_g1", "unitree_g1_29dof", "unitree_h1", "unitree_h1_2"]
    duck = data["robots"][0]
    assert duck["installed"] and duck["hasResults"]
    assert duck["nonCommercial"] and "CC BY-NC-SA 4.0" in duck["licenseNotice"]
    assert not data["robots"][1]["hasResults"] and data["robots"][1]["checkup"] is None
    # The policy that stays down is listed first, so the page reads before/after.
    policies = duck["checkup"]["policies"]
    assert [p["policy"] for p in policies] == ["alpha_walking", "velstand"]
    first, second = policies
    assert (first["neverFallsUpTo"], first["neverStaysDownUpTo"]) == (1, 1)
    assert (second["neverFallsUpTo"], second["neverStaysDownUpTo"]) == (None, 3)
    row = first["shoves"][1]
    assert (row["force"], row["stayedDown"]) == (3, 7)
    assert row["fallRun"] and row["okRun"] is None


def test_api_responses_are_not_cached(client):
    assert client.get("/api/robots").headers["cache-control"] == "no-store"


def test_runs_come_baseline_first_then_shoves_then_conditions(client):
    runs = client.get("/api/robots/microduck/runs").json()["runs"]
    kinds = [r["kind"] for r in runs]
    assert kinds == sorted(kinds, key=["baseline", "shove", "grip"].index)
    assert runs[0]["kind"] == "baseline" and runs[0]["policy"] == "alpha_walking"
    down = next(r for r in runs if r["title"] == "3 N shove" and r["policy"] == "alpha_walking")
    assert down["outcome"] == "fell" and down["outcomeText"] == "Stayed down"
    up = next(r for r in runs if r["title"] == "3 N shove" and r["policy"] == "velstand")
    assert up["outcome"] == "fell_and_got_up" and up["outcomeText"].startswith("Back up in")


def test_run_cards_say_how_hard_the_shove_was(client):
    runs = client.get("/api/robots/microduck/runs").json()["runs"]
    baseline = next(r for r in runs if r["kind"] == "baseline")
    shove = next(r for r in runs if r["title"] == "3 N shove")
    assert (baseline["pushN"], shove["pushN"]) == (0, 3)


def test_a_robot_without_results_has_no_runs(client):
    assert client.get("/api/robots/unitree_g1/runs").json() == {"runs": []}


def test_unknown_robot_and_run_are_404(client):
    assert client.get("/api/robots/walle/runs").status_code == 404
    assert client.get("/api/runs/does-not-exist").status_code == 404
    assert client.get("/api/robots/walle/scene").status_code == 404


def test_run_detail_has_the_story_and_the_numbers(client):
    runs = client.get("/api/robots/microduck/runs").json()["runs"]
    fall = next(r for r in runs if r["title"] == "3 N shove" and r["policy"] == "alpha_walking")
    detail = client.get(f"/api/runs/{fall['id']}").json()
    assert detail["frames"] == 500 and detail["fps"] == 50 and detail["duration"] == 10.0
    assert detail["cause"] == "pushed" and "outside the feet" in detail["causeText"]
    assert detail["events"]["pushAt"] == 4.0 and detail["events"]["pushN"] == 3.0
    assert detail["events"]["fallAt"] == pytest.approx(4.6, abs=0.03)
    assert len(detail["tilt"]) <= 260 and max(detail["tilt"]) > 60
    assert {e["label"] for e in detail["evidence"]} >= {"Balance point vs feet"}
    assert "CC BY-NC-SA 4.0" in detail["credit"]


# ---- 3D data -------------------------------------------------------------------------------


def test_scene_describes_only_the_visual_meshes(client):
    scene = client.get("/api/robots/microduck/scene").json()
    assert scene["bodyCount"] == 2 and scene["poseStride"] == POSE_STRIDE
    assert len(scene["geoms"]) == 2  # trunk and arm; the collision twin is left out
    assert scene["geoms"][0]["rgba"][:3] == pytest.approx([1.0, 0.5, 0.0])
    assert [g["body"] for g in scene["geoms"]] == [0, 1]
    assert scene["meshes"][0]["vertices"] >= 4


def test_mesh_payload_has_a_header_then_vertices_then_faces(client):
    scene = client.get("/api/robots/microduck/scene").json()
    mesh = scene["meshes"][0]
    response = client.get(f"/api/robots/microduck/mesh/{mesh['id']}")
    vertices, faces = struct.unpack("<II", response.content[:8])
    assert (vertices, faces) == (mesh["vertices"], mesh["faces"])
    assert len(response.content) == 8 + vertices * 12 + faces * 12
    assert "immutable" in response.headers["cache-control"]
    assert client.get("/api/robots/microduck/mesh/999").status_code == 404


def test_poses_put_each_body_where_kinematics_says(client):
    runs = client.get("/api/robots/microduck/runs").json()["runs"]
    run_id = runs[0]["id"]
    raw = client.get(f"/api/runs/{run_id}/poses").content
    poses = np.frombuffer(raw, dtype="<f4").reshape(500, 2, POSE_STRIDE)
    assert poses[0, 0, :3] == pytest.approx([0.0, 0.0, 0.12])  # the trunk, from the run's qpos
    assert poses[0, 1, :3] == pytest.approx([0.2, 0.0, 0.12])  # the arm, 0.2 m ahead of it
    assert poses[0, 0, 3:] == pytest.approx([1, 0, 0, 0])


def test_overlay_carries_support_heading_push_and_trunk(client):
    runs = client.get("/api/robots/microduck/runs").json()["runs"]
    fall = next(r for r in runs if r["title"] == "3 N shove" and r["policy"] == "alpha_walking")
    raw = client.get(f"/api/runs/{fall['id']}/overlay").content
    overlay = np.frombuffer(raw, dtype="<f4").reshape(500, OVERLAY_STRIDE)
    assert not np.isnan(overlay[0, :8]).any()  # a 4-corner outline, then NaN padding
    assert np.isnan(overlay[0, 8:16]).all()
    assert overlay[204, 18] == 3.0  # the shove force while it acts (t = 4.10 s)
    assert overlay[0, 18] == 0.0
    assert overlay[100, 19:22] == pytest.approx([0.4, 0.0, 0.12], abs=0.01)


def test_robot_scene_needs_the_download(results, monkeypatch):
    monkeypatch.setattr(server_module, "is_installed", lambda key: False)
    client = _client(create_app(results, static_dir=results / "no-ui"), headers=HEADERS)
    assert client.get("/api/robots/microduck/scene").status_code == 409
    assert not client.get("/api/robots").json()["robots"][0]["installed"]


# ---- thumbnails ----------------------------------------------------------------------------


def test_thumbnails_are_rendered_once_then_cached_beside_the_run(results, installed):
    calls = []

    def render(folder, at):
        calls.append((folder.name, at))
        return b"\xff\xd8fake-jpeg"

    client = _client(
        create_app(results, static_dir=results / "no-ui", thumbnails=Thumbnails(render)),
        headers=HEADERS,
    )
    runs = client.get("/api/robots/microduck/runs").json()["runs"]
    recovered = next(r for r in runs if r["outcome"] == "fell_and_got_up")
    first = client.get(f"/api/runs/{recovered['id']}/thumbnail")
    again = client.get(f"/api/runs/{recovered['id']}/thumbnail")
    assert first.content == again.content == b"\xff\xd8fake-jpeg"
    assert first.headers["content-type"] == "image/jpeg"
    assert len(calls) == 1  # the second request came from the cache file
    assert calls[0][1] == pytest.approx(6.0, abs=0.05)  # 0.4 s after it got back up (5.6 s)


def test_a_machine_that_cannot_render_gets_a_clean_503(results, installed):
    def broken(folder, at):
        raise RuntimeError("no OpenGL")

    client = _client(
        create_app(results, static_dir=results / "no-ui", thumbnails=Thumbnails(broken)),
        headers=HEADERS,
    )
    run_id = client.get("/api/robots/microduck/runs").json()["runs"][0]["id"]
    response = client.get(f"/api/runs/{run_id}/thumbnail")
    assert response.status_code == 503 and "no OpenGL" in response.json()["detail"]


# ---- security ------------------------------------------------------------------------------


def test_requests_for_other_host_names_are_refused(results, installed):
    """DNS rebinding: a web page on another site reaching this local server by its own name."""
    app = create_app(results, static_dir=results / "no-ui")
    assert _client(app, base_url="http://evil.example").get("/api/robots").status_code == 403
    assert _client(app, base_url="http://127.0.0.1:8080").get("/api/health").status_code == 200
    assert _client(app, base_url="http://localhost").get("/api/health").status_code == 200


def test_changing_requests_need_the_custom_header(results, installed):
    """A form on another site cannot add this header without a CORS preflight we never allow."""
    app = create_app(results, static_dir=results / "no-ui")
    plain = _client(app)
    assert plain.post("/api/robots/microduck/checkup").status_code == 403
    assert (
        plain.post("/api/robots/microduck/download", json={"accept_license": True}).status_code
        == 403
    )
    assert plain.get("/api/robots").status_code == 200  # reading needs no header


def test_the_api_has_no_cors_headers(client):
    response = client.get("/api/robots", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in response.headers


# ---- jobs ----------------------------------------------------------------------------------


def _wait(client, job_id, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["state"] != "running":
            return job
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def test_download_needs_the_license_to_be_accepted(results, installed):
    fetched = []
    jobs = Jobs(results, fetch=lambda key, progress=None: fetched.append(key))
    client = _client(create_app(results, static_dir=results / "no-ui", jobs=jobs), headers=HEADERS)
    assert client.post("/api/robots/microduck/download", json={}).status_code == 400
    assert (
        client.post("/api/robots/microduck/download", json={"accept_license": False}).status_code
        == 400
    )
    assert fetched == []
    started = client.post("/api/robots/microduck/download", json={"accept_license": True}).json()
    assert _wait(client, started["id"])["state"] == "done" and fetched == ["microduck"]


def test_download_progress_and_failure_are_reported(results, installed):
    from creature_lab.robots.fetch import FetchError

    def fetch(key, progress=None):
        progress("[2/4] assets/foo.stl")
        raise FetchError("could not download https://example.test/foo.stl")

    jobs = Jobs(results, fetch=fetch)
    client = _client(create_app(results, static_dir=results / "no-ui", jobs=jobs), headers=HEADERS)
    job_id = client.post("/api/robots/unitree_g1/download", json={"accept_license": True}).json()[
        "id"
    ]
    job = _wait(client, job_id)
    assert job["state"] == "failed" and "could not download" in job["error"]
    assert job["progress"] == pytest.approx(0.5)


def test_checkup_job_reports_progress_from_the_cli_output(results, installed):
    lines = ["Microduck check-up"] + [f"  step {i}" for i in range(1, 13)] + ["Report: x"]

    def launcher(args):
        out = args[args.index("--out") + 1]
        from pathlib import Path

        Path(out).mkdir(parents=True)
        (Path(out) / "report.html").write_text("<html></html>", encoding="utf-8")
        return SimpleNamespace(stdout=iter(line + "\n" for line in lines), wait=lambda: 0)

    jobs = Jobs(results, launcher=launcher)
    client = _client(create_app(results, static_dir=results / "no-ui", jobs=jobs), headers=HEADERS)
    started = client.post("/api/robots/unitree_g1/checkup").json()
    assert started["kind"] == "checkup" and started["output"].startswith("unitree_g1-")
    job = _wait(client, started["id"])
    assert job["state"] == "done" and job["progress"] == 1.0


def test_a_failing_checkup_says_why(results, installed):
    def launcher(args):
        return SimpleNamespace(
            stdout=iter(["  baseline walk\n", "boom: no OpenGL\n"]), wait=lambda: 3
        )

    jobs = Jobs(results, launcher=launcher)
    client = _client(create_app(results, static_dir=results / "no-ui", jobs=jobs), headers=HEADERS)
    job = _wait(client, client.post("/api/robots/unitree_g1/checkup").json()["id"])
    assert (
        job["state"] == "failed" and "exit code 3" in job["error"] and "no OpenGL" in job["error"]
    )


def test_the_same_checkup_is_not_started_twice(results, installed):
    release = []

    def launcher(args):
        def lines():
            while not release:
                time.sleep(0.01)
            yield ""

        return SimpleNamespace(stdout=lines(), wait=lambda: 0)

    jobs = Jobs(results, launcher=launcher)
    client = _client(create_app(results, static_dir=results / "no-ui", jobs=jobs), headers=HEADERS)
    first = client.post("/api/robots/unitree_g1/checkup").json()
    second = client.post("/api/robots/unitree_g1/checkup").json()
    release.append(True)
    assert first["id"] == second["id"]
    _wait(client, first["id"])


def test_a_reloaded_page_can_find_the_running_job(results, installed):
    release = []

    def launcher(args):
        def lines():
            while not release:
                time.sleep(0.01)
            yield ""

        return SimpleNamespace(stdout=lines(), wait=lambda: 0)

    jobs = Jobs(results, launcher=launcher)
    client = _client(create_app(results, static_dir=results / "no-ui", jobs=jobs), headers=HEADERS)
    assert client.get("/api/jobs").json() == {"jobs": []}
    started = client.post("/api/robots/unitree_g1/checkup").json()
    running = client.get("/api/jobs").json()["jobs"]
    assert [j["id"] for j in running] == [started["id"]]
    release.append(True)
    _wait(client, started["id"])
    assert client.get("/api/jobs").json() == {"jobs": []}


def test_unknown_job_is_404(client):
    assert client.get("/api/jobs/nope").status_code == 404


# ---- the UI --------------------------------------------------------------------------------


def test_the_built_ui_is_served_with_a_fallback_for_client_side_routes(
    results, installed, tmp_path
):
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text(
        "<!doctype html><title>Creature Lab</title>", encoding="utf-8"
    )
    (static / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    (static / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    client = _client(create_app(results, static_dir=static), headers=HEADERS)
    assert "Creature Lab" in client.get("/").text
    assert client.get("/assets/app.js").text == "console.log(1)"
    assert client.get("/favicon.svg").text == "<svg/>"
    assert "Creature Lab" in client.get("/robots/microduck").text  # a deep link still loads the app
    assert client.get("/api/not-a-thing").status_code == 404  # but the API never serves the page


def test_paths_cannot_escape_the_static_folder(results, installed, tmp_path):
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("INDEX", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("SECRET", encoding="utf-8")
    client = _client(create_app(results, static_dir=static), headers=HEADERS)
    for path in ("../secret.txt", "..%2fsecret.txt", "%2e%2e/secret.txt"):
        assert "SECRET" not in client.get("/" + path).text


def test_without_a_build_the_app_says_how_to_make_one(results, installed, tmp_path):
    client = _client(create_app(results, static_dir=tmp_path / "missing"), headers=HEADERS)
    response = client.get("/")
    assert response.status_code == 503 and "npm run build" in response.json()["error"]


# ---- report and classic builder ------------------------------------------------------------


def test_the_report_is_served_when_a_check_up_wrote_one(results, installed):
    client = _client(create_app(results, static_dir=results / "no-ui"), headers=HEADERS)
    assert client.get("/api/robots/microduck/report").status_code == 404  # none written yet
    folder = next(results.iterdir())
    (folder / "report.html").write_text("<h1>Microduck check-up</h1>", encoding="utf-8")
    response = client.get("/api/robots/microduck/report/")
    assert response.status_code == 200 and "Microduck check-up" in response.text
    assert client.get("/api/robots/walle/report/").status_code == 404
    # The address without the slash moves to the one with it, so relative links resolve.
    moved = client.get("/api/robots/microduck/report", follow_redirects=False)
    assert moved.status_code == 307 and moved.headers["location"] == "/api/robots/microduck/report/"


def test_the_report_shows_its_film_but_nothing_else_in_the_folder(results, installed):
    client = _client(create_app(results, static_dir=results / "no-ui"), headers=HEADERS)
    folder = next(results.iterdir())
    (folder / "report.html").write_text("<video src='microduck-checkup.mp4'>", encoding="utf-8")
    (folder / "microduck-checkup.mp4").write_bytes(b"film")
    (folder / "checkup.json").write_text("{}", encoding="utf-8")
    film = client.get("/api/robots/microduck/report/microduck-checkup.mp4")
    assert film.status_code == 200 and film.headers["content-type"] == "video/mp4"
    assert film.content == b"film"
    assert client.get("/api/robots/microduck/report/checkup.json").status_code == 404
    assert client.get("/api/robots/microduck/report/missing.mp4").status_code == 404
    for sneaky in ("..%2Fsecret.mp4", "%2e%2e/secret.mp4", "runs%5Cx.mp4", "a%2Fb.mp4"):
        assert client.get(f"/api/robots/microduck/report/{sneaky}").status_code == 404


def test_the_classic_builder_opens_only_known_presets(results, installed):
    from creature_lab.web.builder import Builder

    started = []

    def launcher(args):
        started.append(list(args))
        return SimpleNamespace(poll=lambda: None, terminate=lambda: None)

    builder = Builder(launcher=launcher, port_open=lambda port: True, wait_s=2)
    client = _client(
        create_app(results, static_dir=results / "no-ui", builder=builder), headers=HEADERS
    )
    url = client.post("/api/builder", json={"preset": "hexapod"}).json()["url"]
    assert url.startswith("http://localhost:81")
    assert started[0][:4] == ["build", "--preset", "hexapod", "--no-open-browser"]
    again = client.post("/api/builder", json={"preset": "hexapod"}).json()["url"]
    assert again == url and len(started) == 1  # the running one is reused
    client.post("/api/builder", json={"preset": "worm"})
    assert len(started) == 2  # a different preset restarts it
    assert client.post("/api/builder", json={"preset": "../../etc"}).status_code == 409
    assert client.post("/api/builder", json={}).status_code == 422
    assert (
        _client(create_app(results, static_dir=results / "no-ui"))
        .post("/api/builder", json={"preset": "worm"})
        .status_code
        == 403
    )  # needs the guard header like every changing request


def test_a_builder_that_exits_at_once_explains_the_missing_extra(results, installed):
    from creature_lab.web.builder import Builder

    builder = Builder(
        launcher=lambda args: SimpleNamespace(poll=lambda: 1, terminate=lambda: None),
        port_open=lambda port: False,
        wait_s=2,
    )
    client = _client(
        create_app(results, static_dir=results / "no-ui", builder=builder), headers=HEADERS
    )
    response = client.post("/api/builder", json={"preset": "worm"})
    assert response.status_code == 409 and "extra viz" in response.json()["detail"]


# ---- policy twins and wording ---------------------------------------------------------------


def test_each_run_points_at_its_twin_under_the_other_policy(client):
    runs = client.get("/api/robots/microduck/runs").json()["runs"]
    by_id = {run["id"]: run for run in runs}
    assert runs
    for run in runs:
        twin = by_id[run["pair"]]
        assert twin["policy"] != run["policy"] and twin["title"] == run["title"]
        assert twin["pair"] == run["id"]


def test_a_walk_that_went_nowhere_is_not_called_a_walk():
    from creature_lab.web.library import _outcome_text

    def walked(metres, stalled=False):
        return SimpleNamespace(outcome="walked", distance_m=metres, stalled=stalled)

    assert _outcome_text(walked(1.7)) == "Walked 1.7 m"
    assert _outcome_text(walked(-0.2)) == "Stayed up, barely moved"
    assert _outcome_text(walked(0.1)) == "Stayed up, barely moved"
    # On its feet at the foot of a ramp it never climbed: it stopped, it did not walk 0.7 m up it.
    assert _outcome_text(walked(0.7, stalled=True)) == "Stopped at 0.7 m"


# ---- what if --------------------------------------------------------------------------------


def _microduck_run(client, policy="velstand", title="3 N shove"):
    runs = client.get("/api/robots/microduck/runs").json()["runs"]
    return next(r for r in runs if r["title"] == title and r["policy"] == policy)


@pytest.fixture
def simulated(monkeypatch):
    """Stand in for the simulator: record each scenario asked for and return a synthetic run."""
    from robot_helpers import synthetic_run

    import creature_lab.robots.api as api_module

    asked = []

    def fake(scenario, save_to=None):
        asked.append(scenario)
        # The same walk, but it falls and stays down: so the change is visible in the result.
        return synthetic_run(
            robot=scenario.robot,
            policy=scenario.policy,
            qpos_width=8,
            fall_at=4.6,
            push_n=scenario.push_n,
            pushed_outside=True,
            title=scenario.title,
        )

    monkeypatch.setattr(api_module, "run_scenario", fake)
    return asked


def test_a_shove_run_offers_changes_that_make_sense_for_it(client):
    run = _microduck_run(client)
    detail = client.get(f"/api/runs/{run['id']}").json()

    keys = [option["key"] for option in detail["whatIfs"]]

    assert keys == ["other_side", "harder", "gentler", "ice", "slower", "faster", "weak_battery"]
    assert {o["label"] for o in detail["whatIfs"]} >= {
        "Shoved from the other side",
        "A harder shove",
    }


def test_a_plain_walk_offers_no_shove_changes(client):
    baseline = client.get("/api/robots/microduck/runs").json()["runs"][0]

    keys = [o["key"] for o in client.get(f"/api/runs/{baseline['id']}").json()["whatIfs"]]

    assert keys == ["ice", "slower", "faster", "weak_battery"]


def test_asking_what_if_runs_the_changed_scenario_and_pairs_it_with_the_original(client, simulated):
    original = _microduck_run(client)

    response = client.post(f"/api/runs/{original['id']}/whatif", json={"change": "other_side"})

    assert response.status_code == 200, response.text
    made = response.json()["run"]
    assert made["kind"] == "whatif" and made["whatIf"] == "Shoved from the other side"
    assert made["pair"] == original["id"]  # shown together with the run it came from
    assert made["policy"] == "velstand"
    (scenario,) = simulated
    assert scenario.push_side == "right" and scenario.push_n == 3.0  # only the side changed
    assert scenario.title == "3 N shove, shoved from the other side"
    listed = client.get("/api/robots/microduck/runs").json()["runs"]
    assert made["id"] in [r["id"] for r in listed]
    # The original is untouched and still points at its twin under the other policy.
    assert next(r for r in listed if r["id"] == original["id"])["pair"] == original["pair"]


def test_asking_twice_reuses_the_saved_run(client, simulated):
    original = _microduck_run(client)
    path = f"/api/runs/{original['id']}/whatif"

    first = client.post(path, json={"change": "ice"}).json()["run"]
    second = client.post(path, json={"change": "ice"}).json()["run"]

    assert first["id"] == second["id"] and len(simulated) == 1
    assert simulated[0].grip == 0.15


def test_what_if_runs_are_grouped_last_and_offer_nothing_further(client, simulated):
    original = _microduck_run(client)
    made = client.post(f"/api/runs/{original['id']}/whatif", json={"change": "harder"}).json()[
        "run"
    ]

    kinds = [r["kind"] for r in client.get("/api/robots/microduck/runs").json()["runs"]]
    assert kinds[-1] == "whatif"
    assert client.get(f"/api/runs/{made['id']}").json()["whatIfs"] == []
    again = client.post(f"/api/runs/{made['id']}/whatif", json={"change": "ice"})
    assert again.status_code == 409
    assert simulated[0].push_n == 4.5  # 3 N shoved 50% harder
    # The title must not keep saying "3 N shove" for a 4.5 N shove.
    assert simulated[0].title == "4.5 N shove, harder than the 3 N original"


def test_what_if_refuses_changes_that_do_not_apply_and_unknown_runs(client, simulated):
    baseline = client.get("/api/robots/microduck/runs").json()["runs"][0]

    no_shove = client.post(f"/api/runs/{baseline['id']}/whatif", json={"change": "other_side"})
    unknown = client.post("/api/runs/nope/whatif", json={"change": "ice"})
    made_up = client.post(f"/api/runs/{baseline['id']}/whatif", json={"change": "teleport"})

    assert no_shove.status_code == 422 and "does not apply" in no_shove.json()["detail"]
    assert unknown.status_code == 404
    assert made_up.status_code == 422
    assert simulated == []


def test_what_if_needs_the_robot_and_the_custom_header(results, installed, monkeypatch, simulated):
    app = create_app(results, static_dir=results / "no-ui")
    plain = _client(app)  # no X-Creature-Lab header
    guarded = _client(app, headers=HEADERS)
    run = _microduck_run(guarded)

    assert plain.post(f"/api/runs/{run['id']}/whatif", json={"change": "ice"}).status_code == 403
    monkeypatch.setattr(server_module, "is_installed", lambda key: False)
    offered = guarded.get(f"/api/runs/{run['id']}").json()["whatIfs"]
    assert offered == []  # nothing to offer without the robot's files
    missing = guarded.post(f"/api/runs/{run['id']}/whatif", json={"change": "ice"})
    assert missing.status_code == 409


def test_the_changes_for_each_robot_use_what_its_check_up_tests():
    from creature_lab.web.whatif import options

    base = {
        "push_n": 0.0,
        "push_side": "left",
        "grip": 1.0,
        "command": 0.5,
        "payload_kg": 0.0,
        "battery_v": 7.4,
    }
    g1 = {o.key: o for o in options(base, "unitree_g1")}
    duck = {o.key: o for o in options(base, "microduck")}

    assert g1["load"].change == {"payload_kg": 6} and "weak_battery" not in g1
    assert duck["weak_battery"].change == {"battery_v": 6.0} and "load" not in duck
    slippery = {o.key for o in options({**base, "grip": 0.15, "command": 1.0}, "microduck")}
    assert "ice" not in slippery and "faster" not in slippery  # already as bad / as fast as it goes
    weak = {o.key for o in options({**base, "battery_v": 6.0}, "microduck")}
    assert "weak_battery" not in weak
