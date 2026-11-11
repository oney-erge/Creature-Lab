"""Shove a designed creature, and try to improve its gait: the designer's two new tests.

A shove is a one-step sideways kick on the body, sized by the speed it gives the creature (so a
2 kg quadruped and a 60 kg humanoid are shoved comparably) and also stated as the force that
would do the same in 0.2 s, the length of the robot check-up's shove. Nothing here accepts a number
from the browser except how many tries "Improve it" may make, which is clamped.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from creature_lab.diagnosis import first_fall_time, root_id
from creature_lab.schema import CreatureSpec, TaskSpec
from creature_lab.schema.task import ImpulseEventSpec

#: Sideways speeds, in metres per second, that the shove test gives the body (both sides).
SHOVE_SPEEDS = (0.2, 0.4, 0.6, 0.8, 1.0, 1.5, 2.0, 3.0, 5.0)
#: The shoves "Improve it" practises on, weakest first (each from both sides).
LADDER = (0.4, 0.8, 1.5, 3.0)
#: When the shove lands, in seconds into the run (the gait has settled by then).
SHOVE_AT_S = 2.0
#: How long a robot check-up shove lasts; the force figure is for this long.
SHOVE_FOR_S = 0.2
MIN_TRIES, MAX_TRIES = 10, 60


@dataclass
class Outcome:
    """One run: its score, its distance, and whether the body toppled."""

    score: float
    forward: float
    fell: bool


def mass_kg(creature: CreatureSpec) -> float:
    return float(sum(part.mass for part in creature.parts))


def _run(
    creature: CreatureSpec,
    task: TaskSpec,
    controller: str,
    backend: str,
    *,
    speed: float = 0.0,
    side: float = 1.0,
) -> Outcome:
    """Simulate one episode, optionally with a shove of ``speed`` m/s to one side."""
    from creature_lab.cli import _simulate
    from creature_lab.diagnostics import summarize_episode

    if speed > 0:
        kick = mass_kg(creature) * speed / task.timestep  # one step: force x dt = mass x speed
        task = task.model_copy(
            update={
                "impulse_event": ImpulseEventSpec(
                    time=min(SHOVE_AT_S, task.duration * 0.6),
                    part_id=root_id(creature),
                    force=(0.0, side * kick, 0.0),
                )
            }
        )
    trace = _simulate(creature, task, seed=0, controller=controller, backend=backend)
    summary = summarize_episode(trace, task, creature)
    return Outcome(
        score=float(trace.score),
        forward=float(summary.forward_displacement),
        fell=first_fall_time(trace, creature) is not None,
    )


def _newtons(creature: CreatureSpec, speed: float) -> float:
    """The force that gives the creature ``speed`` in a robot check-up shove's 0.2 s."""
    return mass_kg(creature) * speed / SHOVE_FOR_S


def shove_test(creature: CreatureSpec, task: TaskSpec, controller: str, backend: str) -> dict:
    """How hard a sideways shove the creature stays upright through, on each side."""
    baseline = _run(creature, task, controller, backend)
    result: dict = {
        "massKg": round(mass_kg(creature), 2),
        "baselineFell": baseline.fell,
        "score": round(baseline.score, 3),
        "forward": round(baseline.forward, 2),
        "levels": [],
        "survivesUpTo": None,
        "survivesUpToN": None,
        "shoveAtS": min(SHOVE_AT_S, task.duration * 0.6),
    }
    if baseline.fell:  # it cannot stay up with no shove, so shoving it says nothing
        return result
    best: float | None = None
    still_standing = True
    for speed in SHOVE_SPEEDS:
        left = not _run(creature, task, controller, backend, speed=speed, side=1.0).fell
        right = not _run(creature, task, controller, backend, speed=speed, side=-1.0).fell
        result["levels"].append(
            {
                "speed": speed,
                "newtons": round(_newtons(creature, speed), 1),
                "left": left,
                "right": right,
            }
        )
        still_standing = still_standing and left and right
        if still_standing:
            best = speed
    result["survivesUpTo"] = best
    result["survivesUpToN"] = None if best is None else round(_newtons(creature, best), 1)
    return result


