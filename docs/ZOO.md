# Creature Zoo

The Creature Zoo is the packaged gallery of ready-to-run designs. Each entry ships with a
`creature.json`, one or more tasks, and optional baseline score metadata.

```bash
uv run creature-lab zoo list
uv run creature-lab zoo run quadruped
uv run creature-lab report latest
```

## Packaged Creatures

| Creature | Default Task | Useful For | Common Failure To Inspect |
| --- | --- | --- | --- |
| `quadruped` | `crawl_forward` | First demo, locomotion, challenge pack | Contact balance, motor limits, sideways drift |
| `worm` | `crawl_forward` | Rollover challenge | Fast body wave with unstable final orientation |
| `tripod` | `crawl_forward` | Diagnosis challenge | Asymmetric support and tipping |
| `hexapod` | `crawl_forward` | More contacts and gait comparison | Single-limb drag or inefficient phases |
| `damaged_quadruped` | `recover` | Damage/recovery runs | Loss of contact after the damage event |
| `humanoid_minimal` | `balance` | Challenge: diagnose a footless biped | No feet and missing roll control |
| `humanoid_12dof` | `walk` | Slow, inspectable biped walking | Lateral drift and backend sensitivity |

## Challenge Pack

The repo now includes a small local challenge pack using existing simulator features:

- `crawl_forward`: move along +x.
- `low_friction_crawl`: move forward with low ground friction.
- `push_recovery`: stay useful after a lateral impulse.
- `reach_target`: reduce distance to a target sphere.
- `stability_hold`: avoid falling without forward-distance reward.
- `slope_climb` (quadruped): move along +x up a fixed incline (`terrain.type: slope`).
- `step_over` (quadruped): move along +x over a staircase (`terrain.type: steps`).
- `gap_cross` (quadruped): move along +x across periodic gaps, past a solid starting
  platform (`terrain.type: gaps`).

See [Task Spec](TASK_SPEC.md) for the full terrain field reference (`slope`, `steps`,
`gaps`, `rough`) — implemented as a shared, deterministic heightfield on both backends.

List exact creature/task availability with:

```bash
uv run creature-lab zoo list
```

## Showcase Contracts And Optimized Gaits

`quadruped`, `hexapod`, `tripod`, `worm`, and `humanoid_12dof` each ship a measured
`controller.json`. `zoo run` selects the `curated` controller by default: the packaged gait for
compatible joint IDs, posture feedback where the packaged gait is incompatible, and a safe
fallback otherwise.

```bash
uv run creature-lab zoo run quadruped
uv run creature-lab zoo run quadruped --controller sinusoid  # raw baseline
uv run creature-lab zoo run humanoid_12dof --task walk --controller optimized
uv run creature-lab zoo check-showcases
```

Measured improvement over the default sinusoid gait on `crawl_forward`: quadruped 0.57 → 1.97
(3.4x), hexapod 0.54 → 1.68 (3.1x), worm 0.93 → 1.51 (1.6x), tripod −0.68 → 0.94 (its default
gait actually scores worse than standing still; optimization fixes that outright). `zoo list`
marks which creatures have one and labels unstable entries as `challenge`. `check-showcases`
runs every promoted example against a minimum score and no-fall contract. Produce your own with
`creature-lab optimize` (see [CLI Reference](CLI_REFERENCE.md)). The 12-DOF humanoid's packaged
offset gait moves about **0.42 m forward in 5 s without falling** on PyBullet and remains upright
for a measured 30 s run. Its feet alternate contact, but the motion is intentionally described as
a slow stepping/shuffling baseline—not a polished dynamic walk. The same gait stays upright but
drifts slightly backward on MuJoCo, and longer PyBullet runs accumulate lateral drift because the
body has no roll-control joint. Those are tracked limitations, not hidden success claims (see
[Known Issues](KNOWN_ISSUES.md)). `humanoid_minimal` has no feet and remains a labeled challenge.

## Failure Zoo

The separate Failure Zoo packages intentionally broken body/controller/task combinations with
an expected causal category. Export one, inspect the JSON, run `autopsy`, and try a fix:

```bash
uv run creature-lab failure list
uv run creature-lab failure export frozen-gait --out outputs/frozen-gait
```

## Benchmarks

Run all zoo creatures that have a task:

```bash
uv run creature-lab bench --zoo --task crawl_forward --attempts 3 --seed 0 --out runs/bench.json
```

Benchmark output includes scores, best/mean score, backend, controller, seed, saved run paths,
and pass/fail status when a packaged baseline exists.

Every packaged creature/task pair has a calibrated PyBullet baseline
(`baselines/<task>.json`) **and** a MuJoCo baseline (`baselines/<task>.mujoco.json`).
`bench --backend mujoco --zoo` compares against the MuJoCo one automatically. The two
numbers are often very different for the same open-loop gait — that gap is expected (see
[Concepts](CONCEPTS.md) on portability) and is exactly what `sim2sim` measures directly.

## Gallery

Build static cards:

```bash
uv run creature-lab gallery build --zoo --out docs/assets/zoo --no-media
```

Build cards plus GIFs:

```bash
uv sync --extra sim --extra export
uv run creature-lab gallery build --zoo --out docs/assets/zoo --media
```
