"""Check a robot pack before it is used: every likely mistake, said in one plain sentence."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from creature_lab.robots.pack import (
    Pack,
    PackError,
    PackSpec,
    load_pack,
    missing_files,
    pack_file,
    sensor_widths,
)

#: How long the trial walk runs, in seconds.
_TRIAL_S = 2.0
#: A trunk tilted past this (upright below it) in the trial counts as already fallen.
_TRIAL_UPRIGHT = 0.5
#: The mass written in robot.toml may differ from the model's by this fraction before we warn.
_MASS_TOLERANCE = 0.25


@dataclass
class PackReport:
    """What checking a pack found. ``errors`` stop it from being used; ``warnings`` do not."""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    #: Things worth showing the author: joint count, observation length, trial result.
    facts: dict[str, str] = field(default_factory=dict)
    pack: Pack | None = None

    @property
    def ok(self) -> bool:
        return not self.errors


def validate_pack(path: Path, *, simulate: bool = True) -> PackReport:
    """Read ``robot.toml`` and everything it points at; run a short trial walk if ``simulate``.

    Needs MuJoCo and onnxruntime (the ``robots`` extra) beyond the file checks.
    """
    report = PackReport()
    try:
        pack = load_pack(path)
    except PackError as error:
        report.errors.extend(error.problems)
        return report
    report.pack = pack
    todo = [
        number
        for number, line in enumerate(pack_file(path).read_text(encoding="utf-8").splitlines(), 1)
        if "TODO" in line and not line.lstrip().startswith("#")
    ]
    if todo:
        shown = ", ".join(str(n) for n in todo[:6]) + (" ..." if len(todo) > 6 else "")
        report.warnings.append(
            f"robot.toml still says TODO on line {shown}: fill those in (they appear on reports)"
        )
    report.errors.extend(missing_files(pack))
    if report.errors:
        return report
    try:
        import mujoco  # noqa: F401
        import onnxruntime  # noqa: F401
    except ImportError:
        report.warnings.append(
            "MuJoCo or onnxruntime is not installed, so only robot.toml was checked "
            "(uv sync --inexact --extra robots)"
        )
        return report
    _check_policies(pack, report)
    model = _check_model(pack, report)
    if model is not None:
        _check_wiring(pack, model, report)
    if report.ok and simulate:
        _trial_walk(pack, report)
    return report


def _check_policies(pack: Pack, report: PackReport) -> None:
    from creature_lab.robots.policies import load_policy

    joints = len(pack.spec.joints)
    for policy in pack.spec.policies:
        try:
            loaded = load_policy(pack.policy_path(policy.key))
        except Exception as error:
            report.errors.append(f"policy {policy.key}: {error}")
            continue
        if loaded.action_len is not None and loaded.action_len != joints:
            report.errors.append(
                f"policy {policy.key} outputs {loaded.action_len} actions but robot.toml lists "
                f"{joints} joints (one action per joint, in the same order)"
            )
        want = pack.spec.observation_length(policy=policy.key)
        if want is not None and loaded.obs_len is not None and loaded.obs_len != want:
            report.errors.append(
                f"policy {policy.key} expects {loaded.obs_len} observation numbers but the "
                f"observation list gives {want}: {_layout(pack.spec, policy=policy.key)}"
            )


def _layout(
    spec: PackSpec, sensor_widths: dict[str, int] | None = None, policy: str | None = None
) -> str:
    """The observation terms and how many numbers each adds, e.g. "joint_pos 29, command 3"."""
    from creature_lab.robots.pack import _term_width

    parts = []
    for term in spec.observation_for(policy):
        name = f"sensor {term.sensor}" if term.term == "sensor" else term.term
        width = _term_width(term, len(spec.joints), sensor_widths)
        parts.append(f"{name} {'?' if width is None else width}")
    return ", ".join(parts)


def _check_model(pack: Pack, report: PackReport):
    import mujoco

    try:
        model = mujoco.MjModel.from_xml_path(str(pack.model_path))
    except Exception as error:
        report.errors.append(f"model {pack.spec.model}: MuJoCo could not load it: {error}")
        return None
    if np.any(model.geom_type == mujoco.mjtGeom.mjGEOM_PLANE):
        report.errors.append(
            "the model has its own ground plane; delete it, because Creature Lab adds the floor "
            "and needs to know which surface is the ground"
        )
    if mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, "floor") >= 0:
        report.errors.append(
            "the model has a geom named 'floor'; rename it, because Creature Lab uses that name "
            "for its own floor"
        )
    return model


def _check_wiring(pack: Pack, model, report: PackReport) -> None:
    import mujoco

    spec = pack.spec
    trunk = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, spec.trunk)
    if trunk < 0:
        report.errors.append(f"trunk: the model has no body named {spec.trunk!r}")
        return
    root = int(model.body_jntadr[trunk])
    if root < 0 or model.jnt_type[root] != mujoco.mjtJoint.mjJNT_FREE:
        report.errors.append(
            f"trunk {spec.trunk!r} needs a <freejoint/>: it is the part that falls over"
        )
    listed = set()
    for name in spec.joints:
        joint = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, name)
        if joint < 0:
            report.errors.append(f"joints.{name}: the model has no joint with that name")
            continue
        listed.add(joint)
        driven = [
            a
            for a in range(model.nu)
            if model.actuator_trntype[a] == mujoco.mjtTrn.mjTRN_JOINT
            and int(model.actuator_trnid[a, 0]) == joint
        ]
        if not driven:
            report.errors.append(f"joints.{name}: the model has no actuator on this joint")
        elif spec.joints[name].torque_limit is None and not _has_limit(model, joint, driven[0]):
            report.errors.append(
                f"joints.{name}: no torque limit in the model; add torque_limit = <N·m>"
            )
    loose = []
    for a in range(model.nu):
        joint = int(model.actuator_trnid[a, 0])
        if joint not in listed:
            loose.append(mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_JOINT, joint) or f"#{joint}")
    if loose:
        report.errors.append(
            "the model drives joints that robot.toml does not list: "
            f"{', '.join(loose)} (list every actuated joint, in the policy's order)"
        )
    widths = sensor_widths(model)
    lists = [("observation", spec.observation)] + [
        (f"policies.{p.key}.observation", p.observation) for p in spec.policies if p.observation
    ]
    for where, terms in lists:
        for index, term in enumerate(terms):
            if term.term == "height_scan" and term.body:
                if mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, term.body) < 0:
                    report.errors.append(f"{where}[{index}]: the model has no body {term.body!r}")
            if term.term != "sensor":
                continue
            name = term.sensor or ""
            if name not in widths:
                known = ", ".join(sorted(widths)) or "none"
                report.errors.append(
                    f"{where}[{index}]: the model has no sensor {name!r} (sensors: {known})"
                )
            elif isinstance(term.scale, list) and len(term.scale) != widths[name]:
                report.errors.append(
                    f"{where}[{index}]: sensor {name!r} has {widths[name]} numbers but scale "
                    f"lists {len(term.scale)}"
                )
    if root >= 0:
        mass = float(model.body_subtreemass[trunk])
        if abs(mass - spec.mass_kg) > _MASS_TOLERANCE * spec.mass_kg:
            report.warnings.append(
                f"mass_kg is {spec.mass_kg:g} but the model weighs {mass:.3g} kg; the default "
                "shoves and loads are scaled from mass_kg"
            )
    report.facts["joints"] = str(len(spec.joints))
    length = spec.observation_length(widths)
    if length is not None:
        report.facts["observation"] = f"{length} numbers: {_layout(spec, widths)}"


def _has_limit(model, joint: int, actuator: int) -> bool:
    return bool(
        model.jnt_actfrclimited[joint]
        or model.actuator_forcelimited[actuator]
        or model.actuator_ctrllimited[actuator]
    )


def _trial_walk(pack: Pack, report: PackReport) -> None:
    """Walk the robot for two seconds with every policy; say if it falls over or fails."""
    from creature_lab.robots.packbot import PackRobot
    from creature_lab.robots.rollout import run_robot
    from creature_lab.robots.types import Scenario

    spec = pack.spec
    for policy in spec.policies:
        scenario = Scenario(
            robot=spec.key, policy=policy.key, command=spec.walk_command, seconds=_TRIAL_S
        )
        try:
            run = run_robot(PackRobot(scenario, pack))
        except PackError as error:
            report.errors.extend(f"policy {policy.key}: {line}" for line in error.problems)
            continue
        except Exception as error:
            report.errors.append(f"policy {policy.key}: the trial walk failed: {error}")
            continue
        upright = float(run.upright.min())
        distance = float(run.trunk_pos[-1, 0] - run.trunk_pos[0, 0])
        report.facts[f"trial walk ({policy.key})"] = (
            f"{_TRIAL_S:g} s walk, moved {distance:+.2f} m, "
            f"{'stayed upright' if upright >= _TRIAL_UPRIGHT else 'fell over'}"
        )
        if upright < _TRIAL_UPRIGHT:
            report.warnings.append(
                f"policy {policy.key} fell over within {_TRIAL_S:g} s with no shove. Usual causes: "
                "the observation order or scales differ from training, the default pose or gains "
                "differ, or the model differs from the one the policy was trained on"
            )
