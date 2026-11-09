"""The FastAPI app behind the browser UI."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from creature_lab import VERSION
from creature_lab.robots.catalog import ROBOTS, robot_info
from creature_lab.robots.fetch import is_installed, missing_extra
from creature_lab.web.builder import Builder, BuilderError
from creature_lab.web.jobs import Jobs, known_robot
from creature_lab.web.library import Library
from creature_lab.web.scene import load_scene, overlay_payload
from creature_lab.web.thumbs import Thumbnails, pick_time

STATIC_DIR = Path(__file__).parent / "static"
#: Browsers send this host name for pages served from this machine; anything else is another
#: site reaching this server through DNS rebinding.
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1"}
#: Mutating requests must carry this header. A web page on another site cannot add it without a
#: CORS preflight, which this server never approves.
_GUARD_HEADER = "x-creature-lab"
_BINARY = "application/octet-stream"
_NO_STORE = {"Cache-Control": "no-store"}


class DownloadRequest(BaseModel):
    accept_license: bool = False


class BuilderRequest(BaseModel):
    preset: str


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
    allowed_hosts: set[str] | None = None,
) -> FastAPI:
    """Build the app. ``checkup_root`` is where check-up results live and are written."""
    app = FastAPI(title="Creature Lab", version=VERSION, docs_url=None, redoc_url=None)
    library = Library(checkup_root)
    jobs = jobs or Jobs(checkup_root)
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
        for key, info in ROBOTS.items():
            summary = library.checkup_summary(key) if key in have else None
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
                    "policies": [
                        {"key": p.key, "title": p.title, "summary": p.summary, "getsUp": p.gets_up}
                        for p in info.policies
                    ],
                    "checkup": summary,
                }
            )
        return {"robots": items, "missingPackages": missing_extra()}

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
        }

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
    def report(key: str) -> Response:
        _require_robot(key)
        folder = library.newest_folder(key)
        page = folder / "report.html" if folder else None
        if page is None or not page.is_file():
            raise HTTPException(404, "no report yet: run a check-up first")
        return FileResponse(page, media_type="text/html")

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
