"""Which of a robot model's geoms are its visible meshes, and their vertex data.

Shared by every viewer that draws a published robot from its meshes (the browser app and the
build editor's 3D stage), so they agree on what "the robot" looks like.
"""

from __future__ import annotations

from typing import Any

import numpy as np

#: Geom groups that hold the visual meshes in the published models (the rest are collision).
VISUAL_GROUPS = (1, 2)


def visual_mesh_geoms(model: Any) -> list[int]:
    """Ids of the visible mesh geoms: the visual groups if any, else every visible mesh."""
    import mujoco  # here, not at import: the editor imports this module without MuJoCo installed

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


#: The shapes MuJoCo builds from a few numbers, which the app draws when a model has no meshes.
_PRIMITIVES = ("BOX", "CAPSULE", "CYLINDER", "SPHERE", "ELLIPSOID")
#: MuJoCo's own viewer shows geom groups 0 to 2 by default; higher ones are hidden helpers.
_VISIBLE_GROUPS = 2
#: Sides of a round primitive, and rings from pole to pole on a sphere.
_SIDES = 24
_RINGS = 12


def primitive_geoms(model: Any) -> list[int]:
    """Ids of the visible box, capsule, cylinder, sphere and ellipsoid geoms.

    Only meaningful for a model that has no visible meshes: published robots keep primitive
    geoms as invisible collision shapes beside their visual meshes, which must not be drawn.
    """
    import mujoco

    # Plain integers: an enum member and the int in ``geom_type`` compare equal but do not
    # always hash alike, so a set of enum members can miss.
    kinds = {int(getattr(mujoco.mjtGeom, f"mjGEOM_{name}")) for name in _PRIMITIVES}
    return [
        geom
        for geom in range(model.ngeom)
        if int(model.geom_type[geom]) in kinds
        and model.geom_rgba[geom][3] > 0
        and model.geom_group[geom] <= _VISIBLE_GROUPS
    ]


def primitive_arrays(model: Any, geom: int) -> tuple[np.ndarray, np.ndarray]:
    """Vertices (n, 3) float32 and outward-facing triangles (m, 3) uint32 of a primitive geom,
    in the geom's own frame (the same frame a mesh geom's vertices are in)."""
    import mujoco

    kind = model.geom_type[geom]
    size = np.asarray(model.geom_size[geom], dtype=np.float64)
    shape = mujoco.mjtGeom
    if kind == shape.mjGEOM_BOX:
        vertices, faces = _box(size)
    elif kind == shape.mjGEOM_SPHERE:
        vertices, faces = _revolve(_sphere_rings(size[0]))
    elif kind == shape.mjGEOM_ELLIPSOID:
        vertices, faces = _revolve(_sphere_rings(1.0))
        vertices = vertices * size
    elif kind == shape.mjGEOM_CAPSULE:
        vertices, faces = _revolve(_capsule_rings(size[0], size[1]))
    elif kind == shape.mjGEOM_CYLINDER:
        vertices, faces = _revolve(_cylinder_rings(size[0], size[1]))
    else:
        raise ValueError(f"geom {geom} is not a primitive shape")
    return vertices.astype(np.float32), _facing_out(vertices, faces).astype(np.uint32)


def _box(half: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Eight corners, twelve triangles."""
    corners = np.array(
        [[sx, sy, sz] for sz in (-1, 1) for sy in (-1, 1) for sx in (-1, 1)], dtype=np.float64
    )
    faces = np.array(
        [
            [0, 1, 3],
            [0, 3, 2],  # bottom
            [4, 6, 7],
            [4, 7, 5],  # top
            [0, 4, 5],
            [0, 5, 1],  # front (y = -1)
            [2, 3, 7],
            [2, 7, 6],  # back (y = +1)
            [0, 2, 6],
            [0, 6, 4],  # left (x = -1)
            [1, 5, 7],
            [1, 7, 3],  # right (x = +1)
        ]
    )
    return corners * half, faces


def _sphere_rings(radius: float) -> list[tuple[float, float]]:
    """(radius from the axis, height) from the top pole to the bottom pole."""
    angles = np.linspace(0.0, np.pi, _RINGS + 1)
    return [(radius * float(np.sin(a)), radius * float(np.cos(a))) for a in angles]


def _capsule_rings(radius: float, half_length: float) -> list[tuple[float, float]]:
    """Two hemispheres joined by a straight side: the equator ring appears twice."""
    top = np.linspace(0.0, np.pi / 2, _RINGS // 2 + 1)
    bottom = np.linspace(np.pi / 2, np.pi, _RINGS // 2 + 1)
    rings = [(radius * float(np.sin(a)), radius * float(np.cos(a)) + half_length) for a in top]
    rings += [(radius * float(np.sin(a)), radius * float(np.cos(a)) - half_length) for a in bottom]
    return rings


def _cylinder_rings(radius: float, half_height: float) -> list[tuple[float, float]]:
    return [(0.0, half_height), (radius, half_height), (radius, -half_height), (0.0, -half_height)]


def _revolve(rings: list[tuple[float, float]]) -> tuple[np.ndarray, np.ndarray]:
    """A surface of revolution about the z axis; a ring of radius 0 is a pole."""
    angles = np.linspace(0.0, 2 * np.pi, _SIDES, endpoint=False)
    vertices = np.array(
        [[r * np.cos(a), r * np.sin(a), z] for r, z in rings for a in angles], dtype=np.float64
    )
    faces = []
    for ring in range(len(rings) - 1):
        for side in range(_SIDES):
            a = ring * _SIDES + side
            b = ring * _SIDES + (side + 1) % _SIDES
            faces.append([a, a + _SIDES, b + _SIDES])
            faces.append([a, b + _SIDES, b])
    return vertices, np.array(faces)


def _facing_out(vertices: np.ndarray, faces: np.ndarray) -> np.ndarray:
    """The faces wound so every triangle's normal points away from the middle of the shape."""
    a, b, c = vertices[faces[:, 0]], vertices[faces[:, 1]], vertices[faces[:, 2]]
    normal = np.cross(b - a, c - a)
    centre = (a + b + c) / 3.0
    inward = np.einsum("ij,ij->i", normal, centre) < 0
    flipped = faces.copy()
    flipped[inward] = faces[inward][:, [0, 2, 1]]
    return flipped
