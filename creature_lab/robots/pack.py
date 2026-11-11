"""Robot packs: bring your own MuJoCo robot and trained policy to the check-up.

A pack is a folder with a ``robot.toml``, a MuJoCo model (MJCF) and one or more trained
policies. The file says how the policy talks to the robot: which joints it drives, how an
observation is put together, how an action becomes a target pose, and the gains that turn a target
into torque. Creature Lab then runs the same shoves, floors and loads on it as on the built-in
robots and explains every fall.

This module is the schema, the registry of added packs and the conversion to a ``RobotInfo``. It
needs no simulator; ``packbot.py`` runs a pack and ``packcheck.py`` validates one.
"""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass
from functools import cache, lru_cache
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, ValidationError, ValidationInfo, field_validator, model_validator

from creature_lab.io_utils import atomic_write_text
from creature_lab.robots.catalog import (
    ROBOTS,
    CheckupLevels,
    PolicyInfo,
    RobotInfo,
    Staging,
)
from creature_lab.robots.fetch import cache_root
from creature_lab.robots.types import CONTROL_HZ
from creature_lab.schema.base import StrictModel

PACK_FILE = "robot.toml"
SCHEMA_ID = "creature-lab.robot-pack/1"
_KEY = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
_STANDARD_GRAVITY = 9.81

#: Observation pieces a policy can be built from, with how many numbers each one adds.
TERMS = (
    "base_lin_vel",  # trunk velocity in the trunk's own frame (3)
    "base_ang_vel",  # trunk angular velocity in the trunk's own frame (3)
    "projected_gravity",  # where "down" is in the trunk's frame (3)
    "command",  # the walking command: forward speed, then zeros (``size``)
    "joint_pos",  # joint angles minus the default pose (one per joint)
    "joint_vel",  # joint velocities (one per joint)
    "last_action",  # the policy's previous output (one per joint)
    "gait_phase",  # sin and cos of the stride clock (2)
    "sensor",  # a named MuJoCo sensor (its own width)
)

#: Fractions of body weight tried as shoves, and of body mass tried as a carried load, when the
#: pack does not list its own. For a 35 kg humanoid this gives about 50-310 N and 3.5-10 kg.
_SHOVE_FRACTIONS = (0.15, 0.3, 0.45, 0.6, 0.9)
_LOAD_FRACTIONS = (0.1, 0.2, 0.3)


def _bundled_root() -> Traversable:
    return resources.files("creature_lab.robots").joinpath("data", "packs")


@lru_cache(maxsize=1)
def bundled_keys() -> tuple[str, ...]:
    """Keys of the robots whose ``robot.toml`` ships inside the package."""
    root = _bundled_root()
    if not root.is_dir():
        return ()
    return tuple(
        sorted(e.name for e in root.iterdir() if e.is_dir() and e.joinpath(PACK_FILE).is_file())
    )


