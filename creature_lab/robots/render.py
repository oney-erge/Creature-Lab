"""Film a recorded robot run: studio lighting, follow camera, shove and balance markers."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import mujoco
import numpy as np

from creature_lab.robots.analysis import balance_margin_cm
from creature_lab.robots.fetch import robot_dir
from creature_lab.robots.scene import write_studio_scene
from creature_lab.robots.types import CONTROL_HZ, RobotRun

_SCENE_FILES = {
    "microduck": ("Microduck", "robot_groundcontact.xml", 0.12),
    "unitree_g1": ("Unitree G1", "g1_12dof.xml", 0.5),
}

#: Marker colours (rgba).
_SHOVE = (1.0, 0.45, 0.18, 0.92)
_SUPPORT_OK = (0.12, 0.62, 0.55, 0.9)
_SUPPORT_WARN = (0.90, 0.22, 0.20, 0.9)
_BALANCE = (0.99, 0.80, 0.20, 0.95)
#: Height of each robot relative to Microduck, used to size markers.
_UNIT = {"microduck": 1.0, "unitree_g1": 5.2}
#: Shove strength that draws a mid-length arrow.
_SHOVE_REFERENCE_N = {"microduck": 4.0, "unitree_g1": 150.0}


def scene_file(robot: str):
    """Path of the robot's studio scene (written on demand next to its downloaded files)."""
    name, robot_file, tile = _SCENE_FILES[robot]
    return write_studio_scene(robot_dir(robot), name, robot_file, tile_m=tile)


@dataclass
class Shot:
    """How the camera frames the robot."""

    distance: float
    elevation: float = -14.0
    azimuth_start: float = 128.0
    azimuth_end: float = 152.0
    #: Height of the point the camera looks at, as a fraction of ``distance``.
    look_height: float = 0.16
    #: How quickly the camera catches up with the robot (per second).
    follow_rate: float = 3.0
    markers: bool = True


SHOTS = {
    "microduck": Shot(distance=0.62, look_height=0.12),
    "unitree_g1": Shot(distance=2.5, look_height=0.34),
}


