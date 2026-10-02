<p align="center">
  <img src="docs/assets/creature-lab-logo.svg" width="96" height="96" alt="Creature Lab logo" />
</p>

<h1 align="center">Creature Lab</h1>

<p align="center">
  <strong>A failure-first, local workbench for robot morphology experiments.</strong>
</p>

<p align="center">
  <a href="https://github.com/oney-erge/Creature-Lab/actions/workflows/ci.yml"><img src="https://github.com/oney-erge/Creature-Lab/actions/workflows/ci.yml/badge.svg" alt="CI status" /></a>
  <img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="Python 3.11+" />
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-blue" alt="Apache-2.0 license" /></a>
</p>

<p align="center">
  <img src="docs/assets/demo.gif" width="480" alt="Creature Lab demo: a blue quadruped robot walking on a checkered floor in simulation" />
</p>

Design a body, run it in physics, and find out whether a failure came from the body, controller,
task, fragility, or simulator — then hand someone the exact experiment that proves it. Everything
is inspectable JSON and runs offline on an ordinary laptop.

```text
Design → Run → Autopsy → Improve → Verify → Share
```

The distinctive unit is a **minimum reproducible robot experiment**: creature, task, controller,
trace, hashes, and runtime provenance in a verified pack. Creature Lab is an educational and
early-prototyping tool — not hardware qualification, a cloud service, or a GPU-scale RL platform.

## Start Here

```bash
git clone https://github.com/oney-erge/Creature-Lab.git
cd Creature-Lab
./run.sh            # Linux. macOS: ./run.command   Windows: .\run.bat
```

From a fresh checkout, the launcher installs the starter extras, checks the environment,
and opens the interactive **build editor** in your browser — configure a creature first, then
run it, instead of jumping straight into physics.

A terminal shows setup progress and an editor URL such as `http://localhost:8080`. Pick a
preset, tune it, click **Simulate** to run it through the physics pipeline and read its
score/diagnosis and a robustness sweep in the same panel, then **Save** to write a normal
`CreatureSpec` JSON (or `.urdf`). Try a different starting body with
`python scripts/start.py --creature humanoid`.

No browser handy? Once installed, a bare `creature-lab` with no arguments runs a built-in
creature through its measured gait and prints score + diagnosis straight to the terminal:

```bash
uv run creature-lab
```

If launch fails, start with `python scripts/start.py --dry-run` and `uv run creature-lab doctor`.

<details>
<summary>Launcher details</summary>

Use `.\run.ps1` from PowerShell. The launcher accepts `doctor`, `repair`, `docker`, `logs`, and
`stop`, and reuses a current locked environment on later runs. Docker binds the editor to
loopback and preserves runs and outputs in named volumes.

Setup checks disk space, prevents concurrent environment changes, and retries
temporary network failures up to three times. Failures are recorded in
`.setup/install.log`.

</details>

## Manual Quickstart

```bash
uv sync --frozen --extra sim --extra viz
uv run creature-lab build
```

For the plain looping playback demo instead of the setup screen: `uv run creature-lab demo
--open-browser` (add `--no-hold` to save a trace and exit after one pass).

## Next Steps

```bash
uv run creature-lab zoo list
uv run creature-lab zoo run quadruped
uv run creature-lab autopsy examples/quadruped.json --task examples/crawl_forward.json
uv run creature-lab evolve examples/quadruped.json --task examples/crawl_forward.json --attempts 20
```

`zoo run` uses the measured **curated** controller by default; `autopsy` explains *why* a run
scored the way it did and emits a reproducible pack; `evolve` searches for a better body/gait.
See [Getting Started](docs/GETTING_STARTED.md) for the full first-session walkthrough and
[CLI Reference](docs/CLI_REFERENCE.md) for every command.

## What You Get

- A curated Creature Zoo: quadruped, worm, hexapod, tripod, damaged quadruped, and humanoids.
- A browser build editor for presets, body sliders, part edits, motor tuning, validation,
  simulation, live metrics/diagnosis, a robustness sweep, and URDF import/export — all in one
  screen, with optional live file-sync to a project directory (`--project`).
- Portable JSON specs for creatures and tasks, and physics runs saved with exact
  creature/task/controller snapshots, hashes, scores, contacts, and warnings.