class PackError(ValueError):
    """A pack that cannot be used; ``problems`` lists everything wrong, one line each."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("\n".join(problems))
        self.problems = problems


class PackLicense(StrictModel):
    notice: str = Field(min_length=1, description="Shown before use and on every report.")
    credit: str = Field(min_length=1, description="One line printed on videos and reports.")
    non_commercial: bool = False


class JointSpec(StrictModel):
    #: Default pose in radians (or metres for a slide joint): the target when the action is 0.
    default: float = 0.0
    #: Stiffness and damping of the PD controller (``actuator = "pd"`` only).
    kp: float | None = Field(default=None, gt=0)
    kd: float | None = Field(default=None, ge=0)
    #: Torque at which the motor is "at its limit"; read from the model when left out.
    torque_limit: float | None = Field(default=None, gt=0)
    #: This joint's own action scale, when it differs from the pack's ``action_scale``.
    action_scale: float | None = Field(default=None, gt=0)


class ObservationTerm(StrictModel):
    term: Literal[
        "base_lin_vel",
        "base_ang_vel",
        "projected_gravity",
        "command",
        "joint_pos",
        "joint_vel",
        "last_action",
        "gait_phase",
        "sensor",
    ]
    #: One number for every entry, or one per entry.
    scale: float | list[float] = 1.0
    #: ``command`` only: how many numbers the policy expects (forward speed first, then zeros).
    size: int | None = Field(default=None, ge=1, le=64)
    #: ``gait_phase`` only: seconds per stride.
    period_s: float | None = Field(default=None, gt=0)
    #: ``sensor`` only: the MuJoCo sensor to read.
    sensor: str | None = None

    @model_validator(mode="after")
    def _term_fields(self) -> ObservationTerm:
        if self.term == "gait_phase" and self.period_s is None:
            raise ValueError("gait_phase needs period_s (seconds per stride)")
        if self.term == "sensor" and not self.sensor:
            raise ValueError("sensor needs the sensor's name")
        if self.term != "gait_phase" and self.period_s is not None:
            raise ValueError("period_s is only for gait_phase")
        if self.term != "sensor" and self.sensor is not None:
            raise ValueError("sensor is only for term = 'sensor'")
        if self.term != "command" and self.size is not None:
            raise ValueError("size is only for command")
        if self.term == "gait_phase" and not isinstance(self.scale, float | int):
            raise ValueError("gait_phase takes a single scale")
        return self


class PolicySpec(StrictModel):
    key: str
    title: str = Field(min_length=1)
    summary: str = ""
    #: ``.onnx`` (one input, one output) or ``.npz`` (LSTM + MLP head, see docs/ROBOT_PACKS.md).
    file: str = Field(min_length=1)
    #: True if, in simulation, this policy stands back up after falling.
    gets_up: bool = False
    #: True when the title starts with a name ("Unitree ...") that keeps its capital.
    starts_with_name: bool = False

    @field_validator("key")
    @classmethod
    def _key_shape(cls, value: str) -> str:
        if not _KEY.match(value):
            raise ValueError(
                "use lowercase letters, digits and underscores, starting with a letter"
            )
        return value


class LevelsSpec(StrictModel):
    #: Shove strengths in newtons; default: fractions of body weight.
    shoves_n: list[float] | None = None
    #: Floor grip multipliers; 1 is the model's own.
    grips: list[float] = [0.5, 0.3, 0.15]
    #: Extra trunk mass in kilograms; default: fractions of the robot's mass.
    payloads_kg: list[float] | None = None

    @field_validator("shoves_n", "payloads_kg", "grips")
    @classmethod
    def _positive(cls, value: list[float] | None) -> list[float] | None:
        if value is not None and any(v <= 0 for v in value):
            raise ValueError("every level must be above zero")
        return value


class ViewSpec(StrictModel):
    #: Film camera distance in metres; default from the height.
    camera_distance_m: float | None = Field(default=None, gt=0)
    #: Side of one floor square in metres; default from the height.
    floor_tile_m: float | None = Field(default=None, gt=0)


class PackSpec(StrictModel):
    """The contents of ``robot.toml``."""

    schema_id: Literal["creature-lab.robot-pack/1"] = SCHEMA_ID
    key: str
    title: str = Field(min_length=1)
    maker: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    height_cm: int = Field(gt=0, le=500)
    mass_kg: float = Field(gt=0, le=2000)
    license: PackLicense
    #: The MuJoCo model, relative to the pack folder. It must not contain a ground plane.
    model: str = Field(min_length=1)
    #: Name of the trunk body. It must carry the robot's free joint, and it is the part that
    #: counts as "upright".
    trunk: str = Field(min_length=1)
    #: Physics step in seconds. Control runs at 50 Hz, so this must divide 0.02.
    physics_dt: float = Field(gt=0, le=0.02)
    #: ``pd``: Creature Lab computes torque from the gains below (the model's actuators are
    #: plain motors). ``position``: the model's actuators are position servos that hold their own
    #: gains; the target is sent as the control.
    actuator: Literal["pd", "position"] = "pd"
    #: Target pose = default pose + action x action_scale. A joint can set its own; this is the
    #: one for every joint that does not (and may be left out when every joint sets one).
    action_scale: float | None = Field(default=None, gt=0)
    #: Optional clip applied to the policy output before scaling.
    action_clip: float | None = Field(default=None, gt=0)
    #: Every actuated joint, in the order the policy outputs its actions.
    joints: dict[str, JointSpec]
    observation: list[ObservationTerm] = Field(min_length=1)
    policies: list[PolicySpec] = Field(min_length=1)
    #: Forward-speed command that gives a clear walk (0..1; what the policy was trained on).
    walk_command: float = Field(default=0.5, ge=0.0, le=1.0)
    #: Seconds per stride; shoves are spread across one stride.
    gait_period_s: float = Field(gt=0, le=10)
    #: Rough seconds from nothing on disk to a first check-up, for a pack bundled with Creature
    #: Lab (the app opens on the quickest robot). A user's pack leaves it at 0.
    first_run_s: int = Field(default=0, ge=0, le=3600)
    #: Trunk height at the start, if the model's own default is not right.
    spawn_height_m: float | None = Field(default=None, gt=0)
    levels: LevelsSpec = LevelsSpec()
    view: ViewSpec = ViewSpec()

    @field_validator("key")
    @classmethod
    def _key_shape(cls, value: str, info: ValidationInfo) -> str:
        if not _KEY.match(value):
            raise ValueError(
                "use 2-40 lowercase letters, digits and underscores, starting with a letter"
            )
        own = bool(info.context and info.context.get("bundled"))  # a bundled pack is its own key
        if value in ROBOTS or (value in bundled_keys() and not own):
            raise ValueError(f"{value!r} is a built-in robot; pick another key")
        return value

    @model_validator(mode="after")
    def _consistent(self) -> PackSpec:
        steps = round(1.0 / CONTROL_HZ / self.physics_dt)
        if steps < 1 or abs(steps * self.physics_dt - 1.0 / CONTROL_HZ) > 1e-9:
            raise ValueError(
                f"physics_dt = {self.physics_dt:g} does not divide the {CONTROL_HZ} Hz control "
                "step (0.02 s); use 0.02 / n, for example 0.005, 0.004 or 0.002"
            )
        if not self.joints:
            raise ValueError("joints: list at least one joint")
        if self.actuator == "pd":
            lacking = [
                name for name, joint in self.joints.items() if joint.kp is None or joint.kd is None
            ]
            if lacking:
                raise ValueError(
                    f"joints without kp and kd: {', '.join(lacking)} (actuator = 'pd' needs both; "
                    "use actuator = 'position' if the model's servos hold their own gains)"
                )
        unscaled = [name for name, joint in self.joints.items() if joint.action_scale is None]
        if self.action_scale is None and unscaled:
            raise ValueError(
                f"action_scale: set it once for the pack, or on every joint (missing on: "
                f"{', '.join(unscaled)})"
            )
        keys = [policy.key for policy in self.policies]
        if len(set(keys)) != len(keys):
            raise ValueError("policies: every key must be different")
        joints = len(self.joints)
        for index, term in enumerate(self.observation):
            width = _term_width(term, joints)
            if isinstance(term.scale, list) and width is not None and len(term.scale) != width:
                raise ValueError(
                    f"observation[{index}] ({term.term}): scale has {len(term.scale)} numbers "
                    f"but the term has {width}"
                )
        return self

    @property
    def substeps(self) -> int:
        return round(1.0 / CONTROL_HZ / self.physics_dt)

    def observation_length(self, sensor_widths: dict[str, int] | None = None) -> int | None:
        """How many numbers the observation holds; None while a sensor's width is unknown."""
        total = 0
        for term in self.observation:
            width = _term_width(term, len(self.joints), sensor_widths)
            if width is None:
                return None
            total += width
        return total


