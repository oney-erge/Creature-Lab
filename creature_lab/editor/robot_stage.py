"""Draw a published robot's real meshes in the editor's 3D view, and replay saved runs on it.

Poses come from MuJoCo forward kinematics; each body becomes one Viser frame whose meshes
never change, so a replay only moves a few dozen frames per tick. MuJoCo is imported only when
a robot is shown, so the editor itself stays free of it.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np

from creature_lab.robots.visual import geom_rgba, mesh_arrays, visual_mesh_geoms

#: Camera distance from the robot, in metres, and the height it looks at (fraction of distance).
_FRAMING = {"microduck": (0.5, 0.2), "unitree_g1": (2.4, 0.32)}
_CONTROL_HZ = 50
#: Seconds a finished replay holds its last pose before looping.
_HOLD_S = 1.2


class RobotStage:
    """Shows one robot at a time on top of the editor's floor."""

    def __init__(self, server: Any, *, set_editor_visible: Callable[[bool], None]) -> None:
        self._server = server
        self._set_editor_visible = set_editor_visible
        self._nodes: list[Any] = []
        self._bodies: dict[int, Any] = {}
        self._model: Any = None
        self._data: Any = None
        self._robot: str | None = None
        self._run: Any = None
        self._clock = 0.0
        self._last_focus: np.ndarray | None = None
        self.follow = True

    @property
    def active(self) -> bool:
        return self._model is not None

    @property
    def robot(self) -> str | None:
        return self._robot

    @property
    def playing(self) -> bool:
        return self._run is not None

    # ---- showing a robot -----------------------------------------------------------------
    def show(self, robot_key: str, run: Any = None) -> None:
        """Load the robot's studio scene (downloaded files) and put it on the stage."""
        import mujoco

        from creature_lab.robots.render import scene_file

        self.load_model(mujoco.MjModel.from_xml_path(str(scene_file(robot_key))), robot_key)
        if run is not None:
            self.play(run)

    def load_model(self, model: Any, robot_key: str | None = None) -> None:
        """Replace whatever is on the stage with the visual meshes of ``model``."""
        import mujoco

        self.hide(restore_editor=False)
        self._model = model
        self._data = mujoco.MjData(model)
        self._robot = robot_key
        scene = self._server.scene
        root = scene.add_frame("/robot_stage", show_axes=False)
        self._nodes.append(root)
        visual = visual_mesh_geoms(model)
        for geom in visual:
            body = int(model.geom_bodyid[geom])
            if body not in self._bodies:
                frame = scene.add_frame(f"/robot_stage/body_{body}", show_axes=False)
                self._bodies[body] = frame
                self._nodes.append(frame)
            self._nodes.append(
                scene.add_mesh_trimesh(
                    f"/robot_stage/body_{body}/geom_{geom}",
                    _geom_mesh(model, geom),
                    wxyz=tuple(float(v) for v in model.geom_quat[geom]),
                    position=tuple(float(v) for v in model.geom_pos[geom]),
                )
            )
        self._set_editor_visible(False)
        self.pose(model.qpos0, frame_camera=True)

    def hide(self, restore_editor: bool = True) -> None:
        """Take the robot off the stage and bring the editor's creature back."""
        for node in self._nodes:
            try:
                node.remove()
            except Exception:
                pass  # a stale handle must not stop the editor from coming back
        self._nodes, self._bodies = [], {}
        self._model = self._data = self._robot = self._run = None
        self._last_focus = None
        if restore_editor:
            self._set_editor_visible(True)

    # ---- posing and replay ---------------------------------------------------------------
    def pose(self, qpos: np.ndarray, *, frame_camera: bool = False) -> None:
        """Move every body to where ``qpos`` puts it, and keep the camera on the robot."""
        import mujoco

        if self._model is None:
            return
        self._data.qpos[:] = qpos
        mujoco.mj_kinematics(self._model, self._data)
        for body, frame in self._bodies.items():
            frame.position = tuple(float(v) for v in self._data.xpos[body])
            frame.wxyz = tuple(float(v) for v in self._data.xquat[body])
        focus = np.array([qpos[0], qpos[1], 0.0])
        if frame_camera:
            self._frame_camera(focus)
        elif self.follow and self._last_focus is not None:
            self._move_camera(focus - self._last_focus)
        self._last_focus = focus

    def play(self, run: Any) -> None:
        """Replay a saved ``RobotRun`` in a loop."""
        self._run = run
        self._clock = 0.0
        self._last_focus = None
        self.pose(run.qpos[0], frame_camera=True)

    def stop(self) -> None:
        self._run = None

    def tick(self, dt: float) -> None:
        """Advance the replay by ``dt`` seconds (call from the editor's main loop)."""
        run = self._run
        if run is None or self._model is None:
            return
        self._clock += dt
        duration = len(run) / _CONTROL_HZ
        if self._clock >= duration + _HOLD_S:
            self._clock = 0.0
            self._last_focus = None
            self.pose(run.qpos[0], frame_camera=True)
            return
        index = min(int(self._clock * _CONTROL_HZ), len(run) - 1)
        self.pose(run.qpos[index])

    # ---- camera --------------------------------------------------------------------------
    def _frame_camera(self, focus: np.ndarray) -> None:
        distance, look_height = _FRAMING.get(self._robot or "", (1.0, 0.2))
        look_at = (float(focus[0]), float(focus[1]), look_height * distance)
        position = (
            look_at[0] + distance * 0.75,
            look_at[1] - distance * 0.75,
            look_at[2] + distance * 0.45,
        )
        self._server.initial_camera.position = position
        self._server.initial_camera.look_at = look_at
        for client in self._server.get_clients().values():
            client.camera.position = position
            client.camera.look_at = look_at

    def _move_camera(self, delta: np.ndarray) -> None:
        if not np.any(delta):
            return
        for client in self._server.get_clients().values():
            camera = client.camera
            camera.position = tuple(np.asarray(camera.position) + delta)
            camera.look_at = tuple(np.asarray(camera.look_at) + delta)


def _geom_mesh(model: Any, geom: int) -> Any:
    """A colored trimesh of one mesh geom, in the geom's own frame."""
    import trimesh

    vertices, faces = mesh_arrays(model, int(model.geom_dataid[geom]))
    colour = np.clip(geom_rgba(model, geom) * 255, 0, 255).astype(np.uint8)
    mesh = trimesh.Trimesh(vertices=vertices.astype(float), faces=faces.astype(int), process=False)
    mesh.visual.vertex_colors = np.tile(colour, (len(vertices), 1))
    return mesh
