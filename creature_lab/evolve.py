"""Mutation operators and evolution strategies (backend-agnostic).

This module mutates and selects ``CreatureSpec`` objects but never runs physics:
callers pass an ``evaluate`` (scalar fitness) or ``feature_evaluate`` (fitness +
behaviour descriptor) function, so every strategy is deterministic and testable
without a simulator (see CLAUDE.md: do not rely on exact physics reproducibility).

Strategies: ``hill_climb`` (greedy), ``genetic`` (population + crossover),
``map_elites`` (quality-diversity archive), ``cmaes`` (controller-parameter CMA-ES,
needs the optional ``cmaes`` package), and the ``tool_random_mutate`` operator
(proposes random edits through the validated agent tool layer).
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from creature_lab.schema import CreatureSpec
from creature_lab.schema.creature import JointType, ShapeType

# Bounds keep mutations in a safe, validatable range.
_LENGTH_BOUNDS = (0.05, 1.0)
_AMPLITUDE_BOUNDS = (0.0, 3.14)
_FREQUENCY_BOUNDS = (0.1, 5.0)

EvaluateFn = Callable[[CreatureSpec], float]


@dataclass(frozen=True)
class Evaluation:
    """Fitness plus a 2-D behaviour descriptor (for MAP-Elites)."""

    score: float
    features: tuple[float, float]


FeatureEvaluateFn = Callable[[CreatureSpec], Evaluation]


@dataclass(frozen=True)
class Attempt:
    """One evaluated candidate in a lineage."""

    index: int
    score: float
    accepted: bool
    parent: int | None = None
    generation: int = 0
    cell: tuple[int, int] | None = None


@dataclass
class EvolutionResult:
    best: CreatureSpec
    best_score: float
    history: list[Attempt]
    #: MAP-Elites only: cell key -> {"score", "features", "spec"}.
    archive: dict[tuple[int, int], dict] = field(default_factory=dict)


def _clamp(value: float, bounds: tuple[float, float]) -> float:
    low, high = bounds
    return max(low, min(high, value))


# --- mutation operators -------------------------------------------------------


def mutate_controller(creature: CreatureSpec, rng: random.Random) -> CreatureSpec:
    """Randomly nudge one motor's amplitude, frequency, or phase."""
    data = creature.model_dump()
    if not data["motors"]:
        return creature
    motor = rng.choice(data["motors"])
    operator = rng.choice(["amplitude", "frequency", "phase"])
    if operator == "amplitude":
        motor["amplitude"] = _clamp(motor["amplitude"] * rng.uniform(0.7, 1.3), _AMPLITUDE_BOUNDS)
    elif operator == "frequency":
        motor["frequency"] = _clamp(motor["frequency"] * rng.uniform(0.7, 1.3), _FREQUENCY_BOUNDS)
    else:
        motor["phase"] = motor["phase"] + rng.uniform(-0.5, 0.5)
    return _revalidate(data, creature)


def mutate_morphology(creature: CreatureSpec, rng: random.Random) -> CreatureSpec:
    """Randomly resize a limb, shift a joint anchor, or perturb a hinge axis."""
    data = creature.model_dump()
    limbs = [p for p in data["parts"] if p["shape"] in (ShapeType.CAPSULE, ShapeType.CYLINDER)]
    hinges = [j for j in data["joints"] if j["type"] == JointType.HINGE]
    operators = []
    if limbs:
        operators.append("length")
    if data["joints"]:
        operators.append("anchor")
    if hinges:
        operators.append("axis")
    if not operators:
        return creature

    operator = rng.choice(operators)
    if operator == "length":
        limb = rng.choice(limbs)
        limb["length"] = _clamp(limb["length"] * rng.uniform(0.85, 1.15), _LENGTH_BOUNDS)
    elif operator == "anchor":
        joint = rng.choice(data["joints"])
        axis = rng.randrange(3)
        anchor = list(joint["anchor"])
        anchor[axis] += rng.uniform(-0.05, 0.05)
        joint["anchor"] = anchor
    else:  # axis: perturb then let the schema re-normalize
        joint = rng.choice(hinges)
        vec = list(joint["axis"])
        idx = rng.randrange(3)
        vec[idx] += rng.uniform(-0.3, 0.3)
        if any(abs(c) > 1e-6 for c in vec):  # never hand the schema a zero axis
            joint["axis"] = vec
    return _revalidate(data, creature)


def mutate(
    creature: CreatureSpec,
    rng: random.Random,
    *,
    body: bool = True,
    controller: bool = True,
) -> CreatureSpec:
    """Apply one random mutation. ``body``/``controller`` gate the operator pool.

    Returns a validated creature (the original if the mutation would be invalid).
    """
    categories = []
    if controller and creature.motors:
        categories.append("controller")
    if body:
        categories.append("body")
    if not categories:
        return creature
    if rng.choice(categories) == "controller":
        return mutate_controller(creature, rng)
    return mutate_morphology(creature, rng)


