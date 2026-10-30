"""Optional, visual-only details shared by the live viewer and video renderer."""

from __future__ import annotations

from dataclasses import dataclass

from creature_lab.schema import CreatureSpec, EpisodeTrace, PartSpec, ShapeType


@dataclass(frozen=True)
class Decoration:
    name: str
    part: str
    shape: str
    position: tuple[float, float, float]
    size: tuple[float, float, float]
    color: tuple[float, float, float]


def comparison_camera(a: EpisodeTrace, b: EpisodeTrace) -> tuple[float, tuple[float, float]]:
    """Shared distance and horizontal target for two recorded runs."""
    traces = (a, b)
    heights = [
        max(p.position[2] for p in trace.frames[0].parts.values())
        - min(p.position[2] for p in trace.frames[0].parts.values())
        for trace in traces
    ]
    positions = [
        pose.position for trace in traces for frame in trace.frames for pose in frame.parts.values()
    ]
    bounds = [(min(p[i] for p in positions), max(p[i] for p in positions)) for i in (0, 1)]
    center = tuple((low + high) / 2 for low, high in bounds)
    span = max(high - low for low, high in bounds)
    return max(0.8, max(heights) * 2.5, span * 1.8), (center[0], center[1])


def visual_part(creature: CreatureSpec, part: PartSpec) -> PartSpec:
    """Use a rounded visual shell for the duckling's box-shaped physics body."""
    if (
        creature.metadata.get("appearance") == "duckling"
        and part.id == "torso"
        and part.shape == ShapeType.BOX
        and part.size is not None
    ):
        return part.model_copy(
            update={"shape": ShapeType.SPHERE, "radius": max(part.size) * 0.55, "size": None}
        )
    return part


def decorations(creature: CreatureSpec) -> list[Decoration]:
    """Return face details in the head's local frame; they never affect physics."""
    style = creature.metadata.get("appearance")
    if style != "duckling" and not creature.name.startswith("humanoid"):
        return []
    head = next((part for part in creature.parts if part.id == "head"), None)
    if head is None or head.radius is None:
        return []
    radius = head.radius
    eyes = [
        Decoration(
            f"eye_{side}",
            "head",
            "sphere",
            (0.72 * radius, sign * 0.55 * radius, 0.30 * radius),
            (0.12 * radius,) * 3,
            (0.08, 0.10, 0.13),
        )
        for side, sign in (("l", 1), ("r", -1))
    ]
    if style != "duckling":
        return eyes
    return [
        Decoration(
            "beak",
            "head",
            "box",
            (0.95 * radius, 0, -0.18 * radius),
            (0.7 * radius, 0.8 * radius, 0.24 * radius),
            (0.96, 0.42, 0.10),
        ),
        *eyes,
    ]
