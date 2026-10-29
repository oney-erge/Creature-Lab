# Roadmap

**The single active roadmap now lives in [`GRAND_PLAN.md`](GRAND_PLAN.md).** It reconciles the
three earlier plan drafts (archived under [`../archive/some-plans/`](../archive/some-plans/)) into one
phased plan. Read that first.

This page keeps only the durable guard rails.

## Where things stand

Version 0.2 has controller snapshots, verified packs, task-aware qualification, and a failure-first
editor. Recent work connects lessons, explanations, comparisons, and recorded replays. Public
packaging and clean-machine behavior still need direct verification, including the PyBullet
compiler requirement on Windows/macOS; a workflow configuration is not evidence of usability.

The next product decision should follow real usage: deepen education/curriculum first, morphology
research batches second, or undertake the much larger actuator/sensor/calibration work required
for hardware relevance. Do not imply hardware qualification before choosing and funding that path.

## Guard Rails

- Do not make new users choose between many backends before they see a creature move.
- Do not front-load architecture language ahead of the design → move → test → improve loop.
- Keep one authoritative roadmap. New plans update `GRAND_PLAN.md`; they do not spawn a new file.
- Do not add generic agent orchestration, personas, or memory APIs; Creature Lab is the physical
  experiment layer, not AgentGymnasium.
- Do not remove advanced commands that already work; keep them lower in the docs.
