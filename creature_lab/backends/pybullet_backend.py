"""PyBullet implementation of the SimBackend protocol.

Only this module may import pybullet. A joint's ``anchor`` is the child link's
origin in the parent's local frame, and its ``rest_orientation`` is the child's
resting orientation relative to the parent (so limbs can be angled, not just
axis-aligned).
"""

from __future__ import annotations

import math

import pybullet
import pybullet_data

from creature_lab.schema import CreatureSpec, PartPose, PartSpec, ShapeType, TaskSpec
from creature_lab.schema.creature import JointType
from creature_lab.schema.trace import ContactSpec, EpisodeTrace, FrameState
from creature_lab.scoring import score_components
from creature_lab.terrain import (
    DEFAULT_CELL_SIZE,
    DEFAULT_COLS,
    DEFAULT_ROWS,
    flatten_for_heightfield_api,
    heightfield_grid,
    heightfield_range,
    is_flat,
)


def backend_version() -> str:
    """Human-readable PyBullet backend version, e.g. ``pybullet api 201``."""
    return f"pybullet api {pybullet.getAPIVersion()}"


_DEFAULT_COLOR = (0.6, 0.6, 0.6)
_DEFAULT_HINGE_LIMIT = (-math.pi, math.pi)
_DEFAULT_MOTOR_MAX_FORCE = 5.0


def _collision_geometry(part: PartSpec) -> tuple[int, dict]:
    # createCollisionShape spells the capsule/cylinder height parameter "height".
    if part.shape == ShapeType.BOX:
        return pybullet.GEOM_BOX, {"halfExtents": [size / 2 for size in part.size]}
    if part.shape == ShapeType.SPHERE:
        return pybullet.GEOM_SPHERE, {"radius": part.radius}
    if part.shape in (ShapeType.CAPSULE, ShapeType.CYLINDER):
        geom = pybullet.GEOM_CAPSULE if part.shape == ShapeType.CAPSULE else pybullet.GEOM_CYLINDER
        return geom, {"radius": part.radius, "height": part.length}
    raise ValueError(f"unsupported shape {part.shape!r}")


def _visual_geometry(part: PartSpec) -> tuple[int, dict]:
    # createVisualShape spells the same parameter "length" instead of "height".
    if part.shape == ShapeType.BOX:
        return pybullet.GEOM_BOX, {"halfExtents": [size / 2 for size in part.size]}
    if part.shape == ShapeType.SPHERE:
        return pybullet.GEOM_SPHERE, {"radius": part.radius}
    if part.shape in (ShapeType.CAPSULE, ShapeType.CYLINDER):
        geom = pybullet.GEOM_CAPSULE if part.shape == ShapeType.CAPSULE else pybullet.GEOM_CYLINDER
        return geom, {"radius": part.radius, "length": part.length}
    raise ValueError(f"unsupported shape {part.shape!r}")


def _build_ground(task: TaskSpec, client: int) -> int:
    """Load the flat plane, or build a heightfield from ``creature_lab.terrain``."""
    if is_flat(task.terrain):
        ground_id = pybullet.loadURDF("plane.urdf", physicsClientId=client)
    else:
        grid = heightfield_grid(task.terrain)
        # PyBullet auto-recenters heightfield data around z=0 — offsetting the body
        # by the data's midpoint cancels that so raw grid heights are world heights.
        flat_heights = flatten_for_heightfield_api(grid)
        lo, hi = heightfield_range(task.terrain)
        shape = pybullet.createCollisionShape(
            shapeType=pybullet.GEOM_HEIGHTFIELD,
            meshScale=[DEFAULT_CELL_SIZE, DEFAULT_CELL_SIZE, 1.0],
            heightfieldData=flat_heights,
            numHeightfieldRows=DEFAULT_ROWS,
            numHeightfieldColumns=DEFAULT_COLS,
            physicsClientId=client,
        )
        ground_id = pybullet.createMultiBody(
            baseMass=0,
            baseCollisionShapeIndex=shape,
            basePosition=[0, 0, (lo + hi) / 2],
            physicsClientId=client,
        )
    pybullet.changeDynamics(
        ground_id, -1, lateralFriction=task.terrain.friction, physicsClientId=client
    )
    return ground_id


