"""Write the app and a recorded check-up as plain files, so a web site can host it without Python.

The exporter calls the app's own endpoints in-process and saves each answer, so the files hold
exactly what the live app would send. The front end reads them in "static mode" (see
``web-ui/src/api.ts``): the same page, with a banner, and without the buttons that need a server
(download, check-up, what-if, design, add a robot).

    creature-lab app --export-static demo/ --robot unitree_g1 --robot unitree_h1

Only robots with saved check-ups are exported, and a robot whose files are non-commercial
(Microduck's meshes are CC BY-NC-SA) only with ``include_non_commercial=True``.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from creature_lab.web.server import STATIC_DIR, create_app

#: Set in the exported ``index.html``; the front end checks it before every request.
STATIC_FLAG = "<script>window.CREATURE_LAB_STATIC = true;</script>"


class ExportError(RuntimeError):
    """Nothing to export, or the app could not answer for a robot it listed."""


class _Local:
    """Asks a FastAPI app for a path without a server or an HTTP client library."""

    def __init__(self, app: Any) -> None:
        self._app = app
        self._loop = asyncio.new_event_loop()

    def close(self) -> None:
        self._loop.close()

    def get(self, path: str) -> tuple[int, bytes]:
        return self._loop.run_until_complete(self._get(path))

    async def _get(self, path: str) -> tuple[int, bytes]:
        status, body = 0, bytearray()
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "root_path": "",
            "headers": [(b"host", b"localhost")],
            "client": ("127.0.0.1", 1),
            "server": ("localhost", 80),
        }

        async def receive() -> dict:
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message: dict) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            elif message["type"] == "http.response.body":
                body.extend(message.get("body", b""))

        await self._app(scope, receive, send)
        return status, bytes(body)


def _check_destination(out: Path) -> None:
    """Only an empty folder, a new one, or the exporter's own earlier output may be written to.

    The exporter replaces its own ``data/`` and ``assets/`` on a repeat run, so it must never be
    pointed at a folder that holds anything else.
    """
    if out.exists() and not out.is_dir():
        raise ExportError(f"{out} is a file, not a folder")
    if out.is_dir() and any(out.iterdir()) and not (out / "data" / "robots.json").is_file():
        raise ExportError(
            f"{out} is not empty and does not hold an earlier export; use a new or empty folder"
        )


def _write(path: Path, data: bytes | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)


def export_static(
    checkups: Path,
    out: Path,
    *,
    robots: list[str] | None = None,
    include_non_commercial: bool = False,
    progress: Callable[[str], None] | None = None,
) -> dict:
    """Export the newest check-up of each chosen robot, and the app, into ``out``.

    Returns a summary: the robots written, the number of files and their total size.
    """
    say = progress or (lambda message: None)
    out = Path(out)
    _check_destination(out)
    app = create_app(Path(checkups), static_dir=STATIC_DIR)
    local = _Local(app)
    try:
        return _export(local, out, robots, include_non_commercial, say)
    finally:
        local.close()


def _export(
    local: _Local,
    out: Path,
    wanted: list[str] | None,
    include_non_commercial: bool,
    say: Callable[[str], None],
) -> dict:
    def fetch(path: str) -> bytes:
        status, body = local.get(path)
        if status != 200:
            raise ExportError(f"{path} answered {status}")
        return body

    listing = json.loads(fetch("/api/robots"))
    chosen = [
        r
        for r in listing["robots"]
        if r["hasResults"]
        and (wanted is None or r["key"] in wanted)
        and (include_non_commercial or not r["nonCommercial"])
    ]
    if not chosen:
        raise ExportError(
            "no robot to export: run a check-up first (robots checkup ROBOT) and, for a "
            "non-commercial robot such as Microduck, pass include_non_commercial"
        )
    skipped = [r["key"] for r in listing["robots"] if r["hasResults"] and r not in chosen]

    data = out / "data"
    if data.exists():
        shutil.rmtree(data)  # only ever the exporter's own folder inside ``out``
    for robot in chosen:
        key = robot["key"]
        say(f"{key}: meshes and runs")
        scene = json.loads(fetch(f"/api/robots/{key}/scene"))
        _write(data / "robots" / key / "scene.json", json.dumps(scene))
        for mesh in scene["meshes"]:
            _write(
                data / "robots" / key / "mesh" / f"{mesh['id']}.bin",
                fetch(f"/api/robots/{key}/mesh/{mesh['id']}"),
            )
        runs = json.loads(fetch(f"/api/robots/{key}/runs"))
        _write(data / "robots" / key / "runs.json", json.dumps(runs))
        for run in runs["runs"]:
            run_id = run["id"]
            detail = json.loads(fetch(f"/api/runs/{run_id}"))
            detail["whatIfs"] = []  # a recorded demo cannot run a new "what if"
            _write(data / "runs" / run_id / "detail.json", json.dumps(detail))
            _write(data / "runs" / run_id / "poses.bin", fetch(f"/api/runs/{run_id}/poses"))
            _write(data / "runs" / run_id / "overlay.bin", fetch(f"/api/runs/{run_id}/overlay"))
            _picture(
                local, f"/api/runs/{run_id}/thumbnail", data / "runs" / run_id / "thumbnail.jpg"
            )
        _picture(local, f"/api/robots/{key}/thumbnail", data / "robots" / key / "thumbnail.jpg")
        # What the page needs to list the robot: ready on any machine, nothing local.
        robot["installed"] = True
        robot["introClip"] = None
        robot["preview"] = None  # every robot in a recorded demo is "installed"
        robot["custom"] = False
        robot["folder"] = None
        if robot.get("checkup"):
            robot["checkup"]["folder"] = ""
    _write(data / "robots.json", json.dumps({"robots": chosen, "missingPackages": []}))

    say("the app")
    _copy_app(out)
    files = [p for p in out.rglob("*") if p.is_file()]
    return {
        "robots": [r["key"] for r in chosen],
        "skipped": skipped,
        "files": len(files),
        "bytes": sum(p.stat().st_size for p in files),
    }


def _picture(local: _Local, path: str, target: Path) -> None:
    """A thumbnail, when this machine can render one; the page has a drawing for the rest."""
    status, body = local.get(path)
    if status == 200 and body:
        _write(target, body)


def _copy_app(out: Path) -> None:
    """The built front end, made to work from any folder and told it is static."""
    assets = out / "assets"
    if assets.exists():
        shutil.rmtree(assets)  # the exporter's own previous copy of the bundle
    shutil.copytree(STATIC_DIR / "assets", assets)
    page = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    page = page.replace('"/assets/', '"./assets/')  # relative, so /demo/ works as well as /
    page = page.replace("</head>", f"    {STATIC_FLAG}\n  </head>", 1)
    _write(out / "index.html", page)
