"""Human-readable labels and a hierarchy view for a creature's stable part ids.

Ids like ``leg_0l`` or ``seg3`` are chosen to stay stable across edits (see
``CreatureSpec``), not to be read by a person. ``friendly_label`` turns a known naming
convention into a short display label ("Leg 1 (left)", "Segment 4") for presentation
only - the underlying id, and everything saved to JSON, is untouched.
"""

from __future__ import annotations

import re

from creature_lab.schema import CreatureSpec

_SPECIAL = {"torso": "Torso", "head": "Head", "neck": "Neck"}
_SIDE_WORDS = {"l": "left", "r": "right"}
_ROW_PATTERN = re.compile(r"^(leg|hip)_(\d+)([lr])$")
_SEG_PATTERN = re.compile(r"^(?:seg|j)(\d+)$")
_LIMB_PATTERN = re.compile(r"^limb_(\d+)$")
_SIDED_PATTERN = re.compile(
    r"^(upper_leg|lower_leg|foot|hip|knee|ankle|"
    r"upper_arm|lower_arm|hand|shoulder|elbow|wrist)_([lr])$"
)


def friendly_label(part_or_joint_id: str) -> str:
    """Best-effort human-readable label for a stable Creature Lab id.

    Falls back to title-casing the id (underscores -> spaces) for anything that
    doesn't match a known scaffold naming convention, e.g. a custom-loaded JSON.
    """
    raw = part_or_joint_id
    if raw in _SPECIAL:
        return _SPECIAL[raw]

    match = _ROW_PATTERN.match(raw)
    if match:
        base, row, side = match.groups()
        word = "Leg" if base == "leg" else "Hip"
        return f"{word} {int(row) + 1} ({_SIDE_WORDS[side]})"

    match = _SIDED_PATTERN.match(raw)
    if match:
        base, side = match.groups()
        return f"{base.replace('_', ' ').capitalize()} ({_SIDE_WORDS[side]})"

    match = _SEG_PATTERN.match(raw)
    if match:
        (index,) = match.groups()
        return f"Segment {int(index) + 1}"

    match = _LIMB_PATTERN.match(raw)
    if match:
        (index,) = match.groups()
        return f"Limb {index}"

    return raw.replace("_", " ").strip().capitalize() or raw


def hierarchy_rows(creature: CreatureSpec) -> list[tuple[int, str]]:
    """``(depth, part_id)`` pairs from a depth-first walk starting at the root."""
    children: dict[str, list[str]] = {}
    for joint in creature.joints:
        children.setdefault(joint.parent, []).append(joint.child)
    child_ids = {joint.child for joint in creature.joints}
    root = next(part.id for part in creature.parts if part.id not in child_ids)

    rows: list[tuple[int, str]] = []

    def walk(part_id: str, depth: int) -> None:
        rows.append((depth, part_id))
        for child in children.get(part_id, []):
            walk(child, depth + 1)

    walk(root, 0)
    return rows


def hierarchy_markdown(creature: CreatureSpec, selected_id: str) -> str:
    """A compact indented tree (one markdown paragraph, line-broken per row).

    The selected part is bolded so the tree and the 3D/dropdown selection agree.
    """
    lines = []
    for depth, part_id in hierarchy_rows(creature):
        indent = "&nbsp;&nbsp;&nbsp;&nbsp;" * depth
        prefix = "└ " if depth else ""
        label = friendly_label(part_id)
        text = f"**{label}**" if part_id == selected_id else label
        lines.append(f"{indent}{prefix}{text}")
    return "  \n".join(lines)
