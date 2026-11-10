"""Environment checks (`doctor`) and episode summaries (`inspect`).

Both are intentionally light: the doctor checks use ``importlib.util.find_spec`` so
they never import heavy optional deps, and ``summarize_episode`` is a pure function
of a trace (plus an optional task) — no backend required.
"""

from __future__ import annotations

import importlib.util
import math
import os
import platform
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass

from creature_lab.diagnosis import first_fall_time
from creature_lab.schema import CreatureSpec, EpisodeSummary, EpisodeTrace, TaskSpec

_PROVIDER_KEYS = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "GROQ_API_KEY",
    "MISTRAL_API_KEY",
)


@dataclass(frozen=True)
class DoctorCheck:
    """One environment check. ``status`` is one of ok|missing|warn|info."""

    name: str
    status: str
    detail: str


def _installed(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


def collect_doctor_checks() -> list[DoctorCheck]:
    """Inspect the environment: platform, optional extras, and an example run.

    Diagnostics must never crash, so every check is guarded — a failing check
    becomes a `warn` row rather than propagating an exception.
    """
    return [
        DoctorCheck(
            "platform",
            "info",
            f"Python {platform.python_version()} on {platform.platform()}",
        ),
        _safe("sim (pybullet)", _sim_check),
        _safe("mujoco", _mujoco_check),
        _safe("viz (viser)", _viz_check),
        _safe("export (imageio)", _export_check),
        _safe("app (browser)", _app_check),
        _safe("llm (litellm)", _llm_check),
        _safe("examples run", _examples_check),
    ]


def _safe(name: str, check: Callable[[], DoctorCheck]) -> DoctorCheck:
    try:
        return check()
    except Exception as exc:  # a diagnostic must report failures, not raise them
        return DoctorCheck(name, "warn", f"check failed: {exc}")


def _extra_check(name: str, module: str, hint: str) -> DoctorCheck:
    if _installed(module):
        return DoctorCheck(name, "ok", f"{module} importable")
    return DoctorCheck(name, "missing", f"not installed — `{hint}`")


def _sim_check() -> DoctorCheck:
    return _extra_check("sim (pybullet)", "pybullet", "uv sync --extra sim")


def _mujoco_check() -> DoctorCheck:
    if _installed("mujoco"):
        return DoctorCheck("mujoco", "ok", "mujoco importable (run --backend mujoco)")
    return DoctorCheck("mujoco", "info", "not installed — `uv sync --extra mujoco` (optional)")


def _viz_check() -> DoctorCheck:
    if not _installed("viser"):
        return DoctorCheck("viz (viser)", "missing", "not installed — `uv sync --extra viz`")
    missing = [module for module in ("trimesh", "numpy") if not _installed(module)]
    if missing:
        return DoctorCheck(
            "viz (viser)", "warn", f"viser present but {', '.join(missing)} missing (capsules)"
        )
    return DoctorCheck("viz (viser)", "ok", "viser + trimesh + numpy importable")


def _app_check() -> DoctorCheck:
    """The browser app needs the `web` and `robots` extras; the launcher installs them."""
    needed = ("fastapi", "uvicorn", "mujoco", "onnxruntime", "imageio", "PIL")
    missing = [module for module in needed if not _installed(module)]
    if not missing:
        return DoctorCheck("app (browser)", "ok", "fastapi + uvicorn + mujoco + onnxruntime")
    return DoctorCheck(
        "app (browser)",
        "info",
        f"{', '.join(missing)} not installed — `uv sync --inexact --extra web --extra robots`",
    )


def _export_check() -> DoctorCheck:
    if not _installed("imageio"):
        return DoctorCheck(
            "export (imageio)", "missing", "not installed — `uv sync --extra export`"
        )
    formats = []
    if _installed("PIL"):
        formats.append("gif")
    if _installed("imageio_ffmpeg"):
        formats.append("mp4")
    if not formats:
        return DoctorCheck("export (imageio)", "warn", "imageio present but no gif/mp4 writer")
    return DoctorCheck("export (imageio)", "ok", f"writers: {', '.join(formats)}")


def _llm_check() -> DoctorCheck:
    if not _installed("litellm"):
        return DoctorCheck(
            "llm (litellm)", "info", "not installed — `uv sync --extra llm` (optional)"
        )
    configured = [key for key in _PROVIDER_KEYS if os.environ.get(key)]
    if not configured:
        return DoctorCheck("llm (litellm)", "warn", "installed but no provider API key in env")
    return DoctorCheck("llm (litellm)", "ok", f"provider key set: {configured[0]}")


def _examples_check() -> DoctorCheck:
    """Confirm the built-in creature/task validate, cross-check, and (if possible) step."""
    from creature_lab.library import default_creature, default_task
    from creature_lab.validation import validate_episode_inputs

    creature = default_creature()
    task = default_task()
    validate_episode_inputs(creature, task)  # raises only on hard errors (none expected)

    if not _installed("pybullet"):
        return DoctorCheck(
            "examples run", "ok", "built-in creature/task validate (install sim to simulate)"
        )

    from creature_lab.backends.pybullet_backend import PyBulletBackend

    backend = PyBulletBackend()
    try:
        backend.build(creature, task)
        backend.step(task.timestep)
    finally:
        backend.close()
    return DoctorCheck("examples run", "ok", "built-in creature simulates one step")


def summarize_episode(
    trace: EpisodeTrace, task: TaskSpec | None = None, creature: CreatureSpec | None = None
) -> EpisodeSummary:
    """Compute a compact summary of a trace (pure; no backend).

    ``creature``, when given, switches ``fell`` to reward-independent root-part
    orientation detection (``creature_lab.diagnosis.first_fall_time``). Without it,
    ``fell`` falls back to the trace's ``fall`` score component, which is only
    nonzero when the task sets ``reward.fall_penalty`` - a creature that visibly
    toppled on a task without one would otherwise always report ``fell=False``.
    """
    frames = trace.frames
    # Total simulated time: the final frame's timestamp (the sim began at t=0, first frame at dt).
    duration = frames[-1].t

    first_centroid = _centroid(frames[0])
    last_centroid = _centroid(frames[-1])
    displacement = tuple(b - a for a, b in zip(first_centroid, last_centroid, strict=True))
    net_displacement = math.sqrt(sum(component * component for component in displacement))

    target_progress: float | None = None
    if task is not None and task.target is not None:
        target = task.target.position
        target_progress = math.dist(first_centroid, target) - math.dist(last_centroid, target)

    component_scores: dict[str, float] = {}
    warnings: list[str] = []
    if trace.meta is not None:
        component_scores = dict(trace.meta.score_summary)
        warnings = list(trace.meta.warnings)

    fell: bool | None
    if creature is not None:
        fell = first_fall_time(trace, creature) is not None
    elif "fall" in component_scores:
        fell = component_scores["fall"] < 0
    else:
        fell = None

    damage_events = [
        event for frame in frames for event in frame.events if event.startswith("damage:")
    ]
    contacts: Counter[str] = Counter()
    for frame in frames:
        for contact in frame.contacts:
            contacts[contact.part_id] += 1

    return EpisodeSummary(
        frame_count=len(frames),
        duration=duration,
        final_score=trace.score,
        component_scores=component_scores,
        net_displacement=net_displacement,
        forward_displacement=displacement[0],
        target_progress=target_progress,
        total_joint_motion=_total_joint_motion(trace),
        fell=fell,
        damage_events=damage_events,
        contacts_by_part=dict(contacts),
        warnings=warnings,
    )


def _centroid(frame) -> tuple[float, float, float]:
    positions = [pose.position for pose in frame.parts.values()]
    count = len(positions)
    return tuple(sum(axis) / count for axis in zip(*positions, strict=True))


def _total_joint_motion(trace: EpisodeTrace) -> float:
    """Sum of |Δ joint angle| over the episode — an actuation-effort proxy."""
    total = 0.0
    previous: dict[str, float] = {}
    for frame in trace.frames:
        for joint_id, angle in frame.joint_angles.items():
            if joint_id in previous:
                total += abs(angle - previous[joint_id])
            previous[joint_id] = angle
    return total
