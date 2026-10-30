<p align="center">
  <img src="https://raw.githubusercontent.com/oney-erge/Creature-Lab/main/docs/assets/creature-lab-logo.svg" width="96" height="96" alt="Creature Lab logo" />
</p>

<h1 align="center">Creature Lab</h1>

<p align="center"><strong>Build a robot, see why it fails, and compare what fixed it.</strong></p>

<p align="center">
  <a href="https://github.com/oney-erge/Creature-Lab/actions/workflows/ci.yml"><img src="https://github.com/oney-erge/Creature-Lab/actions/workflows/ci.yml/badge.svg" alt="CI status" /></a>
  <img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="Python 3.11+" />
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-blue" alt="Apache-2.0 license" /></a>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/oney-erge/Creature-Lab/main/docs/assets/demo.gif" width="480" alt="Creature Lab demo: a blue quadruped robot walking on a checkered floor in simulation" />
</p>

Creature Lab is a local workbench for designing modular robot bodies, running
them in physics, and finding out whether a result came from the body,
controller, task, fragility, or simulator. It saves the exact experiment so you
can inspect, replay, improve, and share it.

Try the [recorded quadruped replay](https://oney-physics-replays.hazycow18.chatgpt.site/creature-lab.html)
in your browser. [Experimental portable downloads](https://github.com/oney-erge/Creature-Lab/releases/tag/preview-0.2.0)
are available for Windows x64 and Linux x86-64 with PyBullet, and for macOS Intel
and Apple Silicon with MuJoCo. The macOS previews can behave differently and lack
PyBullet-only features; the Intel preview uses an older MuJoCo version. These
previews have not yet been tested on clean machines.
The previews contain the earlier release snapshot; use a current checkout for the latest
editor and analysis changes.

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
opens the browser-based build editor. Pick a preset, tune its body and motors,
click **Simulate**, then read the result. Use **Explain failure** to run a
counterfactual analysis, compare saved runs in History, and download its report
and experiment pack.

For a guided first investigation, open **Test → Failure lessons**, load **Frozen
gait**, simulate, change one motor's range in Motion, and simulate again. Compare
the saved runs in History; the outcome is an experiment, not a promised fix.

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