class PyBulletBackend:
    """Builds a creature as a single PyBullet multi-body and steps it."""

    def __init__(self, gui: bool = False) -> None:
        self._client = pybullet.connect(pybullet.GUI if gui else pybullet.DIRECT)
        pybullet.setAdditionalSearchPath(pybullet_data.getDataPath(), physicsClientId=self._client)
        self._creature: CreatureSpec | None = None
        self._task: TaskSpec | None = None
        self._body_id: int | None = None
        self._link_index: dict[str, int] = {}
        self._joint_link: dict[str, int] = {}
        self._part_by_link: dict[int, str] = {}
        self._plane_id = -1
        self._damaged_parts: set[str] = set()
        self._t = 0.0
        self._initial_root_x = 0.0
        self._initial_target_distance = 0.0
        self._energy = 0.0
        self._last_score_components: dict[str, float] = {}
        self._damage_fired = False
        self._impulse_fired = False
        self._seed: int | None = None

    def build(self, creature: CreatureSpec, task: TaskSpec, *, seed: int | None = None) -> None:
        self._creature = creature
        self._task = task
        self._seed = seed
        pybullet.resetSimulation(physicsClientId=self._client)
        pybullet.setGravity(0, 0, -9.81, physicsClientId=self._client)
        self._plane_id = _build_ground(task, self._client)
        self._build_body(creature)
        self._t = 0.0
        self._energy = 0.0
        self._damaged_parts.clear()
        self._damage_fired = False
        self._impulse_fired = False
        base_position, _ = pybullet.getBasePositionAndOrientation(
            self._body_id, physicsClientId=self._client
        )
        self._initial_root_x = base_position[0]
        self._initial_target_distance = (
            math.dist(base_position, task.target.position) if task.target is not None else 0.0
        )

    def reset(self) -> None:
        if self._creature is None or self._task is None:
            raise RuntimeError("build() must be called before reset()")
        self.build(self._creature, self._task, seed=self._seed)

    def step(self, dt: float) -> FrameState:
        if self._creature is None or self._task is None:
            raise RuntimeError("build() must be called before step()")
        self._t += dt
        events: list[str] = []
        damage_event = self._task.damage_event
        if damage_event is not None and not self._damage_fired and self._t >= damage_event.time:
            self.damage_part(damage_event.part_id)
            self._damage_fired = True
            events.append(f"damage:{damage_event.part_id}")
        impulse_event = self._task.impulse_event
        if impulse_event is not None and not self._impulse_fired and self._t >= impulse_event.time:
            self._apply_impulse(impulse_event)
            self._impulse_fired = True
            events.append(f"impulse:{impulse_event.part_id}")
        pybullet.setTimeStep(dt, physicsClientId=self._client)
        pybullet.stepSimulation(physicsClientId=self._client)
        self._accumulate_energy(dt)
        frame = self._read_frame()
        if events:
            frame = frame.model_copy(update={"events": events})
        return frame

    def _accumulate_energy(self, dt: float) -> None:
        # Proxy for actuation effort: integral of squared hinge-joint speed.
        for joint in self._creature.joints:
            if joint.type != JointType.HINGE:
                continue
            velocity = pybullet.getJointState(
                self._body_id, self._joint_link[joint.id], physicsClientId=self._client
            )[1]
            self._energy += velocity * velocity * dt

    def apply_motor_targets(self, targets: dict[str, float]) -> None:
        if self._creature is None or self._body_id is None:
            raise RuntimeError("build() must be called before apply_motor_targets()")
        joint_child = {joint.id: joint.child for joint in self._creature.joints}
        for motor in self._creature.motors:
            if motor.joint not in targets or joint_child[motor.joint] in self._damaged_parts:
                continue
            pybullet.setJointMotorControl2(
                self._body_id,
                self._joint_link[motor.joint],
                controlMode=pybullet.POSITION_CONTROL,
                targetPosition=targets[motor.joint],
                force=motor.max_force or _DEFAULT_MOTOR_MAX_FORCE,
                physicsClientId=self._client,
            )

    def apply_joint_control(self, targets: dict[str, float], mode: str = "position") -> None:
        """Drive joints directly by id in position/velocity/torque mode (used by CreatureEnv).

        Unlike ``apply_motor_targets`` this applies to *any* hinge joint named in
        ``targets`` (not only joints that carry a MotorSpec), so a policy can control
        joints the open-loop gait does not.
        """
        if self._creature is None or self._body_id is None:
            raise RuntimeError("build() must be called before apply_joint_control()")
        joint_child = {joint.id: joint.child for joint in self._creature.joints}
        joint_force = {
            motor.joint: motor.max_force or _DEFAULT_MOTOR_MAX_FORCE
            for motor in self._creature.motors
        }
        for joint_id, value in targets.items():
            link = self._joint_link.get(joint_id)
            if link is None or joint_child.get(joint_id) in self._damaged_parts:
                continue
            if mode == "position":
                pybullet.setJointMotorControl2(
                    self._body_id,
                    link,
                    pybullet.POSITION_CONTROL,
                    targetPosition=value,
                    force=joint_force.get(joint_id, _DEFAULT_MOTOR_MAX_FORCE),
                    physicsClientId=self._client,
                )
            elif mode == "velocity":
                pybullet.setJointMotorControl2(
                    self._body_id,
                    link,
                    pybullet.VELOCITY_CONTROL,
                    targetVelocity=value,
                    force=joint_force.get(joint_id, _DEFAULT_MOTOR_MAX_FORCE),
                    physicsClientId=self._client,
                )
            elif mode == "torque":
                # Disable the implicit velocity motor, then apply the torque directly.
                pybullet.setJointMotorControl2(
                    self._body_id,
                    link,
                    pybullet.VELOCITY_CONTROL,
                    force=0.0,
                    physicsClientId=self._client,
                )
                pybullet.setJointMotorControl2(
                    self._body_id,
                    link,
                    pybullet.TORQUE_CONTROL,
                    force=value,
                    physicsClientId=self._client,
                )
            else:
                raise ValueError(f"unknown control mode {mode!r}")

    def _apply_impulse(self, impulse) -> None:
        """Apply a one-step world-frame push at a part's current position."""
        link_index = self._link_index[impulse.part_id]
        if link_index == -1:
            position, _ = pybullet.getBasePositionAndOrientation(
                self._body_id, physicsClientId=self._client
            )
        else:
            position = pybullet.getLinkState(
                self._body_id, link_index, physicsClientId=self._client
            )[0]
        pybullet.applyExternalForce(
            self._body_id,
            link_index,
            forceObj=list(impulse.force),
            posObj=list(position),
            flags=pybullet.WORLD_FRAME,
            physicsClientId=self._client,
        )

    def damage_part(self, part_id: str) -> None:
        if self._creature is None or self._body_id is None:
            raise RuntimeError("build() must be called before damage_part()")
        self._damaged_parts.add(part_id)
        for joint in self._creature.joints:
            if joint.child == part_id and joint.id in self._joint_link:
                pybullet.setJointMotorControl2(
                    self._body_id,
                    self._joint_link[joint.id],
                    controlMode=pybullet.VELOCITY_CONTROL,
                    force=0.0,
                    physicsClientId=self._client,
                )

    def close(self) -> None:
        pybullet.disconnect(physicsClientId=self._client)

    def score_summary(self) -> dict[str, float]:
        """Per-component breakdown of the most recently read frame's score."""
        return dict(self._last_score_components)

    def observe(self) -> FrameState:
        """Read the current state as a FrameState without advancing physics.

        Used by CreatureEnv to get the initial observation right after reset().
        """
        return self._read_frame()

    def _build_body(self, creature: CreatureSpec) -> None:
        parts_by_id = {part.id: part for part in creature.parts}
        joints_by_parent: dict[str, list] = {part.id: [] for part in creature.parts}
        joint_by_child = {}
        for joint in creature.joints:
            joints_by_parent[joint.parent].append(joint)
            joint_by_child[joint.child] = joint
        root_id = next(part.id for part in creature.parts if part.id not in joint_by_child)
        root_part = parts_by_id[root_id]

        # PyBullet canonicalises a multibody's link arrays into depth-first order.
        # Supplying breadth-first arrays appears to work for shallow creatures, but
        # PyBullet then returns joint/link indices in a different order for branched,
        # multi-level bodies (notably the humanoid).  The old bookkeeping therefore
        # read ``foot_r`` from an arm link and sent several motor targets to the wrong
        # joints.  Build in the same stable depth-first order PyBullet exposes so our
        # part/joint maps remain exact.
        order: list[tuple] = []
        self._link_index = {root_id: -1}
        stack = [(root_id, iter(joints_by_parent[root_id]))]
        while stack:
            current_id, children = stack[-1]
            joint = next(children, None)
            if joint is None:
                stack.pop()
                continue
            parent_link = self._link_index[current_id]
            order.append((parts_by_id[joint.child], joint, parent_link))
            self._link_index[joint.child] = len(order) - 1
            stack.append((joint.child, iter(joints_by_parent[joint.child])))
        self._part_by_link = {index: part_id for part_id, index in self._link_index.items()}

        base_collision_geom, base_collision_kwargs = _collision_geometry(root_part)
        base_collision = pybullet.createCollisionShape(
            base_collision_geom, physicsClientId=self._client, **base_collision_kwargs
        )
        base_visual_geom, base_visual_kwargs = _visual_geometry(root_part)
        base_visual = pybullet.createVisualShape(
            base_visual_geom,
            rgbaColor=[*(root_part.color or _DEFAULT_COLOR), 1.0],
            physicsClientId=self._client,
            **base_visual_kwargs,
        )

        link_masses: list[float] = []
        link_collision_shapes: list[int] = []
        link_visual_shapes: list[int] = []
        link_positions: list[list[float]] = []
        link_orientations: list[list[float]] = []
        link_inertial_positions: list[list[float]] = []
        link_inertial_orientations: list[list[float]] = []
        link_parent_indices: list[int] = []
        link_joint_types: list[int] = []
        link_joint_axes: list[list[float]] = []
        self._joint_link = {}

        for part, joint, parent_link in order:
            collision_geom, collision_kwargs = _collision_geometry(part)
            collision = pybullet.createCollisionShape(
                collision_geom, physicsClientId=self._client, **collision_kwargs
            )
            visual_geom, visual_kwargs = _visual_geometry(part)
            visual = pybullet.createVisualShape(
                visual_geom,
                rgbaColor=[*(part.color or _DEFAULT_COLOR), 1.0],
                physicsClientId=self._client,
                **visual_kwargs,
            )
            link_masses.append(part.mass)
            link_collision_shapes.append(collision)
            link_visual_shapes.append(visual)
            link_positions.append(list(joint.anchor))
            # Schema stores scalar-first (w, x, y, z); PyBullet wants (x, y, z, w).
            w, qx, qy, qz = joint.rest_orientation
            link_orientations.append([qx, qy, qz, w])
            link_inertial_positions.append([0.0, 0.0, 0.0])
            link_inertial_orientations.append([0.0, 0.0, 0.0, 1.0])
            # PyBullet's multi-body parent indices are 1-based; 0 means the base.
            link_parent_indices.append(parent_link + 1)
            is_hinge = joint.type == JointType.HINGE
            link_joint_types.append(pybullet.JOINT_REVOLUTE if is_hinge else pybullet.JOINT_FIXED)
            link_joint_axes.append(list(joint.axis))
            self._joint_link[joint.id] = len(link_masses) - 1

        self._body_id = pybullet.createMultiBody(
            baseMass=root_part.mass,
            baseCollisionShapeIndex=base_collision,
            baseVisualShapeIndex=base_visual,
            basePosition=[0.0, 0.0, 1.0],
            linkMasses=link_masses,
            linkCollisionShapeIndices=link_collision_shapes,
            linkVisualShapeIndices=link_visual_shapes,
            linkPositions=link_positions,
            linkOrientations=link_orientations,
            linkInertialFramePositions=link_inertial_positions,
            linkInertialFrameOrientations=link_inertial_orientations,
            linkParentIndices=link_parent_indices,
            linkJointTypes=link_joint_types,
            linkJointAxis=link_joint_axes,
            physicsClientId=self._client,
        )

        for joint in creature.joints:
            if joint.type == JointType.HINGE:
                lower, upper = joint.limit if joint.limit else _DEFAULT_HINGE_LIMIT
                pybullet.changeDynamics(
                    self._body_id,
                    self._joint_link[joint.id],
                    jointLowerLimit=lower,
                    jointUpperLimit=upper,
                    physicsClientId=self._client,
                )

    def _read_frame(self) -> FrameState:
        if self._creature is None or self._task is None or self._body_id is None:
            raise RuntimeError("build() must be called before reading a frame")

        parts: dict[str, PartPose] = {}
        base_position, base_orientation = pybullet.getBasePositionAndOrientation(
            self._body_id, physicsClientId=self._client
        )
        for part in self._creature.parts:
            link_index = self._link_index[part.id]
            if link_index == -1:
                parts[part.id] = self._pose(base_position, base_orientation)
            else:
                link_state = pybullet.getLinkState(
                    self._body_id, link_index, physicsClientId=self._client
                )
                parts[part.id] = self._pose(link_state[0], link_state[1])

        joint_angles: dict[str, float] = {}
        for joint in self._creature.joints:
            if joint.type != JointType.HINGE:
                continue
            joint_state = pybullet.getJointState(
                self._body_id, self._joint_link[joint.id], physicsClientId=self._client
            )
            joint_angles[joint.id] = joint_state[0]

        forward_distance = base_position[0] - self._initial_root_x
        target_progress = 0.0
        if self._task.target is not None:
            current_distance = math.dist(base_position, self._task.target.position)
            target_progress = self._initial_target_distance - current_distance
        # Body's local +z expressed in world coordinates; small z-component => toppled.
        body_up_z = pybullet.getMatrixFromQuaternion(base_orientation)[8]
        self._last_score_components = score_components(
            self._task.reward,
            forward_distance=forward_distance,
            target_progress=target_progress,
            energy=self._energy,
            fallen=body_up_z < 0.5,
        )
        score = self._last_score_components["total"]

        return FrameState(
            t=self._t,
            parts=parts,
            joint_angles=joint_angles,
            contacts=self._read_contacts(),
            score=score,
        )

    def _read_contacts(self) -> list[ContactSpec]:
        """Report the creature's contacts with the ground from the last step."""
        points = pybullet.getContactPoints(
            bodyA=self._body_id, bodyB=self._plane_id, physicsClientId=self._client
        )
        contacts: list[ContactSpec] = []
        for point in points:
            part_id = self._part_by_link.get(point[3])  # point[3] = link index on bodyA
            if part_id is None:
                continue
            contacts.append(
                ContactSpec(
                    part_id=part_id,
                    position=tuple(point[6]),  # contact position on the ground
                    normal=tuple(point[7]),  # contact normal on the ground
                    force=max(0.0, point[9]),  # normal force (schema requires >= 0)
                )
            )
        return contacts

    @staticmethod
    def _pose(
        position: tuple[float, float, float],
        orientation: tuple[float, float, float, float],
    ) -> PartPose:
        x, y, z, w = orientation
        return PartPose(position=tuple(position), orientation=(w, x, y, z))