- **Experiment Autopsy**: controller counterfactuals, task-aware perturbation trials, optional
  backend comparison, cause attribution, and a recommended next experiment.
- A Failure Zoo of intentionally broken experiments for teaching and diagnostic regression.
- Local improvement loops: `evolve` for search and `ask --offline` for validated design edits.
- Replay, diagnosis, GIF/MP4 export, and advanced backend/export bridges.

## Core Workflow

```text
CreatureSpec + TaskSpec
  -> run a physics episode
  -> save an EpisodeTrace
  -> inspect or diagnose the result
  -> evolve or edit the creature
  -> replay/export the best run
```

> Every creature, task, and controller is JSON. Every episode is a trace. Every simulator is an
> adapter.

PyBullet is the default simulator. Specs, tasks, traces, and replays are portable; exact physics
behavior is backend-dependent.

## Docs

- [Documentation Home](docs/README.md) - where to start and how the docs fit together.
- [Getting Started](docs/GETTING_STARTED.md) - the shortest path from clone to first run.
- [Build Editor](docs/BUILD_EDITOR.md) - browser setup screen for creating CreatureSpec JSON.
- [Concepts](docs/CONCEPTS.md) - creatures, tasks, traces, backends, and the improve loop.
- [Creature Spec](docs/CREATURE_SPEC.md) and [Task Spec](docs/TASK_SPEC.md) - JSON authoring.
- [Run Artifacts](docs/RUN_ARTIFACTS.md) - what is saved under `runs/<run-id>/`.
- [Zoo](docs/ZOO.md) - bundled creatures, tasks, baselines, and challenge pack.
- [Failure Lab](docs/FAILURE_LAB.md) - hypothesis-driven lessons using intentional failures.
- [CLI Reference](docs/CLI_REFERENCE.md) - every command, grouped by workflow.
- [Known Issues](docs/KNOWN_ISSUES.md) - latent gaps and deliberate limitations found in review.
- [Changelog](CHANGELOG.md) - notable changes by release.
- [Grand Plan](docs/project/GRAND_PLAN.md) / [Roadmap](docs/project/ROADMAP.md) /
  [Releasing](docs/project/RELEASING.md) - maintainer-facing roadmap and release process.

## Advanced

A sample of what's available beyond the first run — full detail in
[CLI Reference](docs/CLI_REFERENCE.md):

| Need | Command |
| --- | --- |
| Diagnose why a run failed | `uv run creature-lab diagnose runs/<run-id>` |
| Optimize a creature's gait (2-3x typical) | `uv run creature-lab optimize creature.json --task task.json --out gait.json` |
| Combine success/robustness/portability into one pass-fail | `uv run creature-lab qualify creature.json --task task.json --profile basic-locomotion` |
| Check robustness / cross-backend gap | `uv run creature-lab robustness runs/<id> --trials 10` / `sim2sim runs/<id>` |
| Export a shareable, verified run | `uv run creature-lab export-pack latest --out outputs/my_pack` |
| Train a policy with reinforcement learning (PPO) | `uv sync --extra rl`, then `uv run creature-lab train creature.json --task task.json --out outputs/trained` |
| MuJoCo backend | `uv sync --extra mujoco`, then `uv run creature-lab run ... --backend mujoco` |
| URDF/MJCF bridge | `export-urdf`, `export-mjcf`, `import-urdf` |
| Gymnasium-style control | `creature_lab.rl.gym_env.CreatureGymEnv` (a real `gymnasium.Env`) |

Install everything with `uv sync --all-extras`.

## Testing

```bash
uv sync --all-extras
uv run ruff check .
uv run ruff format --check .
uv run pytest
uv run creature-lab zoo check-showcases
```

CI runs Ruff, Pytest, packaging, showcase acceptance, a real browser journey, and platform jobs
on Linux, Windows, and macOS. See [CONTRIBUTING.md](CONTRIBUTING.md) for the full pre-PR
checklist and [docs/project/RELEASING.md](docs/project/RELEASING.md) for the release process.

## Development Principle

Do not build a PyBullet project. Build a backend-agnostic creature lab where PyBullet is only
the first backend.
