"""Ground to walk over: stairs, a ramp, rough ground and stepping stones, all built from boxes.

The check-up walks a robot over a short course of each kind at a few heights. Every course is
sized from the robot's height, so a 25 cm desk robot and a 1.3 m humanoid both meet steps that are
hard for their size. The ground is plain boxes, so the simulator, the films and the browser all
draw exactly the same thing, and the height of the ground anywhere is easy to work out.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING, Literal

import numpy as np
from pydantic import ConfigDict, Field

from creature_lab.schema.base import StrictModel

if TYPE_CHECKING:
    import mujoco

TerrainKind = Literal["stairs", "ramp", "rough", "stones"]

#: Every terrain geom's name starts with this; the rollout counts these and the floor as ground.
GEOM_PREFIX = "terrain_"

# Course sizes as fractions of the robot's height (a 1.34 m G1 gets 30 cm treads, 4-16 cm steps).
_STAIR_TREAD = 0.22
_STAIR_RISES = (0.03, 0.06, 0.09, 0.12)
_STAIR_COUNT = 4
_STAIR_LANDING = 3  # treads
_RAMP_UNIT = 0.22
_RAMP_DEGREES = (8.0, 16.0, 24.0)
_RAMP_RUN = 5  # units of horizontal run up, and again down
_RAMP_TOP = 3  # units of flat top
_ROUGH_TILE = 0.15
_ROUGH_BUMPS = (0.02, 0.04, 0.06)
_ROUGH_LENGTH = 4.0  # robot heights of tiles
_ROUGH_WIDTH = 11  # tiles
_STONE = 0.3
_STONE_GAPS = (0.04, 0.08, 0.12)
_STONE_ROWS = 10
_STONE_COLUMNS = 5
_PIT_DEPTH = 0.4  # robot heights
_START = 0.6  # robot heights of flat ground before every course
_WIDTH_UNITS = 8

_SLATE = (0.36, 0.42, 0.52, 1.0)
_SLATE_DARK = (0.30, 0.35, 0.45, 1.0)
_STONE_RGBA = (0.52, 0.53, 0.55, 1.0)
_LOW = np.array([0.26, 0.31, 0.40])
_HIGH = np.array([0.52, 0.58, 0.66])


class Terrain(StrictModel):
    """One course laid out ahead of the robot (along +x), starting ``start_m`` from its start."""

    model_config = ConfigDict(frozen=True)

    kind: TerrainKind
    #: How hard it is: the step height in metres (stairs), the slope in degrees (ramp), the
    #: tallest bump in metres (rough ground) or the gap between stones in metres (stones).
    level: float = Field(gt=0.0, le=60.0)
    #: The course's building block in metres: a stair tread, a ramp's length unit, a rough-ground
    #: tile or a stepping stone.
    unit_m: float = Field(gt=0.0, le=5.0)
    #: Metres of flat ground between the robot's starting point and the course.
    start_m: float = Field(ge=0.0, le=20.0)
    #: Seeds the heights of rough ground (the same seed always gives the same ground).
    seed: int = Field(default=0, ge=0)


@dataclass(frozen=True)
class Box:
    """A solid block of ground. ``pitch`` tilts it about y; positive rises along +x."""

    center: tuple[float, float, float]
    half: tuple[float, float, float]
    rgba: tuple[float, float, float, float]
    pitch: float = 0.0

    @property
    def quat(self) -> tuple[float, float, float, float]:
        """MuJoCo quaternion (w, x, y, z): a rotation of ``-pitch`` about y raises the +x end."""
        return (math.cos(-self.pitch / 2), 0.0, math.sin(-self.pitch / 2), 0.0)

    def top_face(self) -> tuple[float, float, float, float, float, float]:
        """(x0, x1, y0, y1, height at x0, slope) of the face a foot stands on."""
        a, b = self.half[0], self.half[2]
        p = self.pitch
        top_x = self.center[0] - b * math.sin(p)
        top_z = self.center[2] + b * math.cos(p)
        x0, x1 = top_x - a * math.cos(p), top_x + a * math.cos(p)
        return (
            x0,
            x1,
            self.center[1] - self.half[1],
            self.center[1] + self.half[1],
            top_z - a * math.sin(p),
            math.tan(p),
        )


@dataclass(frozen=True)
class Layout:
    """The boxes of one course and the height of the floor around them."""

    boxes: tuple[Box, ...]
    #: Height of the floor plane: 0, or below 0 when the course is stones over a pit.
    floor_z: float = 0.0

    def faces(self) -> np.ndarray:
        """(n, 6) array of every box's ``top_face``."""
        return np.array([box.top_face() for box in self.boxes], dtype=float).reshape(-1, 6)


