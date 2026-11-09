"""Which of a robot model's geoms are its visible meshes, and their vertex data.

Shared by every viewer that draws a published robot from its meshes (the browser app and the
build editor's 3D stage), so they agree on what "the robot" looks like.
"""

from __future__ import annotations

from typing import Any

import mujoco
import numpy as np

#: Geom groups that hold the visual meshes in the published models (the rest are collision).
VISUAL_GROUPS = (1, 2)


def visual_mesh_geoms(model: Any) -> list[int]:
    """Ids of the visible mesh geoms: the visual groups if any, else every visible mesh."""
    meshes = [
        geom
        for geom in range(model.ngeom)
        if model.geom_type[geom] == mujoco.mjtGeom.mjGEOM_MESH and model.geom_rgba[geom][3] > 0
    ]
    return [geom for geom in meshes if model.geom_group[geom] in VISUAL_GROUPS] or meshes


def mesh_arrays(model: Any, mesh_id: int) -> tuple[np.ndarray, np.ndarray]:
    """Vertices (n, 3) float32 and triangles (m, 3) uint32 of a compiled mesh."""
    v0, vn = int(model.mesh_vertadr[mesh_id]), int(model.mesh_vertnum[mesh_id])
    f0, fn = int(model.mesh_faceadr[mesh_id]), int(model.mesh_facenum[mesh_id])
    vertices = np.array(model.mesh_vert[v0 : v0 + vn], dtype=np.float32).reshape(-1, 3)
    faces = np.array(model.mesh_face[f0 : f0 + fn], dtype=np.uint32).reshape(-1, 3)
    return vertices, faces


def geom_rgba(model: Any, geom: int) -> np.ndarray:
    """The geom's colour as RGBA in 0..1 (its material's colour when it has one)."""
    material = int(model.geom_matid[geom])
    return np.array(model.mat_rgba[material] if material >= 0 else model.geom_rgba[geom])
