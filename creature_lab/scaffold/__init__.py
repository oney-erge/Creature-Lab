"""Procedural creature generators and morphology edits.

Each ``generate_*`` function is pure (``CreatureSpec`` out, no I/O) and returns a
fully validated creature, so a scaffolded creature is always runnable.
"""

from __future__ import annotations

from creature_lab.scaffold.humanoid import generate_humanoid
from creature_lab.scaffold.legged import generate_hexapod, generate_quadruped
from creature_lab.scaffold.mirror import mirror_limb
from creature_lab.scaffold.worm import generate_worm

#: Maps a scaffold name to its generator for the ``scaffold`` CLI group.
GENERATORS = {
    "worm": generate_worm,
    "quadruped": generate_quadruped,
    "hexapod": generate_hexapod,
    "humanoid": generate_humanoid,
}

__all__ = [
    "GENERATORS",
    "generate_hexapod",
    "generate_humanoid",
    "generate_quadruped",
    "generate_worm",
    "mirror_limb",
]