def _flat_box(x0, x1, y0, y1, z0, z1, rgba) -> Box:
    return Box(
        ((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2),
        ((x1 - x0) / 2, (y1 - y0) / 2, (z1 - z0) / 2),
        rgba,
    )


def _pitched_box(x0: float, z0: float, run: float, pitch: float, width: float, rgba) -> Box:
    """A box whose top face runs from (x0, z0) over ``run`` metres of x at slope ``pitch``,
    thick enough that its underside stays below the floor along the whole run."""
    rise = run * math.tan(pitch)
    a = run / math.cos(pitch) / 2
    b = (abs(rise) + 0.02 * run) / (2 * math.cos(pitch))
    mid_x, mid_z = x0 + run / 2, z0 + rise / 2
    center = (mid_x + b * math.sin(pitch), 0.0, mid_z - b * math.cos(pitch))
    return Box(center, (a, width / 2, b), rgba, pitch)


@lru_cache(maxsize=32)
def layout(terrain: Terrain) -> Layout:
    """The boxes that make up ``terrain``."""
    unit, start, level = terrain.unit_m, terrain.start_m, terrain.level
    half_width = _WIDTH_UNITS * unit / 2
    if terrain.kind == "stairs":
        boxes = []
        x = start
        # Four steps up, a landing three treads long, four steps down.
        heights = [*range(1, _STAIR_COUNT + 1)] + [_STAIR_COUNT] * (_STAIR_LANDING - 1)
        heights += list(range(_STAIR_COUNT - 1, 0, -1))
        for index, steps in enumerate(heights):
            rgba = _SLATE if index % 2 == 0 else _SLATE_DARK
            boxes.append(_flat_box(x, x + unit, -half_width, half_width, 0.0, steps * level, rgba))
            x += unit
        return Layout(tuple(boxes))
    if terrain.kind == "ramp":
        pitch = math.radians(level)
        run = _RAMP_RUN * unit
        top = run * math.tan(pitch)
        up = _pitched_box(start, 0.0, run, pitch, 2 * half_width, _SLATE)
        flat = _flat_box(
            start + run,
            start + run + _RAMP_TOP * unit,
            -half_width,
            half_width,
            0.0,
            top,
            _SLATE_DARK,
        )
        down = _pitched_box(
            start + run + _RAMP_TOP * unit, top, run, -pitch, 2 * half_width, _SLATE
        )
        return Layout((up, flat, down))
    if terrain.kind == "rough":
        rows = math.ceil(_ROUGH_LENGTH / _ROUGH_TILE)  # four robot heights of tiles
        rng = np.random.default_rng(terrain.seed)
        heights = rng.uniform(0.0, level, size=(rows, _ROUGH_WIDTH))
        boxes = []
        y_start = -_ROUGH_WIDTH * unit / 2
        for row in range(rows):
            for column in range(_ROUGH_WIDTH):
                height = float(heights[row, column])
                shade = _LOW + (_HIGH - _LOW) * (height / level)
                x0, y0 = start + row * unit, y_start + column * unit
                boxes.append(
                    _flat_box(
                        x0, x0 + unit, y0, y0 + unit, -level, height, (*map(float, shade), 1.0)
                    )
                )
        return Layout(tuple(boxes))
    # Stepping stones: a platform to start on, rows of stones over a pit, a platform to end on.
    depth = _PIT_DEPTH / _STONE * unit
    pitch_m = unit + level
    span = _STONE_COLUMNS * unit + (_STONE_COLUMNS - 1) * level
    end = start + level + _STONE_ROWS * pitch_m
    boxes = [
        _flat_box(-start - 2 * unit, start, -half_width, half_width, -depth, 0.0, _SLATE),
        _flat_box(end, end + 3 * unit, -half_width, half_width, -depth, 0.0, _SLATE),
    ]
    for row in range(_STONE_ROWS):
        x0 = start + level + row * pitch_m
        for column in range(_STONE_COLUMNS):
            y0 = -span / 2 + column * pitch_m
            boxes.append(_flat_box(x0, x0 + unit, y0, y0 + unit, -depth, 0.0, _STONE_RGBA))
    return Layout(tuple(boxes), floor_z=-depth)


def ground_height(lay: Layout, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Height of the ground (the highest top face, else the floor) under each (x, y) point."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    faces = lay.faces()
    if len(faces) == 0:
        return np.full(x.shape, lay.floor_z)
    x0, x1, y0, y1, z0, slope = (faces[:, i] for i in range(6))
    xs, ys = x[..., None], y[..., None]
    inside = (xs >= x0) & (xs <= x1) & (ys >= y0) & (ys <= y1)
    tops = np.where(inside, z0 + slope * (xs - x0), -np.inf)
    return np.maximum(tops.max(axis=-1), lay.floor_z)


def add_terrain(spec: mujoco.MjSpec, terrain: Terrain) -> None:
    """Add ``terrain``'s boxes to a scene spec, touching the robot like the floor does."""
    import mujoco

    lay = layout(terrain)
    floor = next(geom for geom in spec.geoms if geom.name == "floor")
    floor.pos = [0.0, 0.0, lay.floor_z]
    for index, box in enumerate(lay.boxes):
        geom = spec.worldbody.add_geom()
        geom.name = f"{GEOM_PREFIX}{index}"
        geom.type = mujoco.mjtGeom.mjGEOM_BOX
        geom.size = list(box.half)
        geom.pos = list(box.center)
        geom.quat = list(box.quat)
        geom.rgba = list(box.rgba)
        for field in (
            "contype",
            "conaffinity",
            "condim",
            "friction",
            "solref",
            "solimp",
            "solmix",
            "priority",
            "margin",
            "gap",
            "group",
        ):
            setattr(geom, field, getattr(floor, field))


def description(terrain: Terrain | None) -> dict | None:
    """The boxes as JSON for the browser (positions, half sizes, quaternions w-x-y-z, colours)."""
    if terrain is None:
        return None
    lay = layout(terrain)
    return {
        "kind": terrain.kind,
        "label": label(terrain),
        "floorZ": round(lay.floor_z, 5),
        "boxes": [
            {
                "pos": [round(v, 5) for v in box.center],
                "half": [round(v, 5) for v in box.half],
                "quat": [round(v, 6) for v in box.quat],
                "rgba": [round(v, 3) for v in box.rgba],
            }
            for box in lay.boxes
        ],
    }


def length_text(metres: float) -> str:
    """ "8 cm", "12.5 cm" or "7 mm"."""
    if metres >= 0.01:
        return f"{round(metres * 100, 1):g} cm"
    return f"{round(metres * 1000, 1):g} mm"


def label(terrain: Terrain) -> str:
    """What the course is, as a test name: "Stairs with 8 cm steps"."""
    if terrain.kind == "stairs":
        return f"Stairs with {length_text(terrain.level)} steps"
    if terrain.kind == "ramp":
        return f"Ramp sloping {terrain.level:g}°"
    if terrain.kind == "rough":
        return f"Rough ground, bumps up to {length_text(terrain.level)}"
    return f"Stepping stones {length_text(terrain.level)} apart"


def phrase(terrain: Terrain) -> str:
    """Where the robot walked, inside a sentence: "over stairs with 8 cm steps"."""
    if terrain.kind == "stairs":
        return f"over stairs with {length_text(terrain.level)} steps"
    if terrain.kind == "ramp":
        return f"up a ramp sloping {terrain.level:g}°"
    if terrain.kind == "rough":
        return f"over rough ground with bumps up to {length_text(terrain.level)}"
    return f"across stepping stones {length_text(terrain.level)} apart"


def obstacle(terrain: Terrain) -> str:
    """The thing a foot catches on this course, inside a sentence: "a step"."""
    return {"stairs": "a step", "ramp": "the ramp", "rough": "a raised tile", "stones": "a stone"}[
        terrain.kind
    ]


def key(terrain: Terrain) -> str:
    """Folder-safe test key: ``terrain_stairs_8cm``."""
    if terrain.kind == "ramp":
        amount = f"{terrain.level:g}deg"
    else:
        amount = length_text(terrain.level).replace(" ", "").replace(".", "p")
    return f"terrain_{terrain.kind}_{amount}"


def _snap(metres: float, height_m: float) -> float:
    """Round to whole centimetres for a robot a metre or taller, else to millimetres."""
    step = 0.01 if height_m >= 1.0 else 0.001
    return round(round(metres / step) * step, 4)


def course(height_cm: float) -> list[Terrain]:
    """The terrain tests for a robot this tall: stairs, a ramp, rough ground, stepping stones."""
    h = height_cm / 100.0
    start = round(_START * h, 3)
    tests = [
        Terrain(
            kind="stairs",
            level=_snap(r * h, h),
            unit_m=round(_STAIR_TREAD * h, 3),
            start_m=start,
        )
        for r in _STAIR_RISES
    ]
    tests += [
        Terrain(kind="ramp", level=d, unit_m=round(_RAMP_UNIT * h, 3), start_m=start)
        for d in _RAMP_DEGREES
    ]
    tests += [
        Terrain(
            kind="rough", level=_snap(b * h, h), unit_m=round(_ROUGH_TILE * h, 3), start_m=start
        )
        for b in _ROUGH_BUMPS
    ]
    tests += [
        Terrain(kind="stones", level=_snap(g * h, h), unit_m=round(_STONE * h, 3), start_m=start)
        for g in _STONE_GAPS
    ]
    return tests
