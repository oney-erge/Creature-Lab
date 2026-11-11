"""Draft a ``robot.toml`` for a model and its policies from what they already say.

A policy exported from mjlab (or Pollen Robotics' Microduck policies) carries its joint order,
gains, default pose, action scales and observation layout as ONNX metadata, and a MuJoCo model
knows its trunk, mass, sensors and physics step. This reads both and writes the draft; what only a
person knows (who made the robot, its license, how fast it walks) is left as ``TODO`` for them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from creature_lab.robots.pack import PACK_FILE, PackError

_DEFAULT_COMMAND = 0.5
_DEFAULT_GAIT_S = 0.8


@dataclass
class Metadata:
    """What a policy file says about itself (empty for a file that says nothing)."""

    joint_names: list[str]
    default_pos: list[float]
    stiffness: list[float]
    damping: list[float]
    action_scale: list[float]
    observation_names: list[str]
    observation_scales: list[float | list[float]]
    history: list[int]
    obs_len: int | None
    action_len: int | None


def _numbers(text: str) -> list[float]:
    return [float(part) for part in text.split(",") if part.strip()]


def read_policy(path: Path) -> Metadata:
    """The metadata of an ``.onnx`` policy; an ``.npz`` policy has none."""
    empty = Metadata([], [], [], [], [], [], [], [], None, None)
    if path.suffix.lower() != ".onnx":
        return empty
    import onnxruntime

    options = onnxruntime.SessionOptions()
    options.log_severity_level = 3
    session = onnxruntime.InferenceSession(
        str(path), sess_options=options, providers=["CPUExecutionProvider"]
    )
    meta = session.get_modelmeta().custom_metadata_map
    obs_shape = session.get_inputs()[0].shape
    act_shape = session.get_outputs()[0].shape

    def width(shape: list) -> int | None:
        return int(shape[-1]) if shape and isinstance(shape[-1], int) else None

    scales: list[float | list[float]] = []
    for entry in meta.get("observation_terms_scale", "").split(","):
        if not entry.strip():
            continue
        values = [float(v) for v in entry.split(";")]
        scales.append(values[0] if len(values) == 1 else values)
    return Metadata(
        joint_names=[n for n in meta.get("joint_names", "").split(",") if n],
        default_pos=_numbers(meta.get("default_joint_pos", "")),
        stiffness=_numbers(meta.get("joint_stiffness", "")),
        damping=_numbers(meta.get("joint_damping", "")),
        action_scale=_numbers(meta.get("action_scale", "")),
        observation_names=[n for n in meta.get("observation_names", "").split(",") if n],
        observation_scales=scales,
        history=[
            int(float(v)) for v in meta.get("observation_terms_history_length", "").split(",") if v
        ],
        obs_len=width(obs_shape),
        action_len=width(act_shape),
    )


def _fmt(value: float) -> str:
    return f"{float(value):.6g}"


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return slug if re.match(r"^[a-z]", slug) else f"robot_{slug}"


def _sensor(model: Any, *needles: str) -> str | None:
    """The model's sensor whose name holds one of ``needles`` (a name with 'imu' wins)."""
    import mujoco

    names = [
        mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_SENSOR, i) or "" for i in range(model.nsensor)
    ]
    found = [n for n in names if any(needle in n.lower() for needle in needles)]
    found.sort(key=lambda n: "imu" not in n.lower())
    return found[0] if found else None


def _height_cm(model: Any, data: Any) -> int:
    """Standing height from the bounding boxes of the model's geoms at its resting pose."""
    import mujoco

    mujoco.mj_forward(model, data)
    low, high = np.inf, -np.inf
    for geom in range(model.ngeom):
        if model.geom_type[geom] == mujoco.mjtGeom.mjGEOM_PLANE:
            continue
        centre = model.geom_aabb[geom, :3]
        half = model.geom_aabb[geom, 3:]
        corners = np.array(
            [
                centre + half * np.array([sx, sy, sz])
                for sx in (-1, 1)
                for sy in (-1, 1)
                for sz in (-1, 1)
            ]
        )
        world = corners @ data.geom_xmat[geom].reshape(3, 3).T + data.geom_xpos[geom]
        low, high = min(low, world[:, 2].min()), max(high, world[:, 2].max())
    return max(int(round((high - low) * 100)), 1)


