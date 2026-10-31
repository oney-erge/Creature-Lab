"""The 3D robot stage: real meshes as Viser frames, posed by MuJoCo forward kinematics."""

from types import SimpleNamespace

import numpy as np
import pytest

mujoco = pytest.importorskip("mujoco")
pytest.importorskip("trimesh")

from creature_lab.editor.robot_stage import RobotStage  # noqa: E402

# One visual mesh on the trunk, a collision twin that must be skipped, and a visual arm.
ROBOT_XML = """
<mujoco>
  <asset><mesh name="tri" vertex="0 0 0  1 0 0  0 1 0  0 0 1"/></asset>
  <worldbody>
    <body name="trunk" pos="0 0 0.5">
      <freejoint/>
      <geom type="mesh" mesh="tri" group="2" rgba="1 0.5 0 1" mass="1"/>
      <geom type="mesh" mesh="tri" group="3" rgba="0 0 1 1" mass="0.001"/>
      <body name="arm" pos="0.2 0 0">
        <joint type="hinge" axis="0 1 0"/>
        <geom type="mesh" mesh="tri" group="2" rgba="1 1 1 1" mass="0.1"/>
      </body>
    </body>
  </worldbody>
</mujoco>
"""


class _Node:
    def __init__(self, name):
        self.name = name
        self.position = (0.0, 0.0, 0.0)
        self.wxyz = (1.0, 0.0, 0.0, 0.0)
        self.removed = False

    def remove(self):
        self.removed = True


class _Scene:
    def __init__(self):
        self.nodes = []

    def add_frame(self, name, **_):
        self.nodes.append(_Node(name))
        return self.nodes[-1]

    def add_mesh_trimesh(self, name, mesh, wxyz, position):
        node = _Node(name)
        node.mesh, node.position, node.wxyz = mesh, position, wxyz
        self.nodes.append(node)
        return node


class _Server:
    def __init__(self):
        self.scene = _Scene()
        self.initial_camera = SimpleNamespace(position=None, look_at=None)
        self.client = SimpleNamespace(camera=SimpleNamespace(position=(0, 0, 0), look_at=(0, 0, 0)))

    def get_clients(self):
        return {1: self.client}


class _Run:
    """The two attributes of a RobotRun the stage reads."""

    def __init__(self, qpos):
        self.qpos = qpos

    def __len__(self):
        return len(self.qpos)


@pytest.fixture
def stage():
    visibility = []
    server = _Server()
    stage = RobotStage(server, set_editor_visible=visibility.append)
    stage.load_model(mujoco.MjModel.from_xml_string(ROBOT_XML), "microduck")
    return stage, server, visibility


def test_only_the_visual_meshes_are_drawn(stage):
    stage_, server, visibility = stage
    names = [node.name for node in server.scene.nodes]
    meshes = [name for name in names if "geom_" in name]
    assert len(meshes) == 2  # trunk + arm; the group-3 collision twin is skipped
    assert sum(name.endswith(("body_1", "body_2")) for name in names) == 2
    assert stage_.active and stage_.robot == "microduck"
    assert visibility == [False]  # the editor's own creature steps aside


def test_mesh_colours_come_from_the_model(stage):
    _, server, _ = stage
    mesh = next(n for n in server.scene.nodes if "geom_" in n.name).mesh
    assert tuple(mesh.visual.vertex_colors[0]) == (255, 127, 0, 255)


def test_posing_moves_each_body_to_its_kinematic_position(stage):
    stage_, server, _ = stage
    qpos = np.array([1.0, 2.0, 0.3, 1, 0, 0, 0, 0.0])  # free joint (7) + the arm hinge
    stage_.pose(qpos)
    trunk = next(n for n in server.scene.nodes if n.name.endswith("body_1"))
    arm = next(n for n in server.scene.nodes if n.name.endswith("body_2"))
    assert trunk.position == pytest.approx((1.0, 2.0, 0.3))
    assert arm.position == pytest.approx((1.2, 2.0, 0.3))  # 0.2 m ahead of the trunk


def test_the_camera_follows_the_robot_unless_told_not_to(stage):
    stage_, server, _ = stage
    stage_.pose(np.array([0.0, 0.0, 0.3, 1, 0, 0, 0, 0.0]))
    start = np.array(server.client.camera.position)
    stage_.pose(np.array([1.5, 0.0, 0.3, 1, 0, 0, 0, 0.0]))
    assert np.array(server.client.camera.position) - start == pytest.approx([1.5, 0, 0])
    stage_.follow = False
    stage_.pose(np.array([3.0, 0.0, 0.3, 1, 0, 0, 0, 0.0]))
    assert np.array(server.client.camera.position) - start == pytest.approx([1.5, 0, 0])


def test_a_replay_advances_with_time_and_loops(stage):
    stage_, server, _ = stage
    qpos = np.zeros((100, 8))
    qpos[:, 3] = 1.0
    qpos[:, 2] = 0.3
    qpos[:, 0] = np.linspace(0.0, 1.98, 100)  # 2 s at 50 Hz
    stage_.play(_Run(qpos))
    assert stage_.playing
    trunk = next(n for n in server.scene.nodes if n.name.endswith("body_1"))
    stage_.tick(1.0)
    assert trunk.position[0] == pytest.approx(qpos[50, 0])
    stage_.tick(1.0)
    stage_.tick(0.01)  # still holding the last pose
    assert trunk.position[0] == pytest.approx(qpos[-1, 0])
    stage_.tick(2.0)  # past the hold: back to the start
    assert trunk.position[0] == pytest.approx(qpos[0, 0])
    stage_.stop()
    assert not stage_.playing


def test_hiding_removes_everything_and_restores_the_editor(stage):
    stage_, server, visibility = stage
    stage_.hide()
    assert all(node.removed for node in server.scene.nodes)
    assert not stage_.active and not stage_.playing
    assert visibility == [False, True]
    stage_.tick(1.0)  # harmless when nothing is shown
    stage_.pose(np.zeros(8))


def test_showing_another_robot_replaces_the_first_without_flicker(stage):
    stage_, server, visibility = stage
    first = list(server.scene.nodes)
    stage_.load_model(mujoco.MjModel.from_xml_string(ROBOT_XML), "unitree_g1")
    assert all(node.removed for node in first)
    assert stage_.robot == "unitree_g1"
    assert visibility == [False, False]  # never restored the editor in between
