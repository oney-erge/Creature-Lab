"""The FastAPI app behind the browser UI."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from creature_lab import VERSION
from creature_lab.robots.catalog import all_robots, robot_info
from creature_lab.robots.fetch import is_installed, missing_extra
from creature_lab.robots.pack import PackError, register_pack, unregister_pack
from creature_lab.robots.packcheck import PackReport, validate_pack
from creature_lab.web.builder import Builder, BuilderError
from creature_lab.web.creatures import (
    CreatureError,
    Designer,
    EngineMissing,
    NoSuchCreature,
    preset_catalog,
)
from creature_lab.web.jobs import Jobs, known_robot
from creature_lab.web.library import Library
from creature_lab.web.scene import load_scene, overlay_payload
from creature_lab.web.thumbs import Thumbnails, pick_time
from creature_lab.web.whatif import WhatIfError, is_what_if, options, run_what_if

STATIC_DIR = Path(__file__).parent / "static"
#: Browsers send this host name for pages served from this machine; anything else is another
#: site reaching this server through DNS rebinding.
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1"}
#: What a check-up report may show beside it (its film and pictures), by file type.
_REPORT_FILES = {
    ".html": "text/html",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".svg": "image/svg+xml",
}
#: Mutating requests must carry this header. A web page on another site cannot add it without a
#: CORS preflight, which this server never approves.
_GUARD_HEADER = "x-creature-lab"
_BINARY = "application/octet-stream"
_NO_STORE = {"Cache-Control": "no-store"}


class DownloadRequest(BaseModel):
    accept_license: bool = False


class PackRequest(BaseModel):
    """A folder on this computer that holds a robot pack (``robot.toml``)."""

    path: str


class BuilderRequest(BaseModel):
    preset: str


class WhatIfRequest(BaseModel):
    """A change from the fixed menu in ``web/whatif.py``; never numbers or paths."""

    change: str


class ImproveRequest(BaseModel):
    """How many small changes "Improve it" may try (clamped to a safe range)."""

    tries: int = 30


class BuildRequest(BaseModel):
    """A creature to design: a preset, its parameters, and a goal to run it toward."""

    preset: str
    params: dict[str, float] = {}
    goal: str = "move_forward"
    simulate: bool = False


def _pack_report(report: PackReport) -> dict:
    """What the Add-a-robot dialog shows about a checked folder."""
    pack = report.pack
    return {
        "ok": report.ok,
        "errors": report.errors,
        "warnings": report.warnings,
        "facts": [{"name": name, "value": value} for name, value in report.facts.items()],
        "title": pack.spec.title if pack else None,
        "key": pack.spec.key if pack else None,
    }


def _host_name(request: Request) -> str:
    host = request.headers.get("host", "")
    return host.rsplit(":", 1)[0] if not host.startswith("[") else host.split("]")[0] + "]"


def create_app(
    checkup_root: Path = Path("outputs") / "checkup",
    *,
    static_dir: Path | None = None,
    jobs: Jobs | None = None,
    thumbnails: Thumbnails | None = None,
    builder: Builder | None = None,
    designer: Designer | None = None,
    allowed_hosts: set[str] | None = None,
) -> FastAPI:
    """Build the app. ``checkup_root`` is where check-up results live and are written."""
    app = FastAPI(title="Creature Lab", version=VERSION, docs_url=None, redoc_url=None)
    library = Library(checkup_root)
    jobs = jobs or Jobs(checkup_root)
    designer = designer or Designer()
    thumbnails = thumbnails or Thumbnails()
    builder = builder or Builder()
    hosts = allowed_hosts or _LOCAL_HOSTS
    static = static_dir if static_dir is not None else STATIC_DIR

    @app.middleware("http")
    async def guard(request: Request, call_next: Any) -> Response:
        if _host_name(request) not in hosts:
            return JSONResponse({"error": "unknown host"}, status_code=403)
        if request.method not in {"GET", "HEAD"} and _GUARD_HEADER not in request.headers:
            return JSONResponse({"error": "missing X-Creature-Lab header"}, status_code=403)
        response = await call_next(request)
        if request.url.path.startswith("/api/") and "cache-control" not in response.headers:
            response.headers["Cache-Control"] = "no-store"  # results change as check-ups run
        return response

    # ---- state ---------------------------------------------------------------------------
    @app.get("/api/health")
    def health() -> dict:
        return {"service": "creature-lab", "version": VERSION}

    @app.get("/api/robots")
    def robots() -> dict:
        have = library.robots_with_results()
        items = []
        for key, info in all_robots().items():
            summary = library.checkup_summary(key) if key in have else None
            clip = static / "clips" / f"{key}.webp"
            items.append(
                {
                    "key": key,
                    "title": info.title,
                    "maker": info.maker,
                    "summary": info.summary,
                    "heightCm": info.height_cm,
                    "credit": info.credit,
                    "licenseNotice": info.license_notice,
                    "nonCommercial": info.non_commercial,
                    "installed": is_installed(key),
                    "hasResults": key in have,
                    "firstRunSeconds": info.first_run_s,
                    "custom": info.folder is not None,
                    "folder": str(info.folder) if info.folder is not None else None,
                    "shoveReferenceN": info.staging.shove_reference_n,
                    "introClip": f"/clips/{key}.webp" if clip.is_file() else None,
                    "policies": [
                        {"key": p.key, "title": p.title, "summary": p.summary, "getsUp": p.gets_up}
                        for p in info.policies
                    ],
                    "checkup": summary,
                }
            )
        return {"robots": items, "missingPackages": missing_extra()}

    def _pack_folder(text: str) -> Path:
        folder = Path(text.strip().strip('"')).expanduser()
        if not text.strip():
            raise HTTPException(422, "Type the folder that holds your robot.toml.")
        if not folder.exists():
            raise HTTPException(422, f"There is no folder or file at {folder}.")
        return folder

    @app.post("/api/robots/validate")
    def validate_robot(body: PackRequest) -> dict:
        """Check a robot pack (a few seconds: it walks the robot) without adding it."""
        return _pack_report(validate_pack(_pack_folder(body.path)))

    @app.post("/api/robots/add")
    def add_robot(body: PackRequest) -> dict:
        """Check a robot pack and, if nothing is wrong with it, add it to the list."""
        report = validate_pack(_pack_folder(body.path))
        result = {**_pack_report(report), "added": False}
        if not report.ok:
            return result
        try:
            register_pack(Path(body.path.strip().strip('"')).expanduser())
        except PackError as error:
            return {**result, "ok": False, "errors": error.problems}
        load_scene.cache_clear()
        return {**result, "added": True}

    @app.delete("/api/robots/{key}")
    def remove_robot(key: str) -> dict:
        """Forget a robot the person added. Its files stay where they are."""
        _require_robot(key)
        if robot_info(key).folder is None:
            raise HTTPException(409, f"{robot_info(key).title} is built in and cannot be removed")
        unregister_pack(key)
        load_scene.cache_clear()
        return {"removed": key}

    def _require_robot(key: str) -> None:
        if not known_robot(key):
            raise HTTPException(404, f"unknown robot {key!r}")

    def _require_installed(key: str) -> None:
        _require_robot(key)
        if not is_installed(key):
            raise HTTPException(409, f"{robot_info(key).title} is not downloaded yet")

    # ---- robot meshes --------------------------------------------------------------------
    @app.get("/api/robots/{key}/scene")
    def scene(key: str) -> dict:
        _require_installed(key)
        return load_scene(key).description()

    @app.get("/api/robots/{key}/mesh/{mesh_id}")
    def mesh(key: str, mesh_id: int) -> Response:
        _require_installed(key)
        data = load_scene(key)
        if mesh_id not in data.meshes:
            raise HTTPException(404, "no such mesh")
        return Response(
            data.mesh_payload(mesh_id),
            media_type=_BINARY,
            headers={"Cache-Control": "public, max-age=86400, immutable"},
        )

    @app.get("/api/robots/{key}/thumbnail")
    def robot_thumbnail(key: str) -> Response:
        _require_installed(key)
        runs = library.runs(key)
        baseline = next((r for r in runs if r.kind == "baseline"), None)
        try:
            data = thumbnails.for_robot(
                key,
                baseline.folder if baseline else None,
                pick_time(baseline.analysis, 0.0, 10.0) if baseline else 0.0,
            )
        except Exception as error:  # no OpenGL, etc.: the card falls back to a drawing
            raise HTTPException(503, f"cannot render a picture here: {error}") from error
        return Response(data, media_type="image/jpeg", headers=_NO_STORE)

    # ---- runs ----------------------------------------------------------------------------
    @app.get("/api/robots/{key}/runs")
    def runs(key: str) -> dict:
        _require_robot(key)
        return {"runs": [entry.card() for entry in library.runs(key)]}

    def _run(run_id: str):
        try:
            return library.load(run_id)
        except KeyError:
            raise HTTPException(404, "no such run") from None

    @app.get("/api/runs/{run_id}")
    def run_detail(run_id: str) -> dict:
        entry, run = _run(run_id)
        analysis = entry.analysis
        scenario = entry.scenario
        info = robot_info(entry.robot)
        return {
            **entry.card(),
            "fps": 50,
            "frames": len(run),
            "duration": float(run.time[-1]),
            "scenario": scenario,
            "cause": analysis.cause,
            "causeText": analysis.cause_text,
            "evidence": [e.model_dump() for e in analysis.evidence],
            "peakTiltDeg": round(analysis.peak_tilt_deg, 1),
            "events": {
                "pushAt": scenario["push_at_s"] if scenario["push_n"] > 0 else None,
                "pushFor": scenario["push_for_s"],
                "pushN": scenario["push_n"],
                "pushSide": scenario["push_side"],
                "fallAt": analysis.fall_time_s,
                "recoveredAt": analysis.recovered_time_s,
            },
            "tilt": _tilt_series(run),
            "credit": info.credit,
            "whatIfs": _what_ifs(entry),
        }

    def _what_ifs(entry: Any) -> list[dict]:
        """The one-click changes offered for a run (none for a what-if run or a missing robot)."""
        if entry.what_if is not None or not is_installed(entry.robot) or missing_extra():
            return []
        return [{"key": o.key, "label": o.label} for o in options(entry.scenario, entry.robot)]

    @app.post("/api/runs/{run_id}/whatif")
    def what_if(run_id: str, body: WhatIfRequest) -> dict:
        try:
            entry = library.run(run_id)
        except KeyError:
            raise HTTPException(404, "no such run") from None
        _require_installed(entry.robot)
        if missing_extra():
            raise HTTPException(409, f"missing packages: {', '.join(missing_extra())}")
        if is_what_if(entry.name):
            raise HTTPException(409, "ask from the original run, not from a what-if")
        try:
            folder = run_what_if(
                entry.folder, entry.scenario, entry.robot, entry.title, body.change
            )
        except WhatIfError as error:
            raise HTTPException(422, str(error)) from error
        except Exception as error:
            raise HTTPException(503, f"could not run that here: {error}") from error
        made = next((e for e in library.runs(entry.robot) if e.folder == folder), None)
        if made is None:
            raise HTTPException(500, "the run was saved but cannot be listed")
        return {"run": made.card()}

    @app.get("/api/runs/{run_id}/poses")
    def run_poses(run_id: str) -> Response:
        entry, run = _run(run_id)
        _require_installed(entry.robot)
        return Response(load_scene(entry.robot).pose_payload(run), media_type=_BINARY)

    @app.get("/api/runs/{run_id}/overlay")
    def run_overlay(run_id: str) -> Response:
        _, run = _run(run_id)
        return Response(overlay_payload(run), media_type=_BINARY)

    @app.get("/api/runs/{run_id}/thumbnail")
    def run_thumbnail(run_id: str) -> Response:
        entry, _ = _run(run_id)
        _require_installed(entry.robot)
        at = pick_time(entry.analysis, entry.scenario["push_at_s"], entry.scenario["seconds"])
        try:
            data = thumbnails.for_run(entry.folder, at)
        except Exception as error:
            raise HTTPException(503, f"cannot render a picture here: {error}") from error
        return Response(data, media_type="image/jpeg", headers=_NO_STORE)

    # ---- jobs ----------------------------------------------------------------------------
    @app.post("/api/robots/{key}/download")
    def download(key: str, body: DownloadRequest) -> dict:
        _require_robot(key)
        if not body.accept_license:
            raise HTTPException(400, "the license must be accepted before downloading")
        return jobs.start_download(key).snapshot()

    @app.post("/api/robots/{key}/checkup")
    def checkup(key: str) -> dict:
        _require_installed(key)
        if missing_extra():
            raise HTTPException(409, f"missing packages: {', '.join(missing_extra())}")
        return jobs.start_checkup(key).snapshot()

    @app.post("/api/builder")
    def open_builder(body: BuilderRequest) -> dict:
        try:
            return {"url": builder.open(body.preset)}
        except BuilderError as error:
            raise HTTPException(409, str(error)) from error

    @app.get("/api/robots/{key}/report", include_in_schema=False)
    def report_redirect(key: str) -> Response:
        # The report links to its film by a relative name, so it must live in a directory URL.
        return RedirectResponse(f"/api/robots/{key}/report/")

    @app.get("/api/robots/{key}/report/{name}", include_in_schema=False)
    @app.get("/api/robots/{key}/report/", include_in_schema=False)
    def report(key: str, name: str = "") -> Response:
        """The newest check-up's report page and the film or pictures it shows beside it."""
        _require_robot(key)
        folder = library.newest_folder(key)
        name = name or "report.html"
        # One plain file name from the allow-list, never a path: nothing else is readable here.
        page = folder / name if folder and Path(name).name == name else None
        if page is None or page.suffix.lower() not in _REPORT_FILES or not page.is_file():
            raise HTTPException(404, "no report yet: run a check-up first")
        return FileResponse(page, media_type=_REPORT_FILES[page.suffix.lower()])

    # ---- designing a creature -------------------------------------------------------------
    @app.get("/api/creatures/presets")
    def creature_presets() -> dict:
        return preset_catalog()

    @app.post("/api/creatures/build")
    def build_creature(body: BuildRequest) -> dict:
        """A resting preview, or a simulated run toward the goal, of a preset creature."""
        try:
            built = designer.build(body.preset, body.params, body.goal, simulate=body.simulate)
        except EngineMissing as error:
            raise HTTPException(409, str(error)) from error
        except CreatureError as error:
            raise HTTPException(400, str(error)) from error
        return {"scene": built.scene, "run": built.detail, "creature": built.creature}

    def _built(creature_id: str):
        try:
            return designer.get(creature_id)
        except CreatureError as error:
            raise HTTPException(404, str(error)) from error

    @app.get("/api/creatures/{creature_id}/scene")
    def creature_scene(creature_id: str) -> dict:
        return _built(creature_id).scene

    @app.get("/api/creatures/{creature_id}/mesh/{mesh_id}")
    def creature_mesh(creature_id: str, mesh_id: int) -> Response:
        meshes = _built(creature_id).meshes
        if mesh_id not in meshes:
            raise HTTPException(404, "no such mesh")
        return Response(meshes[mesh_id], media_type=_BINARY)

    @app.get("/api/creatures/{creature_id}/poses")
    def creature_poses(creature_id: str) -> Response:
        return Response(_built(creature_id).poses, media_type=_BINARY)

    @app.get("/api/creatures/{creature_id}/overlay")
    def creature_overlay(creature_id: str) -> Response:
        return Response(_built(creature_id).overlay, media_type=_BINARY)

    @app.post("/api/creatures/{creature_id}/shove")
    def creature_shove(creature_id: str) -> dict:
        """Shove the creature at rising strengths and say how hard before it topples."""
        try:
            return designer.shove(creature_id)
        except NoSuchCreature as error:
            raise HTTPException(404, str(error)) from error
        except EngineMissing as error:
            raise HTTPException(409, str(error)) from error

    @app.post("/api/creatures/{creature_id}/improve")
    def creature_improve(creature_id: str, body: ImproveRequest) -> dict:
        """Try small design changes; the answer carries a new run only if one is clearly better."""
        try:
            return designer.improve(creature_id, body.tries)
        except NoSuchCreature as error:
            raise HTTPException(404, str(error)) from error
        except EngineMissing as error:
            raise HTTPException(409, str(error)) from error

    @app.get("/api/creatures/{creature_id}/export/{fmt}")
    def creature_export(creature_id: str, fmt: str) -> Response:
        """The creature as a file: its JSON spec, a MuJoCo model (MJCF) or a URDF."""
        try:
            text, media_type, filename = designer.export(creature_id, fmt)
        except NoSuchCreature as error:
            raise HTTPException(404, str(error)) from error
        except CreatureError as error:
            raise HTTPException(400, str(error)) from error
        return Response(
            text,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"', **_NO_STORE},
        )

    @app.get("/api/jobs")
    def running_jobs() -> dict:
        return {"jobs": [j.snapshot() for j in jobs.active()]}

    @app.get("/api/jobs/{job_id}")
    def job(job_id: str) -> dict:
        try:
            return jobs.get(job_id).snapshot()
        except KeyError:
            raise HTTPException(404, "no such job") from None

    # ---- the UI --------------------------------------------------------------------------
    if (static / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=static / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> Response:
        if path.startswith("api/"):
            raise HTTPException(404, "no such endpoint")
        target = (static / path).resolve()
        if path and target.is_file() and static.resolve() in target.parents:
            return FileResponse(target)
        index = static / "index.html"
        if not index.is_file():
            return JSONResponse(
                {"error": "the UI is not built; run `npm run build` in web-ui/"}, status_code=503
            )
        return FileResponse(index, headers=_NO_STORE)

    return app


def _tilt_series(run: Any, points: int = 250) -> list[float]:
    """The trunk's lean angle in degrees, thinned to about ``points`` samples."""
    import numpy as np

    tilt = np.degrees(np.arccos(np.clip(run.upright, -1.0, 1.0)))
    step = max(1, len(tilt) // points)
    return [round(float(v), 1) for v in tilt[::step]]
