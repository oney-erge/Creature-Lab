"""A robot's visible meshes and a run's per-frame body poses, as data a browser can draw."""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

import mujoco
import numpy as np

from creature_lab.robots.analysis import extrapolated_com
from creature_lab.robots.types import SUPPORT_VERTICES, RobotRun
from creature_lab.robots.visual import (
    geom_rgba,
    mesh_arrays,
    primitive_arrays,
    primitive_geoms,
    visual_mesh_geoms,
)

#: Floats per frame in the pose stream: position (3) then quaternion w, x, y, z (4).
POSE_STRIDE = 7
#: Floats per frame in the overlay stream, in this order: the outline of the feet
#: (``SUPPORT_VERTICES`` x/y pairs, NaN-padded), the extrapolated centre of mass (2), the
#: sideways shove force (1) and the trunk position (3).
OVERLAY_STRIDE = SUPPORT_VERTICES * 2 + 2 + 1 + 3


@dataclass
class SceneData:
    """The drawable parts of one robot model."""

    robot: str
    model: Any
    #: MuJoCo body ids that carry a visible mesh; poses are streamed in this order.
    bodies: list[int]
    #: One entry per visible mesh geom: its body (index into ``bodies``), mesh, pose, colour.
    geoms: list[dict]
    meshes: dict[int, tuple[np.ndarray, np.ndarray]] = field(default_factory=dict)

    @classmethod
    def from_model(cls, robot: str, model: Any) -> SceneData:
        bodies: list[int] = []
        geoms: list[dict] = []
        meshes: dict[int, tuple[np.ndarray, np.ndarray]] = {}
        drawn = visual_mesh_geoms(model)
        # A robot built from boxes and capsules has no meshes to draw. Published robots keep such
        # shapes as hidden collision geoms beside their meshes, so they are drawn only when alone.
        from_shapes = not drawn
        for geom in drawn or primitive_geoms(model):
            body = int(model.geom_bodyid[geom])
            if body not in bodies:
                bodies.append(body)
            if from_shapes:
                # One entry per shape, numbered after the model's real meshes.
                mesh_id = int(model.nmesh) + int(geom)
                meshes[mesh_id] = primitive_arrays(model, geom)
            else:
                mesh_id = int(model.geom_dataid[geom])
                if mesh_id not in meshes:
                    meshes[mesh_id] = mesh_arrays(model, mesh_id)
            geoms.append(
                {
                    "id": int(geom),
                    "body": bodies.index(body),
                    "mesh": mesh_id,
                    "pos": [float(v) for v in model.geom_pos[geom]],
                    "quat": [float(v) for v in model.geom_quat[geom]],
                    "rgba": [round(float(v), 4) for v in geom_rgba(model, geom)],
                }
            )
        return cls(robot, model, bodies, geoms, meshes)

    def description(self) -> dict:
        """The JSON the browser needs to build the robot before any pose arrives."""
        return {
            "robot": self.robot,
            "bodyCount": len(self.bodies),
            "poseStride": POSE_STRIDE,
            "geoms": self.geoms,
            "meshes": [
                {"id": mesh_id, "vertices": len(v), "faces": len(f)}
                for mesh_id, (v, f) in sorted(self.meshes.items())
            ],
        }

    def mesh_payload(self, mesh_id: int) -> bytes:
        """Little-endian: uint32 vertices, uint32 faces, float32[n*3], uint32[m*3]."""
        vertices, faces = self.meshes[mesh_id]
        header = struct.pack("<II", len(vertices), len(faces))
        return header + vertices.astype("<f4").tobytes() + faces.astype("<u4").tobytes()

    def pose_payload(self, run: RobotRun) -> bytes:
        """Float32 array of shape (frames, bodies, 7): where every body is at every frame."""
        model, data = self.model, mujoco.MjData(self.model)
        poses = np.empty((len(run), len(self.bodies), POSE_STRIDE), dtype="<f4")
        for frame in range(len(run)):
            data.qpos[:] = run.qpos[frame]
            mujoco.mj_kinematics(model, data)
            poses[frame, :, :3] = data.xpos[self.bodies]
            poses[frame, :, 3:] = data.xquat[self.bodies]
        return poses.tobytes()


def overlay_payload(run: RobotRun) -> bytes:
    """Float32 array of shape (frames, ``OVERLAY_STRIDE``): the data behind the 3D markers."""
    frames = len(run)
    out = np.empty((frames, OVERLAY_STRIDE), dtype="<f4")
    out[:, : SUPPORT_VERTICES * 2] = run.support.reshape(frames, -1)
    out[:, SUPPORT_VERTICES * 2 : SUPPORT_VERTICES * 2 + 2] = extrapolated_com(run)
    out[:, SUPPORT_VERTICES * 2 + 2] = run.push_force
    out[:, SUPPORT_VERTICES * 2 + 3 :] = run.trunk_pos
    return out.tobytes()


def _load_model(robot: str) -> Any:
    from creature_lab.robots.render import scene_file

    return mujoco.MjModel.from_xml_path(str(scene_file(robot)))


@lru_cache(maxsize=4)
def load_scene(robot: str) -> SceneData:
    """The robot's drawable scene (needs the robot downloaded); cached per process."""
    return SceneData.from_model(robot, _load_model(robot))