def draft_pack(
    model_path: Path,
    policy_paths: list[Path],
    *,
    key: str | None = None,
    title: str | None = None,
) -> str:
    """The text of a draft ``robot.toml`` for ``model_path`` and its policies.

    Paths in the file are written relative to the model's folder, so the model and the policies
    must sit in (or below) the folder the file is saved in.
    """
    import mujoco

    folder = model_path.parent
    try:
        model = mujoco.MjModel.from_xml_path(str(model_path))
    except Exception as error:
        raise PackError([f"MuJoCo could not load {model_path.name}: {error}"]) from error
    data = mujoco.MjData(model)

    root = next(
        (
            body
            for body in range(1, model.nbody)
            if model.body_jntadr[body] >= 0
            and model.jnt_type[model.body_jntadr[body]] == mujoco.mjtJoint.mjJNT_FREE
        ),
        None,
    )
    if root is None:
        raise PackError(["the model has no body with a free joint: the robot would be bolted down"])
    trunk = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, root)

    metas = [read_policy(path) for path in policy_paths]
    meta = next((m for m in metas if m.joint_names), metas[0] if metas else None)
    actuated = [
        mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_JOINT, int(model.actuator_trnid[a, 0]))
        for a in range(model.nu)
    ]
    ordered = meta.joint_names if meta and meta.joint_names else actuated
    todo: list[str] = []
    if not (meta and meta.joint_names):
        todo.append("joints follow the model's actuator order; reorder them to your policy's order")

    # How the model's actuators work: position servos hold their own gains.
    servo = model.nu > 0 and bool(
        np.all(model.actuator_gaintype == mujoco.mjtGain.mjGAIN_FIXED)
        and np.all(model.actuator_biastype == mujoco.mjtBias.mjBIAS_AFFINE)
    )
    actuator = "position" if servo else "pd"

    lines = [
        "# Draft written by `creature-lab robots init`. Fix every line that says TODO, then run:",
        "#   creature-lab robots validate .",
        'schema_id = "creature-lab.robot-pack/1"',
        f'key = "{key or _slug(folder.resolve().name)}"',
        f'title = "{title or folder.resolve().name.replace("_", " ").replace("-", " ").title()}"',
        'maker = "TODO: who made the robot"',
        'summary = "TODO: one sentence about the robot"',
        f"height_cm = {_height_cm(model, data)}",
        f"mass_kg = {_fmt(model.body_subtreemass[root])}",
        "",
        f'model = "{model_path.name}"',
        f'trunk = "{trunk}"',
        f"physics_dt = {_fmt(model.opt.timestep)}",
        f'actuator = "{actuator}"',
    ]
    scales = meta.action_scale if meta else []
    # One number for every joint is written once; different ones go on their joints.
    per_joint_scale = len(scales) == len(ordered) > 1 and len(set(scales)) > 1
    if scales and not per_joint_scale:
        lines.append(f"action_scale = {_fmt(meta.action_scale[0])}")
    elif not per_joint_scale:
        lines.append("action_scale = 0.25  # TODO: target pose = default + action x this")
    lines += [
        f"walk_command = {_DEFAULT_COMMAND}  # TODO: the forward speed the policy was trained for",
        f"gait_period_s = {_DEFAULT_GAIT_S}  # TODO: seconds per stride",
    ]
    key_z = None
    if model.nkey > 0:
        root_q = int(model.jnt_qposadr[model.body_jntadr[root]])
        key_z = float(model.key_qpos[0][root_q + 2])
        if abs(key_z - float(model.qpos0[root_q + 2])) > 1e-6:
            lines.append(f"spawn_height_m = {_fmt(key_z)}")
    lines += [
        "",
        "[license]",
        'notice = "TODO: where the model and the policy come from, and under what license"',
        'credit = "TODO: one line printed on every report and video"',
        "non_commercial = false",
        "",
        "# Every actuated joint, in the order the policy outputs its actions.",
        "[joints]",
    ]
    qpos_default = {
        name: float(
            model.qpos0[
                model.jnt_qposadr[mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, name)]
            ]
        )
        for name in ordered
        if mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, name) >= 0
    }
    for index, name in enumerate(ordered):
        default = (
            meta.default_pos[index] if meta and meta.default_pos else qpos_default.get(name, 0.0)
        )
        fields = [f"default = {_fmt(default)}"]
        if actuator == "pd":
            if meta and meta.stiffness and meta.damping:
                fields += [
                    f"kp = {_fmt(meta.stiffness[index])}",
                    f"kd = {_fmt(meta.damping[index])}",
                ]
            else:
                todo.append(f"{name}: kp and kd are not in the policy; add your training gains")
        if per_joint_scale and meta:
            fields.append(f"action_scale = {_fmt(meta.action_scale[index])}")
        lines.append(f"{name} = {{ {', '.join(fields)} }}")

    lines += ["", "# How the policy's input is put together, in order."]
    if meta and meta.observation_names:
        lines += _observation_lines(model, meta, len(ordered), todo)
    else:
        todo.append("list the policy's observation terms (see docs/ROBOT_PACKS.md)")
        lines.append(
            "# TODO: [[observation]] entries, one per term, in the order the policy was trained on"
        )

    for path in policy_paths:
        relative = path.relative_to(folder).as_posix()
        stem = _slug(path.stem)
        lines += [
            "",
            "[[policies]]",
            f'key = "{stem}"',
            f'title = "{path.stem.replace("_", " ").replace("-", " ").capitalize()}"',
            'summary = "TODO: how this policy was trained"',
            f'file = "{relative}"',
        ]
    if todo:
        lines += ["", "# Still to do:"] + [f"#  - {item}" for item in todo]
    return "\n".join(lines) + "\n"


