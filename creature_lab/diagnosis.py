"""Explain *why* a creature failed, not just *what* happened.

``diagnose(trace, creature, task)`` reads a recorded episode and the creature/task
that produced it, derives locomotion signals (center-of-mass path, fall time, joint
effort, ground contacts, motor-vs-limit), and matches them against a set of failure
patterns. Each detected pattern carries a plain-language explanation and a concrete
suggested edit. Pure and backend-free: it reads a saved trace, never re-simulates.
"""

from __future__ import annotations

import math
import statistics
from collections import Counter
from dataclasses import dataclass, field

from creature_lab.schema import CreatureSpec, EpisodeTrace, TaskSpec
from creature_lab.terrain import (
    DEFAULT_CELL_SIZE,
    DEFAULT_COLS,
    DEFAULT_ROWS,
    heightfield_grid,
    is_flat,
)

# Tuning thresholds (metres / radians / fractions). Calibrated against the bundled
# zoo: good walkers travel 0.4-0.9 m forward; the tripod drifts backward.
_POOR_DISPLACEMENT = 0.1
_HIGH_EFFORT = 3.0
_BACKWARD = -0.1
_LATERAL_RATIO = 2.0
_UPRIGHT_Z = 0.5  # root up-axis z below this => toppled (matches the backend)
_EARLY_FALL_FRACTION = 0.3
_DOMINANT_CONTACT = 0.8
_MINOR_CONTACT = 0.2
_COM_HEIGHT_STD = 0.1
_TARGET_NO_PROGRESS = 0.05  # metres of net closing distance below which "no progress"
# Humanoid-specific thresholds.
_ASYM_RATIO = 2.0
_KNEE_LIMIT_EPS = 0.05  # rad from a limit counts as "at the limit"
_KNEE_HIT_FRACTION = 0.5
_ARM_MOTION_FRACTION = 0.05
_NARROW_STANCE = 0.12  # metres between left/right feet


@dataclass
class DiagnosisResult:
    """Outcome of a diagnosis: headline metrics plus matched failure patterns."""

    metrics: dict[str, float]
    patterns: list[str] = field(default_factory=list)
    explanations: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)

    def add(self, pattern: str, explanation: str, suggestion: str) -> None:
        self.patterns.append(pattern)
        self.explanations.append(explanation)
        self.suggestions.append(suggestion)


@dataclass
class _Signals:
    duration: float
    forward: float  # signed CoM displacement along +x
    lateral: float  # abs CoM displacement along y
    net: float  # straight-line CoM displacement
    joint_motion: float  # sum |Δ joint angle|
    fell: bool
    fall_time: float | None
    com_height_std: float
    frames_with_contact: int
    frame_count: int
    early_contact: bool
    contact_fraction: dict[str, float]  # part id -> fraction of frames in contact
    motors_over_limit: list[str]
    #: (initial distance to task.target - final distance), horizontal only. None
    #: when the task has no target.
    target_progress: float | None = None
    terrain_outside_frames: int = 0


def root_id(creature: CreatureSpec) -> str:
    """The creature's root part: the one with no parent joint."""
    child_ids = {joint.child for joint in creature.joints}
    return next(part.id for part in creature.parts if part.id not in child_ids)


def is_upright(orientation: tuple[float, float, float, float]) -> bool:
    """Whether a (w, x, y, z) quaternion's local +z axis still points mostly up."""
    _, x, y, _ = orientation
    up_z = 1 - 2 * (x * x + y * y)
    return up_z >= _UPRIGHT_Z


def first_fall_time(trace: EpisodeTrace, creature: CreatureSpec) -> float | None:
    """First frame time the root part toppled (see ``is_upright``), or None if it never did.

    Reward-independent, unlike a score's ``fall`` component (which is only nonzero
    when the task sets ``reward.fall_penalty`` - see ``creature_lab.diagnostics.
    summarize_episode``, which uses this for the same reason). Root-orientation-based
    fall detection, matching the check ``_signals`` uses internally.
    """
    root = root_id(creature)
    for frame in trace.frames:
        pose = frame.parts.get(root)
        if pose is not None and not is_upright(pose.orientation):
            return frame.t
    return None


