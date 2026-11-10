"""The support area of a mesh foot is its sole, not the few points MuJoCo reports touching."""

import numpy as np
import pytest

mujoco = pytest.importorskip("mujoco")

from creature_lab.robots.rollout import _sole_footprint  # noqa: E402

# A flat 5 cm x 4 cm x 1 cm block lying on the floor, as a mesh (eight corner vertices).
_XML = """
<mujoco>
  <asset>
    <mesh name="foot" vertex="-0.025 -0.02 0  0.025 -0.02 0  0.025 0.02 0  -0.025 0.02 0
        -0.025 -0.02 0.01  0.025 -0.02 0.01  0.025 0.02 0.01  -0.025 0.02 0.01"/>
  </asset>
  <worldbody>
    <geom name="floor" type="plane" size="1 1 0.1"/>
    <body pos="0 0 0"><freejoint/><geom name="foot" type="mesh" mesh="foot"/></body>
  </worldbody>
</mujoco>
"""


def test_a_flat_mesh_foot_outlines_its_whole_sole():
    model = mujoco.MjModel.from_xml_string(_XML)
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    geom = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, "foot")
    footprint = _sole_footprint(model, data, geom)
    extent_cm = np.ptp(footprint, axis=0) * 100
    assert len(footprint) >= 4
    assert extent_cm == pytest.approx([5.0, 4.0], abs=0.5)


def test_a_lifted_foot_has_no_footprint():
    model = mujoco.MjModel.from_xml_string(_XML)
    data = mujoco.MjData(model)
    data.qpos[2] = 0.05  # 5 cm up: nothing within the sole height of the floor
    mujoco.mj_forward(model, data)
    geom = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, "foot")
    assert len(_sole_footprint(model, data, geom)) == 0