def _observation_lines(model: Any, meta: Metadata, joints: int, todo: list[str]) -> list[str]:
    """``[[observation]]`` entries for the terms the policy names."""
    if any(h > 1 for h in meta.history):
        raise PackError(
            ["the policy stacks past observations (history), which robot packs cannot do yet"]
        )
    fixed = {
        "base_lin_vel": 3,
        "base_ang_vel": 3,
        "projected_gravity": 3,
        "joint_pos": joints,
        "joint_vel": joints,
        "actions": joints,
    }
    known = {"command", *fixed}
    unknown = [name for name in meta.observation_names if name not in known]
    if unknown:
        raise PackError(
            [f"the policy observes {', '.join(unknown)}, which robot packs cannot provide yet"]
        )
    command_size = (meta.obs_len or 0) - sum(
        fixed[name] for name in meta.observation_names if name in fixed
    )
    out: list[str] = []
    for index, name in enumerate(meta.observation_names):
        scale = meta.observation_scales[index] if index < len(meta.observation_scales) else 1.0
        out.append("[[observation]]")
        if name in ("base_lin_vel", "base_ang_vel"):
            sensor = _sensor(
                model, *(("lin_vel", "velocimeter") if "lin" in name else ("ang_vel", "gyro"))
            )
            if sensor:
                out += ['term = "sensor"', f'sensor = "{sensor}"']
            else:
                out.append(f'term = "{name}"')
                todo.append(
                    f"{name}: the model has no matching sensor, so it is computed from the trunk"
                )
        elif name == "actions":
            out.append('term = "last_action"')
        else:
            out.append(f'term = "{name}"')
        if name == "command" and command_size not in (0, 3):
            out.append(f"size = {command_size}")
        if scale not in (1.0, [1.0] * 3):
            out.append(f"scale = {scale if isinstance(scale, list) else _fmt(scale)}")
        out.append("")
    return out[:-1]


def write_draft(folder: Path, text: str, *, force: bool = False) -> Path:
    """Save the draft as ``robot.toml`` in ``folder`` (never over an existing file by accident)."""
    target = folder / PACK_FILE
    if target.exists() and not force:
        raise PackError([f"{target} already exists; use --force to replace it"])
    target.write_text(text, encoding="utf-8", newline="\n")
    return target
