"""Thumbnails for robot and run cards, rendered with the same studio as the films.

OpenGL contexts must not be created from many request threads at once, so every render goes
through one dedicated worker thread that owns the renderers. Results are cached on disk next
to what they show (run folders, or the robot's download folder), never in the repository.
"""

from __future__ import annotations

import io
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from creature_lab.robots.analysis import RunAnalysis
from creature_lab.robots.catalog import robot_info
from creature_lab.robots.fetch import cache_root, robot_dir
from creature_lab.robots.pack import PACK_FILE

WIDTH, HEIGHT = 640, 360
#: Frames rendered first so the follow camera settles on the robot before the one we keep.
_SETTLE = 12


def pick_time(analysis: RunAnalysis, push_at: float, seconds: float) -> float:
    """The moment worth showing: after the fall for a fall, standing again for a recovery."""
    if analysis.recovered_time_s is not None:
        return min(analysis.recovered_time_s + 0.4, seconds - 0.05)
    if analysis.fall_time_s is not None:
        return min(analysis.fall_time_s + 1.6, seconds - 0.05)
    if push_at > 0:
        return min(push_at + 0.5, seconds - 0.05)
    return min(3.2, seconds - 0.05)


class Thumbnails:
    """Renders and caches JPEG thumbnails; ``render`` is injectable so tests need no GPU."""

    def __init__(self, render: Callable[..., bytes] | None = None) -> None:
        self._render = render or _render_run_frame
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="thumbs")

    def for_run(self, folder: Path, at: float) -> bytes:
        cached = folder / "thumb.jpg"
        if cached.exists():
            return cached.read_bytes()
        data = self._pool.submit(self._render, folder, at).result(timeout=120)
        cached.write_bytes(data)
        return data

    def for_robot(self, robot: str, folder: Path | None, at: float) -> bytes:
        """A card picture for a robot: a frame of its baseline walk, else its resting pose."""
        cache = _robot_cache(robot)
        if folder is None and cache.exists():
            return cache.read_bytes()
        if folder is not None:
            return self.for_run(folder, at)
        data = self._pool.submit(_render_rest_pose, robot).result(timeout=120)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(data)
        return data


def _robot_cache(robot: str) -> Path:
    """Where a robot's card picture is kept: beside a downloaded robot's files, but in the app's
    cache (named by the pack file's age, so an edited pack is drawn again) for a pack, whose
    folder belongs to its author."""
    info = robot_info(robot)
    if info.folder is None:
        return robot_dir(robot) / "thumb.jpg"
    try:
        stamp = int((info.folder / PACK_FILE).stat().st_mtime)
    except OSError:
        stamp = 0
    return cache_root() / "pack-thumbs" / f"{robot}-{stamp}.jpg"


_studios: dict[str, object] = {}


def _studio(robot: str):
    from creature_lab.robots.render import Shot, Studio, default_shot

    if robot not in _studios:
        base = default_shot(robot)
        shot = Shot(
            distance=base.distance * 1.15,
            look_height=base.look_height,
            azimuth_start=135,
            azimuth_end=135,
        )
        _studios[robot] = Studio(robot, WIDTH, HEIGHT, shot=shot)
    return _studios[robot]


def _jpeg(frame) -> bytes:
    from PIL import Image

    out = io.BytesIO()
    Image.fromarray(frame).save(out, format="JPEG", quality=86)
    return out.getvalue()


def _render_run_frame(folder: Path, at: float) -> bytes:
    from creature_lab.robots.types import RobotRun

    run = RobotRun.read(folder)
    studio = _studio(run.scenario.robot)
    studio.reset_camera()
    for step in range(_SETTLE, 0, -1):
        studio.render(run, max(at - step * 0.04, 0.05), progress=0.5, markers=False)
    return _jpeg(studio.render(run, at, progress=0.5, markers=False))


def _render_rest_pose(robot: str) -> bytes:
    import numpy as np

    studio = _studio(robot)
    studio.reset_camera()

    class _Rest:
        """The one attribute set the studio reads, holding the model's resting pose."""

        qpos = np.array([studio.model.qpos0])
        push_force = np.zeros(1)
        support = np.full((1, 8, 2), np.nan)
        com = np.zeros((1, 3))
        com_vel = np.zeros((1, 3))
        trunk_pos = np.zeros((1, 3))
        scenario = type("S", (), {"seconds": 1.0})()

        def __len__(self) -> int:
            return 1

    rest = _Rest()
    studio.render(rest, 0.02, progress=0.5, markers=False)
    return _jpeg(studio.render(rest, 0.02, progress=0.5, markers=False))