def _term_width(
    term: ObservationTerm, joints: int, sensor_widths: dict[str, int] | None = None
) -> int | None:
    fixed = {
        "base_lin_vel": 3,
        "base_ang_vel": 3,
        "projected_gravity": 3,
        "gait_phase": 2,
        "joint_pos": joints,
        "joint_vel": joints,
        "last_action": joints,
    }
    if term.term in fixed:
        return fixed[term.term]
    if term.term == "command":
        return term.size or 3
    return (sensor_widths or {}).get(term.sensor or "")


@dataclass(frozen=True)
class Pack:
    """A parsed ``robot.toml`` and the folder it was read from."""

    spec: PackSpec
    folder: Path

    @property
    def model_path(self) -> Path:
        return self.folder / self.spec.model

    def policy_path(self, key: str) -> Path:
        for policy in self.spec.policies:
            if policy.key == key:
                return self.folder / policy.file
        raise KeyError(key)


def _describe(error: ValidationError) -> list[str]:
    lines = []
    for item in error.errors():
        where = ".".join(str(part) for part in item["loc"]) or "robot.toml"
        message = item["msg"].removeprefix("Value error, ")
        lines.append(f"{where}: {message}")
    return lines


def pack_file(path: Path) -> Path:
    """``robot.toml`` for a pack folder, or the file itself when given one."""
    path = Path(path).expanduser()
    return path if path.is_file() else path / PACK_FILE