def _signals(trace: EpisodeTrace, creature: CreatureSpec, task: TaskSpec | None = None) -> _Signals:
    frames = trace.frames
    masses = {part.id: part.mass for part in creature.parts}

    def com(frame) -> tuple[float, float, float]:
        present = [(masses.get(pid, 0.0), pose.position) for pid, pose in frame.parts.items()]
        total = sum(mass for mass, _ in present) or 1.0
        return tuple(sum(mass * pos[axis] for mass, pos in present) / total for axis in range(3))

    first, last = com(frames[0]), com(frames[-1])
    forward = last[0] - first[0]
    lateral = abs(last[1] - first[1])
    # Horizontal travel only: the body spawns above the plane and settles, so a 3-D
    # distance would be dominated by that one-time vertical drop, not locomotion.
    net = math.hypot(forward, last[1] - first[1])

    target_progress: float | None = None
    if task is not None and task.target is not None:
        tx, ty, _tz = task.target.position
        initial_distance = math.hypot(tx - first[0], ty - first[1])
        final_distance = math.hypot(tx - last[0], ty - last[1])
        target_progress = initial_distance - final_distance

    # CoM height stability is measured only after the settling transient (the drop
    # from the spawn height), so a clean walker is not flagged for its initial fall.
    settle_t = min(0.5, 0.2 * frames[-1].t)

    root_part_id = root_id(creature)
    steady_heights: list[float] = []
    fall_time: float | None = None
    grid = (
        heightfield_grid(task.terrain) if task is not None and not is_flat(task.terrain) else None
    )
    terrain_outside_frames = 0
    for frame in frames:
        pose = frame.parts.get(root_part_id)
        ground_height = 0.0
        inside = True
        if grid is not None and pose is not None:
            x, y, _ = pose.position
            half_x = DEFAULT_ROWS * DEFAULT_CELL_SIZE / 2
            half_y = DEFAULT_COLS * DEFAULT_CELL_SIZE / 2
            inside = -half_x <= x < half_x and -half_y <= y < half_y
            if inside:
                row = min(DEFAULT_ROWS - 1, max(0, round((x + half_x) / DEFAULT_CELL_SIZE)))
                col = min(DEFAULT_COLS - 1, max(0, round((y + half_y) / DEFAULT_CELL_SIZE)))
                ground_height = grid[row][col]
            else:
                terrain_outside_frames += 1
        if frame.t >= settle_t and inside:
            steady_heights.append(com(frame)[2] - ground_height)
        if pose is not None and fall_time is None and not is_upright(pose.orientation):
            fall_time = frame.t
    com_height_std = statistics.pstdev(steady_heights) if len(steady_heights) > 1 else 0.0

    contacts: Counter[str] = Counter()
    frames_with_contact = 0
    early_contact = False
    for frame in frames:
        if frame.contacts:
            frames_with_contact += 1
            if frame.t < 0.5:
                early_contact = True
        # Count each part once per frame (a part may have several contact points).
        for part_id in {contact.part_id for contact in frame.contacts}:
            contacts[part_id] += 1
    n = len(frames)
    contact_fraction = {pid: count / n for pid, count in contacts.items()}

    limits = {joint.id: joint.limit for joint in creature.joints}
    motors_over_limit = [
        motor.joint
        for motor in creature.motors
        if (lim := limits.get(motor.joint)) is not None
        and motor.amplitude > min(abs(lim[0]), abs(lim[1])) + 1e-9
    ]

    return _Signals(
        duration=frames[-1].t,
        forward=forward,
        lateral=lateral,
        net=net,
        joint_motion=_total_joint_motion(trace),
        fell=fall_time is not None,
        fall_time=fall_time,
        com_height_std=com_height_std,
        frames_with_contact=frames_with_contact,
        frame_count=n,
        early_contact=early_contact,
        contact_fraction=contact_fraction,
        motors_over_limit=motors_over_limit,
        target_progress=target_progress,
        terrain_outside_frames=terrain_outside_frames,
    )


def _total_joint_motion(trace: EpisodeTrace) -> float:
    total = 0.0
    previous: dict[str, float] = {}
    for frame in trace.frames:
        for joint_id, angle in frame.joint_angles.items():
            if joint_id in previous:
                total += abs(angle - previous[joint_id])
            previous[joint_id] = angle
    return total


