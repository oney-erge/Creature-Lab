"""Design a creature in the browser: its presets, a resting preview and a simulated run.

A creature is a handful of boxes, spheres, capsules and cylinders. The browser gets them the
same way it gets a real robot: each part's mesh once, then the pose of every part per frame,
so the same 3D view plays both. Nothing here accepts a path from the browser.
"""

from __future__ import annotations

import math
import struct
import threading
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from creature_lab.diagnosis import diagnose
from creature_lab.editor import presets
from creature_lab.schema import CreatureSpec
from creature_lab.schema.creature import PartSpec, ShapeType
from creature_lab.schema.trace import FrameState
from creature_lab.web import shoves

#: Floats per frame in the pose stream (position, then quaternion w, x, y, z) and in the
#: overlay stream. Both match the real-robot streams, so one 3D view plays either.
POSE_STRIDE = 7
OVERLAY_STRIDE = 22
_KEEP = 12
_PALETTE = (
    (0.95, 0.55, 0.25),
    (0.35, 0.72, 0.9),
    (0.6, 0.8, 0.45),
    (0.85, 0.5, 0.75),
    (0.9, 0.8, 0.4),
    (0.55, 0.6, 0.9),
)
_SEGMENTS = 20
_FALL_DEG = 60.0


class CreatureError(Exception):
    """Something the person asked for that cannot be built (an unknown preset or goal)."""


class NoSuchCreature(CreatureError):
    """A creature that was never built here, or was dropped to make room for newer ones."""


class EngineMissing(CreatureError):
    """No physics engine is installed; the message says which extra to add."""


# ---- shapes as meshes ------------------------------------------------------------------------


def _revolve(profile: list[tuple[float, float]]) -> tuple[np.ndarray, np.ndarray]:
    """A mesh of revolution about Z from (radius, z) rings, bottom to top (radius 0 = a pole)."""
    angles = np.linspace(0.0, 2.0 * math.pi, _SEGMENTS, endpoint=False)
    vertices: list[tuple[float, float, float]] = []
    rings: list[list[int]] = []
    for radius, z in profile:
        if radius < 1e-9:
            rings.append([len(vertices)])
            vertices.append((0.0, 0.0, z))
        else:
            rings.append(list(range(len(vertices), len(vertices) + _SEGMENTS)))
            vertices.extend((radius * math.cos(a), radius * math.sin(a), z) for a in angles)
    faces: list[tuple[int, int, int]] = []
    for lower, upper in zip(rings, rings[1:], strict=False):
        for i in range(_SEGMENTS):
            j = (i + 1) % _SEGMENTS
            if len(lower) == 1:
                faces.append((lower[0], upper[i], upper[j]))
            elif len(upper) == 1:
                faces.append((lower[i], upper[0], lower[j]))
            else:
                faces.append((lower[i], upper[i], upper[j]))
                faces.append((lower[i], upper[j], lower[j]))
    return np.array(vertices, dtype=np.float32), np.array(faces, dtype=np.uint32)


def _hemisphere(radius: float, z0: float, up: bool, rings: int = 6):
    out = []
    for k in range(rings + 1):
        angle = (math.pi / 2) * k / rings
        out.append((radius * math.cos(angle), z0 + (1 if up else -1) * radius * math.sin(angle)))
    return out if up else out[::-1]


def part_mesh(part: PartSpec) -> tuple[np.ndarray, np.ndarray]:
    """Vertices and triangles of one part, centred on its own origin, long axis along Z."""
    if part.shape == ShapeType.BOX:
        sx, sy, sz = (c / 2 for c in part.size)  # type: ignore[union-attr]
        corners = np.array(
            [(x, y, z) for z in (-sz, sz) for y in (-sy, sy) for x in (-sx, sx)], dtype=np.float32
        )
        quads = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
        faces = [t for a, b, c, d in quads for t in ((a, b, c), (a, c, d))]
        return corners, np.array(faces, dtype=np.uint32)
    radius = float(part.radius or 0.05)
    if part.shape == ShapeType.SPHERE:
        return _revolve(_hemisphere(radius, 0.0, False, 8) + _hemisphere(radius, 0.0, True, 8)[1:])
    half = float(part.length or 0.1) / 2
    if part.shape == ShapeType.CYLINDER:
        # Rings with a pole above and below make the end caps.
        return _revolve([(0.0, -half), (radius, -half), (radius, half), (0.0, half)])
    return _revolve(_hemisphere(radius, -half, False) + _hemisphere(radius, half, True))