#: A try with equally many ladder steps must score at least this much more to count.
_MIN_SCORE_GAIN = 0.05


@dataclass
class Improvement:
    """What ``improve`` found: better slider values, or ``None`` if nothing beat the current."""

    values: dict[str, float] | None
    tried: int
    kept: int
    #: The full shove test of the design before, and of the better one (``None`` if none found).
    before: dict
    after: dict | None


def _grade(
    creature: CreatureSpec, task: TaskSpec, controller: str, backend: str
) -> tuple[int, float]:
    """How many steps of the ladder the creature stays up through, then its score.

    A creature that topples with no shove at all grades -1, so it can never win a try.
    """
    run = _run(creature, task, controller, backend)
    if run.fell:
        return (-1, run.score)
    steps = 0
    for speed in LADDER:
        if any(
            _run(creature, task, controller, backend, speed=speed, side=side).fell
            for side in (1.0, -1.0)
        ):
            break
        steps += 1
    return (steps, run.score)


def _better(new: tuple[int, float], old: tuple[int, float]) -> bool:
    """Stays up through more shoves, or equally many and walks clearly farther."""
    if new[0] != old[0]:
        return new[0] > old[0]
    return new[1] > old[1] + _MIN_SCORE_GAIN


def _nudge(preset: str, values: dict[str, float], rng: random.Random) -> dict[str, float]:
    """One slider moved a little (to a step the slider allows), the rest left alone."""
    from creature_lab.editor import presets

    spec = rng.choice(presets.CREATURE_PRESETS[preset].params)
    moved = values[spec.key] + rng.gauss(0.0, 0.2) * (spec.maximum - spec.minimum)
    moved = min(max(moved, spec.minimum), spec.maximum)
    snapped = float(round(moved)) if spec.kind == "int" else round(moved / spec.step) * spec.step
    return {**values, spec.key: min(max(snapped, spec.minimum), spec.maximum)}


def improve(
    preset: str,
    values: dict[str, float],
    task: TaskSpec,
    backend: str,
    *,
    tries: int = 30,
    seed: int = 0,
) -> Improvement:
    """Try small changes to the design's sliders; offer one only if it is clearly better.

    The search practises on a short ladder of shoves for speed. Whatever it finds is then
    re-measured on the full ladder, side by side with the original, and is offered only if it
    stays up through at least as many shoves as before and is better on one of the two measures
    (more shoves, or clearly farther). The creature's gait is whatever the preset gives it, the
    same one the person watched, so "before" is exactly what they saw.
    """
    from creature_lab.cli import _curated_controller
    from creature_lab.editor import presets

    tries = max(MIN_TRIES, min(int(tries), MAX_TRIES))
    rng = random.Random(seed)

    def build(candidate: dict[str, float]) -> tuple[CreatureSpec, str]:
        creature = presets.generate_creature(preset, candidate)
        return creature, _curated_controller(creature)

    def grade(candidate: dict[str, float]) -> tuple[int, float]:
        creature, controller = build(candidate)
        return _grade(creature, task, controller, backend)

    best, best_grade = dict(values), grade(values)
    kept = 0
    for _ in range(tries):
        candidate = _nudge(preset, best, rng)
        if candidate == best:
            continue
        candidate_grade = grade(candidate)
        if _better(candidate_grade, best_grade):
            best, best_grade, kept = candidate, candidate_grade, kept + 1

    original, original_controller = build(values)
    before = shove_test(original, task, original_controller, backend)
    if not kept:
        return Improvement(None, tries, 0, before, None)
    creature, controller = build(best)
    after = shove_test(creature, task, controller, backend)
    # Judged on the full ladder, in the same order as the search: more shoves first, then distance.
    old = (_limit(before), before["score"])
    new = (_limit(after), after["score"])
    if after["baselineFell"] or not _better(new, old):
        return Improvement(None, tries, kept, before, None)
    return Improvement(best, tries, kept, before, after)


def _limit(test: dict) -> int:
    """How many speeds of the full ladder, in a row from the gentlest, it stayed up through."""
    if test["baselineFell"]:
        return -1
    return 0 if test["survivesUpTo"] is None else SHOVE_SPEEDS.index(test["survivesUpTo"]) + 1