@dataclass
class Studio:
    """An offscreen MuJoCo renderer bound to one robot's studio scene."""

    robot: str
    width: int = 1280
    height: int = 720
    shot: Shot | None = None
    model: mujoco.MjModel = field(init=False)
    data: mujoco.MjData = field(init=False)

    def __post_init__(self) -> None:
        self.model = mujoco.MjModel.from_xml_path(str(scene_file(self.robot)))
        self.model.vis.global_.offwidth = max(self.width, int(self.model.vis.global_.offwidth))
        self.model.vis.global_.offheight = max(self.height, int(self.model.vis.global_.offheight))
        self.data = mujoco.MjData(self.model)
        self._renderer = mujoco.Renderer(self.model, self.height, self.width)
        self._option = mujoco.MjvOption()
        self._camera = mujoco.MjvCamera()
        self._camera.type = mujoco.mjtCamera.mjCAMERA_FREE
        self.shot = self.shot or SHOTS[self.robot]
        self._focus: np.ndarray | None = None
        self._last_time = 0.0

    def close(self) -> None:
        self._renderer.close()

    def __enter__(self) -> Studio:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def reset_camera(self) -> None:
        self._focus = None

    # ---- state ---------------------------------------------------------------------------
    def _qpos_at(self, run: RobotRun, time_s: float) -> np.ndarray:
        """Joint state at an arbitrary time, interpolated between 50 Hz frames."""
        position = np.clip(time_s * CONTROL_HZ - 1.0, 0.0, len(run) - 1.0)
        low = int(math.floor(position))
        high = min(low + 1, len(run) - 1)
        weight = position - low
        qpos = (1 - weight) * run.qpos[low] + weight * run.qpos[high]
        quaternion = qpos[3:7]
        norm = np.linalg.norm(quaternion)
        if norm > 0:
            qpos[3:7] = quaternion / norm
        return qpos

    def _frame_index(self, run: RobotRun, time_s: float) -> int:
        return int(np.clip(round(time_s * CONTROL_HZ) - 1, 0, len(run) - 1))

    # ---- drawing -------------------------------------------------------------------------
    def render(
        self,
        run: RobotRun,
        time_s: float,
        *,
        progress: float | None = None,
        margin_cm: np.ndarray | None = None,
        markers: bool | None = None,
        shift: float = 0.0,
    ) -> np.ndarray:
        """One RGB frame of ``run`` at ``time_s``. ``progress`` (0..1) drives the camera orbit.

        ``shift`` moves the robot sideways in the picture (fraction of the camera distance;
        positive puts it right of centre, leaving room for a headline on the left).
        """
        shot = self.shot
        qpos = self._qpos_at(run, time_s)
        self.data.qpos[:] = qpos
        mujoco.mj_forward(self.model, self.data)
        trunk = qpos[:3].copy()
        if self._focus is not None and not 0.0 <= time_s - self._last_time <= 0.5:
            self._focus = None  # scene change or seek: snap to the robot
        dt = time_s - self._last_time if self._focus is not None else 1.0
        self._last_time = time_s
        if self._focus is None:
            self._focus = trunk
        else:
            blend = 1.0 - math.exp(-shot.follow_rate * min(dt, 0.2))
            self._focus = self._focus + blend * (trunk - self._focus)
        lookat = self._focus.copy()
        lookat[2] = max(shot.look_height * shot.distance, 0.02)
        orbit = (time_s / run.scenario.seconds) if progress is None else progress
        azimuth = shot.azimuth_start + (shot.azimuth_end - shot.azimuth_start) * orbit
        if shift:
            heading = math.radians(azimuth)
            right = np.array([math.sin(heading), -math.cos(heading), 0.0])
            lookat -= right * shift * shot.distance
        self._camera.lookat[:] = lookat
        self._camera.distance = shot.distance
        self._camera.elevation = shot.elevation
        self._camera.azimuth = azimuth
        self._renderer.update_scene(self.data, self._camera, self._option)
        if shot.markers if markers is None else markers:
            self._draw_markers(run, time_s, margin_cm)
        return self._renderer.render().copy()

    def _draw_markers(self, run: RobotRun, time_s: float, margin_cm: np.ndarray | None) -> None:
        scene = self._renderer.scene
        index = self._frame_index(run, time_s)
        unit = _UNIT[self.robot]

        # Outline of the feet on the floor; red once the balance point is outside it.
        outline = run.support[index]
        outline = outline[~np.isnan(outline[:, 0])]
        inside = margin_cm is None or np.isnan(margin_cm[index]) or margin_cm[index] >= 0
        colour = _SUPPORT_OK if inside else _SUPPORT_WARN
        points = [np.array([x, y, 0.0015 * unit]) for x, y in outline]
        if len(points) > 1:
            for start, end in zip(points, points[1:] + points[:1], strict=False):
                _connector(scene, start, end, 0.0022 * unit, colour)
        elif points:
            _sphere(scene, points[0], 0.004 * unit, colour)

        # Where the body is heading (extrapolated centre of mass): a small disc on the floor.
        if len(outline):
            height = max(float(run.com[index, 2]), 0.05)
            target = run.com[index, :2] + run.com_vel[index, :2] / math.sqrt(9.81 / height)
            _disc(scene, np.array([target[0], target[1], 0.0015 * unit]), 0.011 * unit, _BALANCE)

        # The shove: a slim arrow pointing at the trunk while it lasts.
        force = float(run.push_force[index])
        if force != 0.0:
            trunk = run.trunk_pos[index]
            direction = np.array([0.0, math.copysign(1.0, force), 0.0])
            strength = min(abs(force) / _SHOVE_REFERENCE_N[self.robot], 2.0)
            length = (0.07 + 0.07 * strength) * unit
            head = trunk - direction * 0.05 * unit
            _connector(scene, head - direction * length, head, 0.0042 * unit, _SHOVE, arrow=True)


def _sphere(scene, position: np.ndarray, radius: float, rgba) -> None:
    if scene.ngeom >= scene.maxgeom:
        return
    geom = scene.geoms[scene.ngeom]
    mujoco.mjv_initGeom(
        geom,
        mujoco.mjtGeom.mjGEOM_SPHERE,
        np.array([radius, 0.0, 0.0]),
        np.asarray(position, dtype=float),
        np.eye(3).ravel(),
        np.array(rgba, dtype=np.float32),
    )
    scene.ngeom += 1


def _disc(scene, position: np.ndarray, radius: float, rgba) -> None:
    if scene.ngeom >= scene.maxgeom:
        return
    geom = scene.geoms[scene.ngeom]
    mujoco.mjv_initGeom(
        geom,
        mujoco.mjtGeom.mjGEOM_CYLINDER,
        np.array([radius, radius * 0.08, 0.0]),
        np.asarray(position, dtype=float),
        np.eye(3).ravel(),
        np.array(rgba, dtype=np.float32),
    )
    scene.ngeom += 1


def _connector(scene, start, end, width: float, rgba, *, arrow: bool = False) -> None:
    if scene.ngeom >= scene.maxgeom:
        return
    geom = scene.geoms[scene.ngeom]
    kind = mujoco.mjtGeom.mjGEOM_ARROW if arrow else mujoco.mjtGeom.mjGEOM_CAPSULE
    mujoco.mjv_initGeom(
        geom, kind, np.zeros(3), np.zeros(3), np.zeros(9), np.array(rgba, dtype=np.float32)
    )
    mujoco.mjv_connector(geom, kind, width, np.asarray(start, float), np.asarray(end, float))
    scene.ngeom += 1


def margins_for(run: RobotRun) -> np.ndarray:
    return balance_margin_cm(run)
