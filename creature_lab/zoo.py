"""The Creature Zoo: a curated gallery of ready-to-run creatures and tasks.

Each entry lives under ``creature_lab/zoo/<name>/`` with a ``creature.json`` and a
``tasks/`` directory. The files are static (shareable, diff-able) and shipped with
the package, so ``creature-lab zoo run <name>`` works from an installed wheel.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from creature_lab.schema import CreatureSpec, TaskSpec

ZOO_DIR = Path(__file__).parent / "zoo"

#: Preferred default task names (first match wins) when a creature offers several.
_PREFERRED_DEFAULTS = ("crawl_forward", "walk", "balance")
_EXPLICIT_DEFAULT_TASKS = {
    "humanoid_minimal": "balance",
    "humanoid_12dof": "walk",
}


@dataclass(frozen=True)
class ZooShowcase:
    """Measured first-run contract, or an explicitly labeled challenge."""

    task: str
    status: str
    min_score: float | None
    require_no_fall: bool
    description: str


ZOO_SHOWCASES: dict[str, ZooShowcase] = {
    "quadruped": ZooShowcase(
        "crawl_forward", "showcase", 1.5, True, "Fast curated four-legged crawl"
    ),
    "hexapod": ZooShowcase(
        "crawl_forward", "showcase", 1.2, True, "Stable coordinated six-legged crawl"
    ),
    "worm": ZooShowcase(
        "crawl_forward",
        "challenge",
        None,
        False,
        "Fast body-wave motion that still exposes rollover instability",
    ),
    "damaged_quadruped": ZooShowcase(
        "recover", "showcase", 1.5, True, "Keeps moving after a scripted failure"
    ),
    "humanoid_minimal": ZooShowcase(
        "balance",
        "challenge",
        None,
        False,
        "Eight-DOF biped without feet; use it to diagnose structural instability",
    ),
    "humanoid_12dof": ZooShowcase(
        "walk", "showcase", 0.3, True, "Measured two-foot humanoid walking gait"
    ),
    "tripod": ZooShowcase(
        "crawl_forward",
        "challenge",
        None,
        False,
        "Intentionally difficult asymmetric locomotion challenge",
    ),
}


def list_zoo_creatures() -> list[str]:
    """Names of all zoo creatures (directories containing a ``creature.json``)."""
    if not ZOO_DIR.is_dir():
        return []
    return sorted(
        entry.name
        for entry in ZOO_DIR.iterdir()
        if entry.is_dir() and (entry / "creature.json").exists()
    )


def _creature_dir(name: str) -> Path:
    directory = ZOO_DIR / name
    if not (directory / "creature.json").exists():
        available = ", ".join(list_zoo_creatures())
        raise KeyError(f"unknown zoo creature {name!r}; choose one of: {available}")
    return directory


def zoo_tasks(name: str) -> list[str]:
    """Task names available for a zoo creature."""
    tasks_dir = _creature_dir(name) / "tasks"
    if not tasks_dir.is_dir():
        return []
    return sorted(path.stem for path in tasks_dir.glob("*.json"))


def default_task_name(name: str) -> str:
    """The task used when ``zoo run`` is given no ``--task`` (prefers crawl_forward)."""
    tasks = zoo_tasks(name)
    if not tasks:
        raise KeyError(f"zoo creature {name!r} has no tasks")
    explicit = _EXPLICIT_DEFAULT_TASKS.get(name)
    if explicit in tasks:
        return explicit
    for preferred in _PREFERRED_DEFAULTS:
        if preferred in tasks:
            return preferred
    return tasks[0]


def zoo_showcase(name: str) -> ZooShowcase | None:
    """Return the first-run behavioral contract for a Zoo entry, if declared."""
    _creature_dir(name)
    return ZOO_SHOWCASES.get(name)


def zoo_creature(name: str, task: str | None = None) -> tuple[CreatureSpec, TaskSpec]:
    """Load a zoo creature and one of its tasks (its default task if unspecified)."""
    directory = _creature_dir(name)
    creature = CreatureSpec.model_validate_json((directory / "creature.json").read_text())
    task_name = task or default_task_name(name)
    task_path = directory / "tasks" / f"{task_name}.json"
    if not task_path.exists():
        available = ", ".join(zoo_tasks(name))
        raise KeyError(f"unknown task {task_name!r} for {name!r}; choose one of: {available}")
    task_spec = TaskSpec.model_validate_json(task_path.read_text())
    return creature, task_spec


def zoo_optimized_controller(name: str) -> Path | None:
    """Path to a packaged, CMA-ES-optimized ``controller.json`` for this zoo creature
    (see ``creature-lab optimize``), if one is shipped - ``None`` otherwise. The
    creature's own ``creature.json`` motors are left at their original, un-tuned
    values; this is an opt-in, additive artifact so baselines stay unaffected.
    """
    path = _creature_dir(name) / "controller.json"
    return path if path.exists() else None


def zoo_baseline(name: str, task: str, backend: str = "pybullet") -> dict[str, Any] | None:
    """Load the optional packaged baseline metadata for a zoo creature/task pair.

    ``backend="pybullet"`` (the default) reads ``baselines/<task>.json``, the original
    filename; any other backend reads the backend-suffixed ``baselines/<task>.<backend>.json``.
    """
    filename = f"{task}.json" if backend == "pybullet" else f"{task}.{backend}.json"
    path = _creature_dir(name) / "baselines" / filename
    return json.loads(path.read_text()) if path.exists() else None


def validate_all() -> list[tuple[str, str]]:
    """Cross-validate every (creature, task) pair in the zoo.

    Returns the list of validated ``(creature, task)`` name pairs. Raises if any
    creature, task, or their combination is invalid (so ``zoo validate-all`` can
    surface a broken gallery before shipping).
    """
    from creature_lab.validation import validate_episode_inputs

    checked: list[tuple[str, str]] = []
    for name in list_zoo_creatures():
        for task_name in zoo_tasks(name):
            creature, task = zoo_creature(name, task_name)
            validate_episode_inputs(creature, task)  # raises EpisodeInputError on hard errors
            checked.append((name, task_name))
    return checked