def diagnose(
    trace: EpisodeTrace, creature: CreatureSpec, task: TaskSpec | None = None
) -> DiagnosisResult:
    """Diagnose an episode and return matched failure patterns with suggested fixes."""
    sig = _signals(trace, creature, task)
    result = DiagnosisResult(
        metrics={
            "forward_displacement": sig.forward,
            "lateral_displacement": sig.lateral,
            "net_displacement": sig.net,
            "total_joint_motion": sig.joint_motion,
            "fall_time": sig.fall_time if sig.fall_time is not None else -1.0,
            "com_height_std": sig.com_height_std,
            "terrain_outside_frames": float(sig.terrain_outside_frames),
            "contact_frames_fraction": (
                sig.frames_with_contact / sig.frame_count if sig.frame_count else 0.0
            ),
            **({"target_progress": sig.target_progress} if sig.target_progress is not None else {}),
        }
    )

    if sig.terrain_outside_frames:
        result.add(
            "outside_terrain",
            f"The root left the finite terrain grid in {sig.terrain_outside_frames} frame(s); "
            "ground-relative height is unavailable there.",
            "Shorten the episode or keep the target and motion inside the terrain extent.",
        )

    # 1. Motors that swing past their own joint limit (read from the creature spec).
    if sig.motors_over_limit:
        joints = ", ".join(sig.motors_over_limit)
        result.add(
            "motor_over_limit",
            f"Motor amplitude exceeds the joint limit on {joints}; the joint clips "
            "every cycle, wasting actuation and jittering.",
            "Lower those motor amplitudes to within the joint limit, or widen the limits.",
        )

    # 2. Started airborne / never settled on the ground.
    if not sig.early_contact:
        result.add(
            "no_ground_contact",
            "No ground contact in the first 0.5 s - the creature starts airborne or "
            "is too small/short to reach the floor.",
            "Lower the spawn or lengthen the legs so the body rests on the ground.",
        )

    # 3. Fell, and fell early.
    if (
        sig.fell
        and sig.fall_time is not None
        and sig.fall_time < _EARLY_FALL_FRACTION * sig.duration
    ):
        result.add(
            "early_fall",
            f"The body toppled at t={sig.fall_time:.2f}s "
            f"(within the first {_EARLY_FALL_FRACTION:.0%} of the episode).",
            "Widen the stance (spread leg anchors) or lower the torso to drop the centre of mass.",
        )

    # 4. Moving the wrong way.
    if sig.forward < _BACKWARD:
        result.add(
            "moving_backward",
            f"The creature moved backward ({sig.forward:.2f} m along x) instead of forward.",
            "Reverse the gait direction: flip the leg tilt sign or reverse the wave phase order.",
        )

    # 5. Lots of joint motion, almost no displacement.
    elif sig.joint_motion > _HIGH_EFFORT and sig.net < _POOR_DISPLACEMENT:
        result.add(
            "high_effort_low_result",
            f"High actuation ({sig.joint_motion:.1f} rad of joint motion) but the body "
            f"barely moved ({sig.net:.2f} m).",
            "Stagger motor phases so limbs push in a coordinated direction instead of fighting.",
        )

    # 6. Veers sideways instead of forward.
    if sig.net >= _POOR_DISPLACEMENT and sig.lateral > _LATERAL_RATIO * abs(sig.forward):
        result.add(
            "lateral_drift",
            f"The creature drifts sideways ({sig.lateral:.2f} m) far more than forward "
            f"({sig.forward:.2f} m) - the gait has no straight directional thrust.",
            "Symmetrise left/right phases and align leg axes so thrust points along +x.",
        )

    # 7. One limb does all the ground work.
    legs_in_contact = {
        pid: frac for pid, frac in sig.contact_fraction.items() if pid != root_id(creature)
    }
    if len(legs_in_contact) >= 2:
        dominant = max(legs_in_contact, key=legs_in_contact.get)
        minor = [p for p, f in legs_in_contact.items() if f < _MINOR_CONTACT]
        if legs_in_contact[dominant] > _DOMINANT_CONTACT and minor:
            result.add(
                "single_leg_drag",
                f"{dominant!r} is on the ground {legs_in_contact[dominant]:.0%} of the time "
                f"while {', '.join(minor)} barely touch - the creature drags one limb.",
                "Rebalance leg phases/lengths so all limbs share stance and swing.",
            )

    # 8. Bouncing / unstable centre of mass.
    if sig.com_height_std > _COM_HEIGHT_STD:
        result.add(
            "com_instability",
            f"The centre-of-mass height swings a lot (std={sig.com_height_std:.2f} m) - "
            "the body bounces or pitches rather than gliding.",
            "Reduce motor amplitude/frequency or add a stabilising contact point.",
        )

    # 9. Has a target, but made no real progress toward it.
    if sig.target_progress is not None and sig.target_progress < _TARGET_NO_PROGRESS:
        result.add(
            "target_not_approached",
            f"The task has a target, but the creature made almost no progress toward "
            f"it ({sig.target_progress:+.2f} m closed over the episode).",
            "Use a target-aware controller (e.g. --controller target_seek) instead of "
            "an open-loop gait, or check the episode is long enough to reach it.",
        )

    _add_humanoid_patterns(result, trace, creature, sig)
    return result