def crossover(a: CreatureSpec, b: CreatureSpec, rng: random.Random) -> CreatureSpec:
    """Blend ``b``'s motor parameters into ``a``'s morphology (matched by joint id).

    Keeps ``a``'s parts/joints (so the result is always a valid topology) and, for
    each joint that both creatures motorize, takes ``b``'s amplitude/frequency/phase.
    """
    data = a.model_dump()
    b_motors = {m["joint"]: m for m in b.model_dump()["motors"]}
    for motor in data["motors"]:
        donor = b_motors.get(motor["joint"])
        if donor is not None and rng.random() < 0.5:
            motor["amplitude"] = donor["amplitude"]
            motor["frequency"] = donor["frequency"]
            motor["phase"] = donor["phase"]
    return _revalidate(data, a)


def _revalidate(data: dict, fallback: CreatureSpec) -> CreatureSpec:
    try:
        return CreatureSpec.model_validate(data)
    except ValueError:
        return fallback


def make_mutator(
    body: bool, controller: bool
) -> Callable[[CreatureSpec, random.Random], CreatureSpec]:
    """Build a ``mutate``-style callable with body/controller operators gated."""
    return lambda spec, rng: mutate(spec, rng, body=body, controller=controller)


# --- strategies ---------------------------------------------------------------


def hill_climb(
    seed: CreatureSpec,
    evaluate: EvaluateFn,
    *,
    attempts: int,
    rng: random.Random,
    mutate_fn: Callable[[CreatureSpec, random.Random], CreatureSpec] = mutate,
) -> EvolutionResult:
    """Greedily mutate ``seed``, keeping any candidate that scores higher."""
    if attempts < 0:
        raise ValueError("attempts must not be negative")

    best = seed
    best_score = evaluate(seed)
    best_index = 0
    history = [Attempt(index=0, score=best_score, accepted=True)]

    for index in range(1, attempts + 1):
        candidate = mutate_fn(best, rng)
        score = evaluate(candidate)
        accepted = score > best_score
        history.append(Attempt(index, score, accepted, parent=best_index, generation=index))
        if accepted:
            best, best_score, best_index = candidate, score, index

    return EvolutionResult(best, best_score, history)


