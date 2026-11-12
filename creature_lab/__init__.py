"""Creature Lab: a minimal, visual, backend-agnostic creature simulation lab."""

from creature_lab.schema import (
    CreatureSpec,
    EpisodeTrace,
    FrameState,
    TaskSpec,
)

VERSION = "0.4.1"

__all__ = [
    "VERSION",
    "CreatureSpec",
    "EpisodeTrace",
    "FrameState",
    "TaskSpec",
]