def parse_pack(text: str, *, bundled: bool = False) -> PackSpec:
    """Parse the text of a ``robot.toml``; raises ``PackError`` listing every problem."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise PackError([f"robot.toml is not valid TOML: {error}"]) from error
    try:
        return PackSpec.model_validate(data, context={"bundled": bundled})
    except ValidationError as error:
        raise PackError(_describe(error)) from error


def load_pack(path: Path) -> Pack:
    """Read a pack from its folder (or its ``robot.toml``)."""
    file = pack_file(path)
    if not file.is_file():
        raise PackError([f"no {PACK_FILE} in {Path(path).expanduser()}"])
    return Pack(parse_pack(file.read_text(encoding="utf-8")), file.parent.resolve())


def missing_files(pack: Pack) -> list[str]:
    """The model and policy files the pack names that are not on disk."""
    wanted = [("model", pack.spec.model)] + [
        (f"policy {policy.key}", policy.file) for policy in pack.spec.policies
    ]
    return [
        f"{label}: {name} not found" for label, name in wanted if not (pack.folder / name).is_file()
    ]


def _round_2(value: float) -> float:
    """Two significant figures: 51.45 -> 51, 308.7 -> 310, 3.4 -> 3.4."""
    return float(f"{value:.2g}")


def default_levels(mass_kg: float) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """(shoves in newtons, carried loads in kilograms) scaled to the robot's mass."""
    weight_n = mass_kg * _STANDARD_GRAVITY
    shoves = tuple(_round_2(weight_n * f) for f in _SHOVE_FRACTIONS)
    loads = tuple(_round_2(mass_kg * f) for f in _LOAD_FRACTIONS)
    return shoves, loads


def pack_info(pack: Pack, *, bundled: bool = False) -> RobotInfo:
    """The catalog entry for a pack, so the check-up and the app treat it like any robot.

    A bundled pack's model and meshes are downloaded into the cache (``<key>.json`` lists them),
    where its ``robot.toml`` and policies are copied; a user's pack lives in its own folder.
    """
    spec = pack.spec
    shoves, loads = default_levels(spec.mass_kg)
    levels = CheckupLevels(
        shoves_n=tuple(spec.levels.shoves_n or shoves),
        grips=tuple(spec.levels.grips),
        payloads_kg=tuple(spec.levels.payloads_kg or loads),
    )
    height_m = spec.height_cm / 100.0
    distance = spec.view.camera_distance_m or max(0.5, 1.9 * height_m)
    staging = Staging(
        model_file=spec.model,
        scene_name=spec.title,
        tile_m=spec.view.floor_tile_m or min(0.6, max(0.1, 0.4 * height_m)),
        camera_distance=distance,
        look_height=round(0.45 * height_m / distance, 3),
        unit=spec.height_cm / 25.0,
        shove_reference_n=levels.shoves_n[len(levels.shoves_n) // 2],
        editor_view=(round(0.95 * distance, 2), round(0.45 * height_m / (0.95 * distance), 3)),
    )
    policies = tuple(
        PolicyInfo(
            p.key,
            p.title,
            p.summary,
            p.file,
            gets_up=p.gets_up,
            starts_with_name=p.starts_with_name,
        )
        for p in spec.policies
    )
    return RobotInfo(
        key=spec.key,
        title=spec.title,
        maker=spec.maker,
        summary=spec.summary,
        height_cm=spec.height_cm,
        license_notice=spec.license.notice,
        credit=spec.license.credit,
        non_commercial=spec.license.non_commercial,
        policies=policies,
        default_policy=policies[0].key,
        walk_command=spec.walk_command,
        gait_period_s=spec.gait_period_s,
        levels=levels,
        staging=staging,
        folder=None if bundled else pack.folder,
        pack=True,
        manifest=f"{spec.key}.json" if bundled else None,
        first_run_s=spec.first_run_s,
    )


@cache
def _bundled_spec(key: str) -> PackSpec:
    text = _bundled_root().joinpath(key, PACK_FILE).read_text(encoding="utf-8")
    return parse_pack(text, bundled=True)


def bundled_pack(key: str) -> Pack:
    """A bundled pack, read from the package and located in the download cache."""
    return Pack(_bundled_spec(key), cache_root() / key)


def pack_for(key: str) -> Pack:
    """The pack that runs ``key``: a bundled one from the package, else the user's folder.

    A bundled robot must be downloaded (its model and meshes); asking checks that, and copies its
    pack files into place, so a run never uses a stale policy file from an older version.
    """
    from creature_lab.robots.fetch import is_installed, robot_dir

    if key in bundled_keys():
        if not is_installed(key):  # also copies the bundled files beside the download
            raise FileNotFoundError(
                f"{key} is not downloaded yet; run: creature-lab robots fetch {key}"
            )
        return bundled_pack(key)
    return load_pack(robot_dir(key))


def bundled_infos() -> dict[str, RobotInfo]:
    return {key: pack_info(bundled_pack(key), bundled=True) for key in bundled_keys()}


def _copy_tree(source: Traversable, target: Path) -> None:
    for entry in source.iterdir():
        destination = target / entry.name
        if entry.is_dir():
            _copy_tree(entry, destination)
            continue
        data = entry.read_bytes()
        if not destination.is_file() or destination.read_bytes() != data:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)