def render_trace(
    creature: CreatureSpec,
    trace: EpisodeTrace,
    *,
    task: TaskSpec | None = None,
    width: int = 640,
    height: int = 480,
    fov: float = 60.0,
    camera_distance: float = 2.0,
    camera_yaw: float = 50.0,
    camera_pitch: float = -30.0,
) -> list:
    """Render a trace to a list of RGB frames (no physics step).

    Each part is drawn as an independent visual body posed *directly* from the
    recorded ``frame.parts`` poses — exactly what the Viser viewer shows — so the
    export is faithful to the trace rather than re-deriving link poses from joint
    angles (which deviates from the recorded dynamics). Returns a list of
    ``(height, width, 3)`` uint8 numpy arrays.

    ``task`` draws the actual terrain shape (slope/steps/gaps/rough) instead of a flat
    plane when its ``terrain`` is non-flat — without it, a replay of a non-flat-terrain
    run would misleadingly show the creature floating above/sinking into a flat floor.
    """
    import numpy as np

    # Round up to even dimensions so the frames are valid MP4 input for libx264.
    width += width % 2
    height += height % 2

    client = pybullet.connect(pybullet.DIRECT)
    frames: list = []
    try:
        pybullet.setAdditionalSearchPath(pybullet_data.getDataPath(), physicsClientId=client)
        if task is not None and not is_flat(task.terrain):
            _build_ground(task, client)  # visual ground reference (matches the real terrain)
        else:
            pybullet.loadURDF("plane.urdf", physicsClientId=client)  # visual ground reference

        # One static (mass-0) visual body per part; we just move them each frame.
        part_bodies: dict[str, int] = {}
        for part in creature.parts:
            geom, kwargs = _visual_geometry(part)
            visual = pybullet.createVisualShape(
                geom,
                rgbaColor=[*(part.color or _DEFAULT_COLOR), 1.0],
                physicsClientId=client,
                **kwargs,
            )
            part_bodies[part.id] = pybullet.createMultiBody(
                baseMass=0.0, baseVisualShapeIndex=visual, physicsClientId=client
            )

        projection = pybullet.computeProjectionMatrixFOV(
            fov, width / height, 0.1, 100.0, physicsClientId=client
        )
        for frame in trace.frames:
            centroid = [0.0, 0.0, 0.0]
            for part_id, pose in frame.parts.items():
                body = part_bodies.get(part_id)
                if body is None:
                    continue
                w, x, y, z = pose.orientation  # schema (w,x,y,z) -> pybullet (x,y,z,w)
                pybullet.resetBasePositionAndOrientation(
                    body, pose.position, (x, y, z, w), physicsClientId=client
                )
                for axis in range(3):
                    centroid[axis] += pose.position[axis]
            centroid = [value / len(frame.parts) for value in centroid]
            view = pybullet.computeViewMatrixFromYawPitchRoll(
                centroid, camera_distance, camera_yaw, camera_pitch, 0, 2, physicsClientId=client
            )
            _, _, rgba, _, _ = pybullet.getCameraImage(
                width,
                height,
                viewMatrix=view,
                projectionMatrix=projection,
                renderer=pybullet.ER_TINY_RENDERER,
                physicsClientId=client,
            )
            rgb = np.reshape(np.asarray(rgba, dtype=np.uint8), (height, width, 4))[:, :, :3]
            frames.append(rgb)
    finally:
        pybullet.disconnect(physicsClientId=client)
    return frames