def encode_mesh(vertices: np.ndarray, faces: np.ndarray) -> bytes:
    """The browser's mesh layout: vertex count, face count, float32 vertices, uint32 faces."""
    return (
        struct.pack("<II", len(vertices), len(faces))
        + vertices.astype("<f4").tobytes()
        + faces.astype("<u4").tobytes()
    )


# ---- one built creature -----------------------------------------------------------------------


@dataclass
class Built:
    """What the browser can fetch for one preview or one run."""

    id: str
    scene: dict
    meshes: dict[int, bytes]
    poses: bytes
    overlay: bytes
    detail: dict
    creature: dict = field(default_factory=dict)
    #: What follow-up tests need: the creature, its task, the controller it ran with, the engine.
    spec: CreatureSpec | None = None
    task: Any = None
    controller: str = "sinusoid"
    backend_name: str = ""


def _color(part: PartSpec, index: int) -> list[float]:
    rgb = part.color if part.color is not None else _PALETTE[index % len(_PALETTE)]
    # Lifted a little: the studio lighting makes the schema's dark blues vanish into the floor.
    return [min(1.0, float(c) * 1.2 + 0.12) for c in rgb] + [1.0]


def _poses_array(creature: CreatureSpec, frames: list[FrameState]) -> np.ndarray:
    ids = [part.id for part in creature.parts]
    out = np.zeros((len(frames), len(ids), POSE_STRIDE), dtype=np.float32)
    for f, frame in enumerate(frames):
        for p, part_id in enumerate(ids):
            pose = frame.parts[part_id]
            out[f, p, :3] = pose.position
            out[f, p, 3:] = pose.orientation
    return out


def _tilt_degrees(poses: np.ndarray, root: int) -> np.ndarray:
    x, y = poses[:, root, 4], poses[:, root, 5]  # quaternion is w, x, y, z
    up = np.clip(1.0 - 2.0 * (x * x + y * y), -1.0, 1.0)
    return np.degrees(np.arccos(up))


def _overlay_array(poses: np.ndarray, root: int) -> np.ndarray:
    overlay = np.full((len(poses), OVERLAY_STRIDE), np.nan, dtype=np.float32)
    overlay[:, 18] = 0.0  # no shove
    overlay[:, 19:22] = poses[:, root, :3]
    return overlay


def _root_index(creature: CreatureSpec) -> int:
    child_ids = {joint.child for joint in creature.joints}
    for index, part in enumerate(creature.parts):
        if part.id not in child_ids:
            return index
    return 0


