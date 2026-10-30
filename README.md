<p align="center">
  <img src="https://raw.githubusercontent.com/oney-erge/Creature-Lab/main/docs/assets/creature-lab-logo.svg" width="96" height="96" alt="Creature Lab logo" />
</p>

<h1 align="center">Creature Lab</h1>

<p align="center"><strong>Build a robot, investigate a failure, and compare changes.</strong></p>

<p align="center">
  <a href="https://github.com/oney-erge/Creature-Lab/actions/workflows/ci.yml"><img src="https://github.com/oney-erge/Creature-Lab/actions/workflows/ci.yml/badge.svg" alt="CI status" /></a>
  <img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="Python 3.11+" />
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-blue" alt="Apache-2.0 license" /></a>
</p>

<p align="center">
  <img src="docs/assets/showcase.webp" width="720" alt="Side-by-side recorded comparisons of Duckling and a humanoid before and after a gait change" />
</p>

Creature Lab is a local workbench for designing modular robot bodies and exploring
how the body, controller, task, and simulator affect their behavior. It saves the
experiment so you can inspect, replay, improve, and share the evidence.

Try the [recorded quadruped replay](https://oney-physics-replays.hazycow18.chatgpt.site/creature-lab.html)
in your browser. An [experimental Windows x64 preview](https://github.com/oney-erge/Creature-Lab/releases/tag/preview-windows-2026-10-30)
contains an earlier editor snapshot and uses PyBullet. [Older previews](https://github.com/oney-erge/Creature-Lab/releases/tag/preview-0.2.0)
are available for Linux with PyBullet and macOS with MuJoCo. The macOS previews
can behave differently and lack PyBullet-only features; Intel uses an older MuJoCo
version. These archives are unsigned and have not been run on clean machines.

```text
Design -> simulate -> diagnose -> improve -> verify -> share
```

It is designed for education and early prototyping, not hardware qualification,
a cloud service, or large-scale GPU reinforcement learning.

## Quick start

```bash
git clone https://github.com/oney-erge/Creature-Lab.git
cd Creature-Lab
./run.sh            # Linux; macOS: ./run.command
```

On Windows, use `.\run.bat`. The launcher sets up the starter environment and
opens the browser-based build editor. Pick a creature and goal, then click
**Run first simulation**. Watch the replay, inspect the result, and use **Back to
design** to make a change. Use **Explain failure** to run a
counterfactual analysis, compare saved runs in History, and download its report
and experiment pack.

For a guided investigation, open **Results → Guided experiment**, choose **Humanoid**
or **Duckling**, and run the no-swing baseline. Select **Try walking gait and run again**,
then **Compare with baseline** to see both recorded runs together. Duckling's gait is an
experimental, PyBullet-tuned starting point; changes and other backends can behave differently.

The animation above comes from saved simulation traces. To create your own GIFs,
MP4s and offline comparison reports after setup:

```bash
uv sync --inexact --extra sim --extra viz --extra export
uv run python scripts/create_showcase.py
```

The output path and measured results are printed when recording finishes.

PyBullet's current PyPI release has no Windows or macOS wheels. On those
platforms its first installation builds from source and requires a working C++
toolchain; it may take several minutes. Linux x86-64 has a Python 3.11 wheel.
See [Getting Started](docs/GETTING_STARTED.md) for setup and troubleshooting.

Each run produces ordinary JSON: a creature, task, controller, trace, hashes,
and runtime provenance. That is the project's central unit: a minimum
reproducible robot experiment.

No browser? After setup, run the built-in demo from a terminal:

```bash
uv run creature-lab
```

If launch fails, try `python scripts/start.py --dry-run` and
`uv run creature-lab doctor`.

The launchers also accept `doctor`, `repair`, `docker`, `logs`, and `stop`.
Docker binds the editor to localhost and keeps runs and outputs in named volumes.

## Next steps

```bash
uv run creature-lab zoo list
uv run creature-lab zoo run quadruped
uv run creature-lab autopsy examples/quadruped.json --task examples/crawl_forward.json
uv run creature-lab evolve examples/quadruped.json --task examples/crawl_forward.json --attempts 20
```

- `zoo run` runs a curated creature and controller.
- `autopsy` proposes an explanation and writes the recorded evidence in verified packs.
- `evolve` searches for a better body and gait.

The [Getting Started guide](docs/GETTING_STARTED.md) walks through a complete
first session. Try the [two-gait lesson](docs/GAIT_LESSON.md) to compare two
saved quadruped runs. The [CLI reference](docs/CLI_REFERENCE.md) covers every
command.

## What it includes

- A Creature Zoo with working and deliberately broken examples.
- A browser editor for presets, parts, motors, validation, simulation, and
  URDF import/export.
- Physics traces, replay, diagnosis, robustness tests, and GIF/MP4 export.
- Local improvement tools for search and validated design edits.
- Portable JSON contracts for creatures, tasks, controllers, and traces.

PyBullet is the default simulator. The JSON specifications and saved traces are
portable, but exact physics behavior can differ by backend.

## Documentation

| Guide | Use it for |
|---|---|
| [Getting Started](docs/GETTING_STARTED.md) | A complete first experiment |
| [Build Editor](docs/BUILD_EDITOR.md) | Creating and editing creatures in the browser |
| [Concepts](docs/CONCEPTS.md) | Creatures, tasks, traces, simulators, and improvement |
| [Zoo](docs/ZOO.md) | Bundled creatures, tasks, and challenge packs |
| [Failure Lab](docs/FAILURE_LAB.md) | Intentional failures and diagnostic lessons |
| [CLI reference](docs/CLI_REFERENCE.md) | Advanced commands and exports |
| [Known issues](docs/KNOWN_ISSUES.md) | Current limitations |
| [Documentation home](docs/README.md) | JSON schemas, run artifacts, and advanced guides |
| [Contributing](CONTRIBUTING.md) | Development and verification |

Apache-2.0. Built by [Oney Erge](https://oneyerge.com).
