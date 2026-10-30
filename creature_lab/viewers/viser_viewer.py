"""Viser browser viewer for replaying or live-streaming creature motion.

This renders poses; it never runs physics. It consumes a stream of FrameState
objects (recorded or produced live by a backend), keeping the viewer
backend-agnostic per docs/archive/MVP_PLAN.md. The schema's scalar-first ``(w, x, y, z)``
quaternion matches Viser's ``wxyz``, so no conversion is needed here.

Viser is an optional dependency (the ``viz`` extra); import this module lazily.
"""

from __future__ import annotations

import math
import time
import webbrowser
from bisect import bisect_right
from collections import defaultdict, deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from creature_lab.schema import CreatureSpec, EpisodeTrace, FrameState, PartSpec, TaskSpec
from creature_lab.schema.creature import ShapeType

# Viser listens on every network interface unless told otherwise; this server has no sign-in,
# so bind to this computer only by default. Pass host="0.0.0.0" to share it on purpose.
DEFAULT_HOST = "127.0.0.1"
_DEFAULT_COLOR = (0.6, 0.6, 0.6)
_CONTACT_COLOR = (255, 60, 40)
_MAX_CONTACT_MARKERS = 16
_MIN_REACH = 0.15  # metres; keeps a single-part creature from framing to nothing


@dataclass
class SceneHandles:
    """Mutable Viser handles for a built scene."""

    parts: dict[str, Any]
    contacts: list[Any] = field(default_factory=list)
    extras: list[Any] = field(default_factory=list)
    floor: Any = None


def part_color_255(part: PartSpec) -> tuple[int, int, int]:
    """Convert a part's 0..1 RGB color to Viser's 0..255 integer triple."""
    rgb = part.color or _DEFAULT_COLOR
    return tuple(int(round(max(0.0, min(1.0, channel)) * 255)) for channel in rgb)


def _part_radius(part: PartSpec) -> float:
    """Rough half-extent of a part, for a bounding-reach estimate (not rendering)."""
    if part.shape == ShapeType.BOX and part.size is not None:
        return max(part.size) / 2
    if part.shape == ShapeType.SPHERE and part.radius is not None:
        return part.radius
    if part.radius is not None and part.length is not None:
        return max(part.radius, part.length / 2)
    return 0.05


def creature_reach(creature: CreatureSpec) -> float:
    """Rough max distance any part can be from the root, in the rest pose.

    Ignores joint rotations (unlike ``EditorSession.preview_frame``'s real forward
    kinematics) - this only has to be in the right ballpark to pick a camera
    distance or floor-grid size, not to place parts for rendering. Without any
    camera framing at all, a ~0.4 m creature was rendering as a barely-visible
    speck on a fixed 10x10 m grid (see docs/KNOWN_ISSUES.md).
    """
    child_to_joint = {joint.child: joint for joint in creature.joints}
    children: dict[str, list] = defaultdict(list)
    for joint in creature.joints:
        children[joint.parent].append(joint.child)
    roots = [part.id for part in creature.parts if part.id not in child_to_joint]
    if not roots:
        return _MIN_REACH
    parts_by_id = {part.id: part for part in creature.parts}
    root = roots[0]
    reach = {root: _part_radius(parts_by_id[root])}
    max_reach = reach[root]
    queue: deque[str] = deque([root])
    while queue:
        parent = queue.popleft()
        for child in children[parent]:
            anchor = child_to_joint[child].anchor
            anchor_length = math.sqrt(sum(component * component for component in anchor))
            child_reach = reach[parent] + anchor_length + _part_radius(parts_by_id[child])
            reach[child] = child_reach
            max_reach = max(max_reach, child_reach)
            queue.append(child)
    return max(max_reach, _MIN_REACH)


def _add_part(scene: Any, name: str, part: PartSpec) -> Any:
    color = part_color_255(part)
    if part.shape == ShapeType.BOX:
        if part.size is None:
            raise ValueError("box part is missing size")
        return scene.add_box(name, color=color, dimensions=tuple(part.size))
    if part.shape == ShapeType.SPHERE:
        if part.radius is None:
            raise ValueError("sphere part is missing radius")
        return scene.add_icosphere(name, radius=part.radius, color=color)
    if part.radius is None or part.length is None:
        raise ValueError("capsule/cylinder part is missing radius or length")
    if part.shape == ShapeType.CYLINDER:
        # Native Viser cylinder, along the local z axis (matches the schema/backend).
        return scene.add_cylinder(name, radius=part.radius, height=part.length, color=color)
    # Capsule: Viser has no native primitive, so build a true capsule mesh (rounded
    # ends) with trimesh — matching the PyBullet export. trimesh ships with the viz extra.
    import numpy as np
    import trimesh

    centered = trimesh.transformations.translation_matrix((0.0, 0.0, -part.length / 2))
    mesh = trimesh.creation.capsule(height=part.length, radius=part.radius, transform=centered)
    mesh.visual.vertex_colors = np.array([*color, 255], dtype=np.uint8)
    return scene.add_mesh_trimesh(name, mesh)