def describe(
    built_id: str,
    preset: str,
    goal_label: str,
    creature: CreatureSpec,
    frames: list[FrameState],
    *,
    fps: float,
    simulated: bool,
    score: float,
    forward: float,
    fell_at: float | None,
    headline: str,
    cause: str | None,
    evidence: list[dict],
) -> Built:
    """Assemble meshes, scene description, poses, overlay and the run-shaped summary."""
    meshes: dict[int, bytes] = {}
    geoms, mesh_info = [], []
    for index, part in enumerate(creature.parts):
        vertices, faces = part_mesh(part)
        meshes[index] = encode_mesh(vertices, faces)
        mesh_info.append({"id": index, "vertices": len(vertices), "faces": len(faces)})
        geoms.append(
            {
                "id": index,
                "body": index,
                "mesh": index,
                "pos": [0.0, 0.0, 0.0],
                "quat": [1.0, 0.0, 0.0, 0.0],
                "rgba": _color(part, index),
            }
        )
    poses = _poses_array(creature, frames)
    root = _root_index(creature)
    tilt = _tilt_degrees(poses, root)
    # The view frames by the body's own size (its widest spread of parts at any moment, so a
    # worm that stretches is not framed curled up), with a margin for the parts' thickness.
    spread = float((poses[:, :, :3].max(axis=1) - poses[:, :, :3].min(axis=1)).max())
    size_cm = max(spread * 100.0 * 1.35, 62.0)
    duration = round(len(frames) / fps, 3)
    stride = max(1, len(tilt) // 260)
    outcome = "fell" if fell_at is not None else "walked"
    scene = {
        "robot": built_id,
        "bodyCount": len(creature.parts),
        "poseStride": POSE_STRIDE,
        "geoms": geoms,
        "meshes": mesh_info,
    }
    detail = {
        "id": built_id,
        "robot": built_id,
        "policy": "preset",
        "policyTitle": presets.preset_label(preset),
        "title": goal_label if simulated else "Resting pose",
        "kind": "other",
        "outcome": outcome,
        "outcomeText": headline,
        "verdict": headline,
        "fallAt": fell_at,
        "recoveredAt": None,
        "distance": round(forward, 2),
        "pushN": 0.0,
        "pair": None,
        "fps": fps,
        "frames": len(frames),
        "duration": duration,
        "scenario": {},
        "cause": None,
        "causeText": cause,
        "evidence": evidence,
        "peakTiltDeg": round(float(tilt.max()), 1),
        "events": {
            "pushAt": None,
            "pushFor": 0.2,
            "pushN": 0.0,
            "pushSide": "left",
            "fallAt": fell_at,
            "recoveredAt": None,
        },
        "tilt": [round(float(v), 1) for v in tilt[::stride]],
        "credit": "Creature Lab preset",
        "sizeCm": round(size_cm, 1),
        "score": round(score, 3),
        "simulated": simulated,
    }
    return Built(
        id=built_id,
        scene=scene,
        meshes=meshes,
        poses=poses.astype("<f4").tobytes(),
        overlay=_overlay_array(poses, root).astype("<f4").tobytes(),
        detail=detail,
    )


# ---- presets, building and running ---------------------------------------------------------------


def preset_catalog() -> dict:
    return {
        "presets": [
            {
                "key": name,
                "label": preset.label,
                "params": [
                    {
                        "key": p.key,
                        "label": p.label,
                        "min": p.minimum,
                        "max": p.maximum,
                        "step": p.step,
                        "initial": p.initial,
                        "integer": p.kind == "int",
                    }
                    for p in preset.params
                ],
            }
            for name, preset in presets.CREATURE_PRESETS.items()
        ],
        "goals": [
            {"key": key, "label": label} for key, (label, _task) in presets.ONBOARDING_GOALS.items()
        ],
    }


def clean_params(preset: str, given: dict[str, Any] | None) -> dict[str, float]:
    """The preset's own parameters, each clamped to its range; anything else is dropped."""
    if preset not in presets.CREATURE_PRESETS:
        raise CreatureError(f"unknown preset {preset!r}")
    out: dict[str, float] = {}
    for spec in presets.CREATURE_PRESETS[preset].params:
        raw = (given or {}).get(spec.key, spec.initial)
        try:
            value = float(raw)
        except (TypeError, ValueError):
            value = spec.initial
        if not math.isfinite(value):
            value = spec.initial
        value = min(max(value, spec.minimum), spec.maximum)
        out[spec.key] = float(round(value)) if spec.kind == "int" else value
    return out


def _backend():
    """PyBullet if installed, else MuJoCo; the same creature runs on either."""
    try:
        from creature_lab.backends.pybullet_backend import PyBulletBackend, backend_version

        return PyBulletBackend, backend_version(), "pybullet"
    except ImportError:
        pass
    try:
        from creature_lab.backends.mujoco_backend import MuJoCoBackend, backend_version

        return MuJoCoBackend, backend_version(), "mujoco"
    except ImportError as error:
        raise EngineMissing(
            "Building a creature needs a physics engine: uv sync --inexact --extra sim"
        ) from error


class Designer:
    """Builds previews and runs, keeping the last few so the browser can fetch their parts."""

    def __init__(self) -> None:
        self._built: OrderedDict[str, Built] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, built_id: str) -> Built:
        try:
            return self._built[built_id]
        except KeyError:
            raise NoSuchCreature("that creature is no longer available") from None

    def _keep(self, built: Built) -> Built:
        self._built[built.id] = built
        while len(self._built) > _KEEP:
            self._built.popitem(last=False)
        return built

    def build(
        self, preset: str, params: dict[str, Any] | None, goal: str, *, simulate: bool
    ) -> Built:
        """A resting preview of the creature, or a simulated run of it toward a goal."""
        values = clean_params(preset, params)
        if goal not in presets.ONBOARDING_GOALS:
            raise CreatureError(f"unknown goal {goal!r}")
        goal_label, task_name = presets.ONBOARDING_GOALS[goal]
        creature = presets.generate_creature(preset, values)
        task = presets.generate_task(task_name)
        backend_cls, version, backend_name = _backend()
        built_id = uuid.uuid4().hex[:12]
        with self._lock:
            if simulate:
                built = self._simulate(
                    built_id, preset, goal_label, creature, task, backend_name, backend_cls
                )
            else:
                sim = backend_cls(gui=False)
                try:
                    sim.build(creature, task, seed=0)
                    frames = [sim.step(task.timestep)]
                finally:
                    sim.close()
                built = describe(
                    built_id,
                    preset,
                    goal_label,
                    creature,
                    frames,
                    fps=1.0 / task.timestep,
                    simulated=False,
                    score=0.0,
                    forward=0.0,
                    fell_at=None,
                    headline="Resting pose",
                    cause=None,
                    evidence=[],
                )
        built.creature = {"preset": preset, "params": values, "goal": goal, "backend": version}
        built.detail["backend"] = backend_name
        from creature_lab.cli import _curated_controller

        built.spec, built.task = creature, task
        built.controller, built.backend_name = _curated_controller(creature), backend_name
        return self._keep(built)

    # ---- follow-up tests on a built creature ---------------------------------------------
    def _testable(self, built_id: str) -> Built:
        built = self.get(built_id)
        if built.spec is None or built.task is None:
            raise NoSuchCreature("that creature cannot be tested any more")
        return built

    def shove(self, built_id: str) -> dict:
        """Shove the creature from each side at rising strengths: how hard before it topples."""
        built = self._testable(built_id)
        with self._lock:
            return shoves.shove_test(built.spec, built.task, built.controller, built.backend_name)

    def improve(self, built_id: str, tries: int = 30) -> dict:
        """Try small changes to the design's sliders and offer one only if it is clearly better."""
        base = self._testable(built_id)
        meta = base.creature
        with self._lock:
            found = shoves.improve(
                meta["preset"], meta["params"], base.task, base.backend_name, tries=tries
            )
        out: dict = {
            "improved": found.values is not None,
            "tried": found.tried,
            "before": found.before,
            "after": found.after,
            "changes": [],
        }
        if found.values is None:
            return out
        spec = {p.key: p for p in presets.CREATURE_PRESETS[meta["preset"]].params}
        out["changes"] = [
            {"key": key, "label": spec[key].label, "from": meta["params"][key], "to": value}
            for key, value in found.values.items()
            if value != meta["params"][key]
        ]
        built = self.build(meta["preset"], found.values, meta["goal"], simulate=True)
        out.update(
            {"scene": built.scene, "run": built.detail, "creature": built.creature, "id": built.id}
        )
        return out

    def export(self, built_id: str, fmt: str) -> tuple[str, str, str]:
        """The creature as a file to keep: (text, media type, file name)."""
        from creature_lab.export.mjcf import export_mjcf
        from creature_lab.export.urdf import export_urdf

        built = self._testable(built_id)
        creature, task = built.spec, built.task
        name = "".join(c if c.isalnum() or c in "-_" else "_" for c in creature.name) or "creature"
        if fmt == "json":
            return creature.model_dump_json(indent=2), "application/json", f"{name}.json"
        if fmt == "mjcf":
            text = export_mjcf(creature, friction=task.terrain.friction, timestep=task.timestep)
            return text, "application/xml", f"{name}.xml"
        if fmt == "urdf":
            return export_urdf(creature), "application/xml", f"{name}.urdf"
        raise CreatureError(f"unknown export format {fmt!r} (choose json, mjcf or urdf)")

    def _simulate(self, built_id, preset, goal_label, creature, task, backend_name, backend_cls):
        from creature_lab.cli import _curated_controller, _simulate
        from creature_lab.diagnosis import first_fall_time
        from creature_lab.diagnostics import summarize_episode

        controller = _curated_controller(creature)
        trace = _simulate(creature, task, seed=0, controller=controller, backend=backend_name)
        summary = summarize_episode(trace, task, creature)
        fell_at = first_fall_time(trace, creature)
        result = diagnose(trace, creature, task)
        moved = summary.forward_displacement
        if fell_at is not None:
            headline = f"Fell at {fell_at:.1f} s"
        elif task.target is not None and summary.target_progress is not None:
            headline = f"Got {summary.target_progress * 100:.0f}% of the way to the target"
        else:
            headline = f"Moved {moved:.2f} m and stayed upright"
        cause = result.explanations[0] if result.explanations else None
        evidence = [
            {"label": "Score", "value": f"{trace.score:.2f}", "detail": "the task's reward"},
            {
                "label": "Moved forward",
                "value": f"{moved:.2f} m",
                "detail": "net distance along the forward axis",
            },
            {
                "label": "Stayed upright",
                "value": "No" if fell_at is not None else "Yes",
                "detail": "whether the body toppled",
            },
        ]
        if result.suggestions:
            evidence.append(
                {"label": "Try", "value": result.suggestions[0], "detail": "a suggested change"}
            )
        return describe(
            built_id,
            preset,
            goal_label,
            creature,
            list(trace.frames),
            fps=1.0 / task.timestep,
            simulated=True,
            score=float(trace.score),
            forward=float(moved),
            fell_at=fell_at,
            headline=headline,
            cause=cause,
            evidence=evidence,
        )
