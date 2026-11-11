"""Shared by the robot-pack tests: the example pack and small helpers to bend a copy of it."""

from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "robot-pack"


def copy_example(target: Path) -> Path:
    """A writable copy of the example pack (without the generated scene or caches)."""
    shutil.copytree(
        EXAMPLE, target, ignore=shutil.ignore_patterns("__pycache__", "checkup_scene.xml")
    )
    return target


def edit(folder: Path, name: str, old: str, new: str) -> None:
    """Replace the first ``old`` in a pack file; fails loudly if the example changed."""
    path = folder / name
    text = path.read_text(encoding="utf-8")
    assert old in text, f"{old!r} is not in {name}"
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def make_policy_module():
    """The example's own ``make_policy.py``, so tests can write ONNX policies of any shape."""
    spec = importlib.util.spec_from_file_location("make_policy", EXAMPLE / "make_policy.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