def _add_floor(
    server: Any, task: TaskSpec | None, creature: CreatureSpec | None = None, *, prefix: str = ""
) -> Any:
    """Draw the ground: a flat grid, or a mesh built from the task's terrain heightfield.

    Without this, replaying a non-flat-terrain run would show the creature floating
    above (or sinking into) a flat floor instead of the slope/steps/gaps it actually ran on.
    Returns the Viser handle (a grid or a mesh), mainly so tests can tell which was drawn.

    The flat-plane grid is sized from ``creature`` (when given) instead of a fixed
    10x10 m, so a small creature isn't rendered as a speck on an oversized grid -
    this is purely a rendering choice; the non-flat heightfield mesh below stays at
    its fixed physics-accurate extent (see docs/KNOWN_ISSUES.md) and is untouched.
    """
    from creature_lab.terrain import is_flat

    if task is None or is_flat(task.terrain):
        size = 10.0 if creature is None else max(2.0, creature_reach(creature) * 8)
        return server.scene.add_grid(
            f"{prefix}/floor",
            width=size,
            height=size,
            plane="xy",
            cell_color=(193, 202, 215),
            section_color=(165, 178, 194),
            plane_color=(231, 236, 243),
            plane_opacity=0.85,
            cell_size=max(0.1, size / 20),
            section_size=max(0.5, size / 4),
            shadow_opacity=0.25,
        )

    import numpy as np
    import trimesh

    from creature_lab.terrain import DEFAULT_CELL_SIZE, heightfield_grid

    grid = heightfield_grid(task.terrain)
    rows, cols = len(grid), len(grid[0])
    x0 = -(rows * DEFAULT_CELL_SIZE) / 2
    y0 = -(cols * DEFAULT_CELL_SIZE) / 2
    vertices = np.array(
        [
            (x0 + r * DEFAULT_CELL_SIZE, y0 + c * DEFAULT_CELL_SIZE, grid[r][c])
            for r in range(rows)
            for c in range(cols)
        ]
    )
    faces = []
    for r in range(rows - 1):
        for c in range(cols - 1):
            top_left, top_right = r * cols + c, r * cols + c + 1
            bottom_left, bottom_right = (r + 1) * cols + c, (r + 1) * cols + c + 1
            faces.append((top_left, bottom_left, bottom_right))
            faces.append((top_left, bottom_right, top_right))
    mesh = trimesh.Trimesh(vertices=vertices, faces=np.array(faces))
    mesh.visual.vertex_colors = np.array([140, 140, 140, 255], dtype=np.uint8)
    return server.scene.add_mesh_trimesh(f"{prefix}/floor", mesh)