def genetic(
    seed: CreatureSpec,
    evaluate: EvaluateFn,
    *,
    attempts: int,
    rng: random.Random,
    population: int = 8,
    mutate_fn: Callable[[CreatureSpec, random.Random], CreatureSpec] = mutate,
) -> EvolutionResult:
    """Population-based GA: select the fittest, breed by crossover + mutation."""
    if attempts < 0:
        raise ValueError("attempts must not be negative")
    population = max(2, population)

    pop = [seed] + [mutate_fn(seed, rng) for _ in range(population - 1)]
    scored = [(evaluate(spec), idx, spec) for idx, spec in enumerate(pop)]
    history = [Attempt(idx, score, True, generation=0) for score, idx, _ in scored]
    best_score, _, best = max(scored, key=lambda item: item[0])

    index = population
    generation = 1
    while index < attempts + 1:
        scored.sort(key=lambda item: item[0], reverse=True)
        parents = scored[: max(2, population // 2)]
        children: list[tuple[float, int, CreatureSpec]] = list(parents)  # elitism
        while len(children) < population and index < attempts + 1:
            pa, pb = rng.choice(parents), rng.choice(parents)
            child = mutate_fn(crossover(pa[2], pb[2], rng), rng)
            score = evaluate(child)
            accepted = score > best_score
            history.append(Attempt(index, score, accepted, parent=pa[1], generation=generation))
            if accepted:
                best, best_score = child, score
            children.append((score, index, child))
            index += 1
        scored = children
        generation += 1

    return EvolutionResult(best, best_score, history)


def _cell_of(
    features: tuple[float, float],
    bins: tuple[int, int],
    bounds: tuple[tuple[float, float], tuple[float, float]],
) -> tuple[int, int]:
    cell = []
    for value, n, (lo, hi) in zip(features, bins, bounds, strict=True):
        frac = 0.0 if hi == lo else (value - lo) / (hi - lo)
        cell.append(max(0, min(n - 1, int(frac * n))))
    return cell[0], cell[1]


def map_elites(
    seed: CreatureSpec,
    feature_evaluate: FeatureEvaluateFn,
    *,
    attempts: int,
    rng: random.Random,
    bins: tuple[int, int] = (10, 5),
    bounds: tuple[tuple[float, float], tuple[float, float]] = ((-1.0, 2.0), (0.0, 1.0)),
    mutate_fn: Callable[[CreatureSpec, random.Random], CreatureSpec] = mutate,
) -> EvolutionResult:
    """Quality-diversity search: keep the best creature in each behaviour cell."""
    if attempts < 0:
        raise ValueError("attempts must not be negative")

    archive: dict[tuple[int, int], dict] = {}

    def place(spec: CreatureSpec, index: int, parent: int | None) -> Attempt:
        """Evaluate ``spec`` once and insert it if it wins its cell."""
        ev = feature_evaluate(spec)
        cell = _cell_of(ev.features, bins, bounds)
        current = archive.get(cell)
        accepted = current is None or ev.score > current["score"]
        if accepted:
            archive[cell] = {
                "score": ev.score,
                "features": ev.features,
                "spec": spec,
                "index": index,
            }
        return Attempt(index, ev.score, accepted, parent=parent, generation=index, cell=cell)

    history = [place(seed, 0, None)]
    for index in range(1, attempts + 1):
        parent = archive[rng.choice(list(archive))]
        child = mutate_fn(parent["spec"], rng)
        history.append(place(child, index, parent["index"]))

    best_cell = max(archive, key=lambda c: archive[c]["score"])
    return EvolutionResult(
        best=archive[best_cell]["spec"],
        best_score=archive[best_cell]["score"],
        history=history,
        archive=archive,
    )


def cmaes(
    seed: CreatureSpec,
    evaluate: EvaluateFn,
    *,
    attempts: int,
    rng: random.Random,
    sigma: float = 0.3,
) -> EvolutionResult:
    """CMA-ES over the motor parameters (amplitude, frequency, phase per motor).

    Morphology is held fixed. Requires the optional ``cmaes`` package.
    """
    try:
        import numpy as np
        from cmaes import CMA
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise RuntimeError("CMA-ES needs the 'cmaes' package — `uv sync --extra evolve`") from exc

    motors = seed.model_dump()["motors"]
    if not motors:
        raise ValueError("cmaes needs a creature with at least one motor")

    x0 = np.array([v for m in motors for v in (m["amplitude"], m["frequency"], m["phase"])])

    def decode(x: np.ndarray) -> CreatureSpec:
        data = seed.model_dump()
        for i, motor in enumerate(data["motors"]):
            motor["amplitude"] = _clamp(float(x[3 * i]), _AMPLITUDE_BOUNDS)
            motor["frequency"] = _clamp(float(x[3 * i + 1]), _FREQUENCY_BOUNDS)
            motor["phase"] = float(x[3 * i + 2])
        return _revalidate(data, seed)

    optimizer = CMA(mean=x0, sigma=sigma, seed=rng.randrange(2**31))
    best, best_score = seed, evaluate(seed)
    history = [Attempt(0, best_score, True)]

    index = 1
    while index <= attempts:
        solutions = []
        for _ in range(optimizer.population_size):
            x = optimizer.ask()
            candidate = decode(x)
            score = evaluate(candidate)
            solutions.append((x, -score))  # CMA-ES minimizes
            accepted = score > best_score
            history.append(Attempt(index, score, accepted, generation=index))
            if accepted:
                best, best_score = candidate, score
            index += 1
            if index > attempts:
                break
        if len(solutions) == optimizer.population_size:
            optimizer.tell(solutions)

    return EvolutionResult(best, best_score, history)


def tool_random_mutate(
    spec: CreatureSpec,
    rng: random.Random,
    *,
    on_propose: Callable[[Any], None] | None = None,
) -> CreatureSpec:
    """A ``mutate_fn`` that proposes one edit through the validated agent tool layer.

    Uses the offline, no-provider ``RandomToolPolicy`` (so ``evolve --strategy tool_random`` needs
    no API key and stays deterministic/testable), reseeded from ``rng`` on every call so a
    fixed top-level ``--seed`` still reproduces the whole run. A creature with nothing
    tunable yields a "no-op" proposal that the tool layer rejects; that is not an error
    here, it just means this attempt leaves the spec unchanged. ``on_propose``, if given,
    is called with every ``Proposal`` (accepted or not) so a caller can record rationale.
    """
    from creature_lab.agents.baseline import RandomToolPolicy
    from creature_lab.agents.loop import Observation
    from creature_lab.agents.tools import ToolError, apply_tool

    policy = RandomToolPolicy(seed=rng.randrange(2**31))
    proposal = policy(Observation(spec, 0.0, 0))
    if on_propose is not None:
        on_propose(proposal)
    try:
        return apply_tool(spec, proposal.tool, proposal.args)
    except ToolError:
        return spec


# Backwards-compatible Python API for callers using the former misleading name.
llm_mutate = tool_random_mutate