def _is_humanoid(creature: CreatureSpec) -> bool:
    """Heuristic: a biped from the humanoid scaffold (has arms or upper/lower legs)."""
    ids = [part.id for part in creature.parts]
    return any("arm" in pid for pid in ids) or any("upper_leg" in pid for pid in ids)


def _add_humanoid_patterns(
    result: DiagnosisResult, trace: EpisodeTrace, creature: CreatureSpec, sig: _Signals
) -> None:
    """Append humanoid-specific patterns; no-op for non-humanoid creatures."""
    if not _is_humanoid(creature):
        return

    part_ids = [part.id for part in creature.parts]
    frames = trace.frames
    n = len(frames)
    limits = {j.id: j.limit for j in creature.joints}

    # Per-joint motion and knee-at-limit counts in one pass.
    per_joint_motion: dict[str, float] = {}
    knee_hits: dict[str, int] = {}
    previous: dict[str, float] = {}
    for frame in frames:
        for joint_id, angle in frame.joint_angles.items():
            if joint_id in previous:
                per_joint_motion[joint_id] = per_joint_motion.get(joint_id, 0.0) + abs(
                    angle - previous[joint_id]
                )
            previous[joint_id] = angle
            if "knee" in joint_id and (limit := limits.get(joint_id)) is not None:
                if min(abs(angle - limit[0]), abs(angle - limit[1])) < _KNEE_LIMIT_EPS:
                    knee_hits[joint_id] = knee_hits.get(joint_id, 0) + 1

    # biped_asymmetric_fall: fell, with one side bearing far more ground contact.
    foot_like = [pid for pid in part_ids if "foot" in pid or "lower_leg" in pid]
    left = sum(sig.contact_fraction.get(p, 0.0) for p in foot_like if p.endswith("_l"))
    right = sum(sig.contact_fraction.get(p, 0.0) for p in foot_like if p.endswith("_r"))
    hi, lo = max(left, right), min(left, right)
    if sig.fell and hi > _MINOR_CONTACT and lo < hi / _ASYM_RATIO:
        heavy = "left" if left > right else "right"
        result.add(
            "biped_asymmetric_fall",
            f"The biped fell with its {heavy} foot bearing most of the ground contact "
            f"(left {left:.0%} vs right {right:.0%}) - it tipped to one side.",
            "Symmetrise leg mass/length and gait phase so both feet share load.",
        )

    # knee_hyperextension: a knee sits at its limit for most of the episode.
    pinned = [j for j, count in knee_hits.items() if n and count / n > _KNEE_HIT_FRACTION]
    if pinned:
        result.add(
            "knee_hyperextension",
            f"Knee joint(s) {', '.join(pinned)} sit at their limit most of the time - "
            "the leg is locked straight rather than flexing.",
            "Widen the knee joint limits or lower the motor amplitude driving them there.",
        )

    # arm_swing_absent: arms barely move relative to the whole body.
    arm_keys = ("shoulder", "elbow", "arm", "wrist")
    arm_motion = sum(m for j, m in per_joint_motion.items() if any(k in j for k in arm_keys))
    if any("arm" in pid for pid in part_ids) and sig.joint_motion > 0:
        if arm_motion / sig.joint_motion < _ARM_MOTION_FRACTION:
            result.add(
                "arm_swing_absent",
                f"The arms barely move ({arm_motion / sig.joint_motion:.0%} of total joint "
                "motion) - they are dead weight instead of aiding balance.",
                "Add arm motors or counter-swing the arms against the legs.",
            )

    # stance_too_narrow: feet stay close together laterally.
    width = _mean_stance_width(frames, foot_like)
    if width is not None and width < _NARROW_STANCE:
        result.add(
            "stance_too_narrow",
            f"The feet stay only {width:.2f} m apart laterally - a narrow base that "
            "topples easily.",
            "Move the hip anchors farther apart (wider stance).",
        )


def _mean_stance_width(frames, foot_like: list[str]) -> float | None:
    """Mean lateral (y) separation between left and right foot-like parts, or None."""
    left_parts = [p for p in foot_like if p.endswith("_l")]
    right_parts = [p for p in foot_like if p.endswith("_r")]
    if not left_parts or not right_parts:
        return None
    separations: list[float] = []
    for frame in frames:
        left_y = [frame.parts[p].position[1] for p in left_parts if p in frame.parts]
        right_y = [frame.parts[p].position[1] for p in right_parts if p in frame.parts]
        if left_y and right_y:
            separations.append(abs(sum(left_y) / len(left_y) - sum(right_y) / len(right_y)))
    return sum(separations) / len(separations) if separations else None