def build_scene(
    server: Any,
    creature: CreatureSpec,
    task: TaskSpec | None = None,
    *,
    max_contacts: int = _MAX_CONTACT_MARKERS,
    prefix: str = "",
    add_floor: bool = True,
    offset: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> SceneHandles:
    """Add a floor, optional target, one handle per part, and a contact-marker pool.

    ``prefix`` namespaces every node (``/<prefix>/parts/...``) so several creatures
    can share one server (used by ``compare``); ``add_floor`` lets the caller draw a
    single shared floor.
    """
    floor = _add_floor(server, task, creature, prefix=prefix) if add_floor else None
    if floor is not None:
        floor.position = offset
    extras: list[Any] = []
    if task is not None and task.target is not None:
        target = server.scene.add_icosphere(
            f"{prefix}/target", radius=task.target.radius, color=(255, 180, 40)
        )
        target.position = tuple(task.target.position[i] + offset[i] for i in range(3))
        extras.append(target)
    from creature_lab.viewers.appearance import decorations, visual_part

    parts = {
        part.id: _add_part(server.scene, f"{prefix}/parts/{part.id}", visual_part(creature, part))
        for part in creature.parts
    }
    for detail in decorations(creature):
        name = f"{prefix}/parts/{detail.part}/{detail.name}"
        color = tuple(round(channel * 255) for channel in detail.color)
        if detail.shape == "box":
            handle = server.scene.add_box(name, dimensions=detail.size, color=color)
        else:
            handle = server.scene.add_icosphere(name, radius=detail.size[0], color=color)
        handle.position = detail.position
        extras.append(handle)
    # A fixed pool of contact dots, shown/hidden per frame as contacts come and go.
    contacts = []
    for index in range(max_contacts):
        marker = server.scene.add_icosphere(
            f"{prefix}/contacts/{index}", radius=0.03, color=_CONTACT_COLOR
        )
        marker.visible = False
        contacts.append(marker)
    return SceneHandles(parts=parts, contacts=contacts, extras=extras, floor=floor)


def remove_scene(handles: SceneHandles | None) -> None:
    """Remove all Viser handles created by ``build_scene``."""
    if handles is None:
        return
    all_handles = [*handles.parts.values(), *handles.contacts, *handles.extras]
    if handles.floor is not None:
        all_handles.append(handles.floor)
    for handle in all_handles:
        try:
            handle.remove()
        except Exception:
            # Best-effort cleanup: stale Viser handles should not make a refresh fail.
            pass


def add_debug_overlays(
    server: Any, creature: CreatureSpec, trace: EpisodeTrace, task: TaskSpec | None = None
) -> Any:
    """Draw static debug overlays: CoM trail, root ground path, and a fall marker.

    ``task`` places the root-path dots on the actual terrain surface instead of a flat
    z=0 plane, so they don't appear to float above a slope or sink into a gap. Returns
    the root-path point-cloud handle (or ``None``), mainly so tests can inspect it.
    """
    import numpy as np

    from creature_lab.diagnosis import diagnose
    from creature_lab.schema.task import TerrainSpec
    from creature_lab.terrain import height_at
    from creature_lab.viewers.overlays import center_of_mass_trail, root_path

    com = center_of_mass_trail(creature, trace)
    if com:
        server.scene.add_point_cloud(
            "/debug/com_trail",
            points=np.asarray(com, dtype=np.float32),
            colors=(40, 200, 255),
            point_size=0.02,
        )
    path = root_path(creature, trace)
    root_path_handle = None
    if path:
        terrain = task.terrain if task is not None else TerrainSpec()
        floor_path = np.asarray(
            [(x, y, height_at(terrain, x, y) + 0.005) for x, y, _ in path], dtype=np.float32
        )
        root_path_handle = server.scene.add_point_cloud(
            "/debug/root_path", points=floor_path, colors=(255, 220, 40), point_size=0.015
        )
    # Mark where the body first toppled, if it did.
    result = diagnose(trace, creature)
    fall_time = result.metrics.get("fall_time", -1.0)
    if fall_time >= 0 and com:
        index = min(range(len(trace.frames)), key=lambda i: abs(trace.frames[i].t - fall_time))
        marker = server.scene.add_icosphere("/debug/fall", radius=0.06, color=(255, 40, 40))
        marker.position = com[index]

    return root_path_handle


def apply_frame(
    handles: SceneHandles,
    frame: FrameState,
    *,
    offset: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> None:
    """Move part handles to their poses and show contact markers for this frame.

    ``offset`` shifts the whole creature (used by ``compare`` to place two runs
    side by side in one scene).
    """

    def shift(position: tuple[float, float, float]) -> tuple[float, float, float]:
        return (position[0] + offset[0], position[1] + offset[1], position[2] + offset[2])

    for part_id, pose in frame.parts.items():
        handle = handles.parts.get(part_id)
        if handle is not None:
            handle.position = shift(pose.position)
            handle.wxyz = pose.orientation
    for index, marker in enumerate(handles.contacts):
        if index < len(frame.contacts):
            marker.position = shift(frame.contacts[index].position)
            marker.visible = True
        else:
            marker.visible = False


def recorded_replay_html(
    creature: CreatureSpec,
    trace: EpisodeTrace,
    *,
    task: TaskSpec | None = None,
    on_frame: Callable[[int, int], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> str:
    """Serialize recorded poses into Viser's experimental standalone 3D player.

    This opens an isolated loopback server only while serializing; it never
    mutates the live editor scene or re-simulates the episode.
    """
    import viser

    server = viser.ViserServer(host="127.0.0.1", port=0, verbose=False)
    try:
        reach = creature_reach(creature)
        server.initial_camera.position = (reach * 1.54, -reach * 1.54, reach * 1.56)
        server.initial_camera.look_at = (0.0, 0.0, reach * 0.35)
        handles = build_scene(server, creature, task)
        serializer = server.get_scene_serializer()
        previous = trace.frames[0].t
        for index, frame in enumerate(trace.frames):
            if should_stop is not None and should_stop():
                raise InterruptedError("Replay export cancelled")
            serializer.insert_sleep(max(0.0, frame.t - previous))
            apply_frame(handles, frame)
            previous = frame.t
            if on_frame is not None:
                on_frame(index + 1, len(trace.frames))
        return serializer.as_html(dark_mode=True)
    finally:
        server.stop()


def stream_frames(
    creature: CreatureSpec,
    frames: Iterable[FrameState],
    *,
    task: TaskSpec | None = None,
    fps: float = 30.0,
    host: str = DEFAULT_HOST,
    port: int = 8080,
    hold: bool = True,
    open_browser: bool = False,
    debug_trace: EpisodeTrace | None = None,
) -> list[FrameState]:
    """Open a Viser server and animate `frames` as they arrive.

    `frames` may be a live generator (e.g. a running simulation) or a recorded
    sequence. Frames are captured as they play; when the stream ends and `hold`
    is true, the captured frames loop so the scene keeps moving until interrupted.
    Returns the captured frames so a caller can save them as a trace. When
    ``debug_trace`` is given, static debug overlays (CoM/root trails, fall marker)
    are drawn from it before animating.
    """
    import viser

    server = viser.ViserServer(host=host, port=port)
    if open_browser:
        webbrowser.open(f"http://localhost:{port}", new=2)
    handles = build_scene(server, creature, task)
    if debug_trace is not None:
        add_debug_overlays(server, creature, debug_trace, task)
    delay = 1.0 / fps
    captured: list[FrameState] = []
    try:
        for frame in frames:
            apply_frame(handles, frame)
            captured.append(frame)
            time.sleep(delay)
        while hold and captured:
            for frame in captured:
                apply_frame(handles, frame)
                time.sleep(delay)
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
    return captured


def play_trace(
    creature: CreatureSpec,
    trace: EpisodeTrace,
    *,
    task: TaskSpec | None = None,
    fps: float = 30.0,
    loop: bool = True,
    host: str = DEFAULT_HOST,
    port: int = 8080,
    debug: bool = False,
    open_browser: bool = False,
) -> None:
    """Open a Viser server and animate a recorded trace. Blocks until interrupted."""
    stream_frames(
        creature,
        trace.frames,
        task=task,
        fps=fps,
        host=host,
        port=port,
        hold=loop,
        open_browser=open_browser,
        debug_trace=trace if debug else None,
    )


def compare_traces(
    creature_a: CreatureSpec,
    trace_a: EpisodeTrace,
    creature_b: CreatureSpec,
    trace_b: EpisodeTrace,
    *,
    task_a: TaskSpec | None = None,
    task_b: TaskSpec | None = None,
    gap: float = 1.0,
    fps: float = 30.0,
    host: str = DEFAULT_HOST,
    port: int = 8080,
    hold: bool = True,
    open_browser: bool = False,
) -> None:
    """Replay both runs at the same recorded simulation time, with separate terrain."""
    import viser

    from creature_lab.terrain import DEFAULT_CELL_SIZE, DEFAULT_COLS, is_flat

    if fps <= 0:
        raise ValueError("fps must be positive")
    times_a = [frame.t for frame in trace_a.frames]
    times_b = [frame.t for frame in trace_b.frames]
    if times_a != sorted(times_a) or times_b != sorted(times_b):
        raise ValueError("comparison requires traces with nondecreasing frame times")

    def floor_width(creature: CreatureSpec, task: TaskSpec | None) -> float:
        if task is not None and not is_flat(task.terrain):
            return DEFAULT_COLS * DEFAULT_CELL_SIZE
        return max(2.0, creature_reach(creature) * 8)

    spacing = max(
        gap, (floor_width(creature_a, task_a) + floor_width(creature_b, task_b)) / 2 + 0.2
    )
    offset_a = (0.0, spacing / 2, 0.0)
    offset_b = (0.0, -spacing / 2, 0.0)

    server = viser.ViserServer(host=host, port=port)
    frames_a, frames_b = trace_a.frames, trace_b.frames
    duration = max(times_a[-1], times_b[-1])
    n = math.ceil(duration * fps)
    delay = 1.0 / fps
    try:
        handles_a = build_scene(server, creature_a, task_a, prefix="/a", offset=offset_a)
        handles_b = build_scene(server, creature_b, task_b, prefix="/b", offset=offset_b)
        if open_browser:
            webbrowser.open(f"http://localhost:{port}", new=2)
        while True:
            for i in range(n + 1):
                t = min(i / fps, duration)
                index_a = max(0, bisect_right(times_a, t) - 1)
                index_b = max(0, bisect_right(times_b, t) - 1)
                apply_frame(handles_a, frames_a[index_a], offset=offset_a)
                apply_frame(handles_b, frames_b[index_b], offset=offset_b)
                time.sleep(delay)
            if not hold:
                break
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