def sync_bundled(key: str) -> Path:
    """Copy a bundled pack's ``robot.toml`` and policies beside its downloaded model.

    Cheap and safe to repeat: only files that are missing or differ are written, so a newer
    Creature Lab's policies replace an older copy.
    """
    folder = cache_root() / key
    _copy_tree(_bundled_root().joinpath(key), folder)
    return folder


# ---- the registry of added packs ------------------------------------------------------------


def registry_path() -> Path:
    """The list of added packs lives beside the download cache (and moves with its override)."""
    return cache_root() / "packs.json"


def _read_registry() -> dict[str, str]:
    try:
        data = json.loads(registry_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    packs = data.get("packs") if isinstance(data, dict) else None
    return {str(k): str(v) for k, v in packs.items()} if isinstance(packs, dict) else {}


def _write_registry(packs: dict[str, str]) -> None:
    atomic_write_text(registry_path(), json.dumps({"packs": packs}, indent=2) + "\n")


def register_pack(path: Path) -> RobotInfo:
    """Remember a pack folder so every command and the app list it. Does not copy anything."""
    pack = load_pack(path)
    problems = missing_files(pack)
    if problems:
        raise PackError(problems)
    packs = _read_registry()
    owner = packs.get(pack.spec.key)
    if owner and Path(owner) != pack.folder and (Path(owner) / PACK_FILE).is_file():
        raise PackError(
            [
                f"{pack.spec.key!r} is already added from {owner}; remove it first "
                f"(creature-lab robots remove {pack.spec.key})"
            ]
        )
    packs[pack.spec.key] = str(pack.folder)
    _write_registry(packs)
    return pack_info(pack)


def unregister_pack(key: str) -> Path:
    """Forget a pack (its files are left alone) and return the folder it pointed at."""
    packs = _read_registry()
    if key not in packs:
        raise KeyError(key)
    folder = Path(packs.pop(key))
    _write_registry(packs)
    return folder


_cache: dict[Path, tuple[float, RobotInfo]] = {}


def registry_status() -> dict[str, tuple[Path, RobotInfo | None, str]]:
    """Every added pack: its folder, its catalog entry, and what is wrong with it (or "")."""
    status: dict[str, tuple[Path, RobotInfo | None, str]] = {}
    for key, folder in _read_registry().items():
        file = pack_file(Path(folder))
        try:
            stamp = file.stat().st_mtime
            cached = _cache.get(file)
            if cached and cached[0] == stamp:
                info = cached[1]
            else:
                info = pack_info(load_pack(file))
                _cache[file] = (stamp, info)
            if info.key != key:
                raise PackError([f"robot.toml now says key {info.key!r}, not {key!r}"])
            status[key] = (Path(folder), info, "")
        except (OSError, PackError) as error:
            reason = error.problems[0] if isinstance(error, PackError) else str(error)
            status[key] = (Path(folder), None, reason)
    return status


def registered_infos() -> dict[str, RobotInfo]:
    """Catalog entries of the added packs that can still be read."""
    return {key: info for key, (_, info, _) in registry_status().items() if info is not None}


def sensor_widths(model: Any) -> dict[str, int]:
    """Sensor name -> width, for a compiled MuJoCo model."""
    import mujoco

    widths = {}
    for index in range(model.nsensor):
        name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_SENSOR, index)
        if name:
            widths[name] = int(model.sensor_dim[index])
    return widths
