<p align="center">
  <img src="https://raw.githubusercontent.com/oney-erge/Creature-Lab/main/docs/assets/creature-lab-logo.svg" width="96" height="96" alt="Creature Lab logo" />
</p>

<h1 align="center">Creature Lab</h1>

<p align="center"><strong>Shove a real robot, see exactly why it fell, and prove the fix.</strong></p>

<p align="center">
  <a href="https://github.com/oney-erge/Creature-Lab/actions/workflows/ci.yml"><img src="https://github.com/oney-erge/Creature-Lab/actions/workflows/ci.yml/badge.svg" alt="CI status" /></a>
  <img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="Python 3.11+" />
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-blue" alt="Apache-2.0 license" /></a>
</p>

<p align="center">
  <img src="docs/assets/checkup-microduck.webp" width="800" alt="Two simulated Microduck robots take the same 3 N sideways shove. The one with the walk-only policy stays on the floor; the one with the newer walk-and-get-up policy falls and stands back up." />
</p>

<p align="center"><sub>The same shove, the same instant, two policies for the same robot (simulation). Microduck model by Pollen Robotics, CC BY-NC-SA 4.0.</sub></p>

Creature Lab is a local workbench for robot experiments. Run a published robot with its real
trained policy, shove it, make the floor slippery, and get an explanation of every fall backed
by the recorded evidence. Or design your own modular robot, then explore how its body,
controller, task, and simulator affect its behavior. Every experiment is saved so you can
inspect, replay, improve, and share it.

## Browser app

<p align="center">
  <img src="docs/assets/app-microduck.webp" width="800" alt="The Creature Lab browser app: a Microduck robot on the floor in slow motion after a shove, the run history on the left, and the explanation of the fall and the shove results on the right." />
</p>

<p align="center"><sub>Simulation. Microduck model by Pollen Robotics, CC BY-NC-SA 4.0.</sub></p>

```bash
./run.sh            # Linux; macOS: ./run.command; Windows: .\run.bat
```

The launcher opens the app. Choose Microduck or the Unitree G1, watch a saved shove in 3D (slowed
down at the shove and the fall), read why the robot fell, switch between its policies, or press
**Run check-up** to run a fresh one. Robots are downloaded after you accept their license. See
[Browser app](docs/WEB_APP.md).

## Robot check-up from the command line

```bash
uv sync --inexact --extra robots
uv run creature-lab robots checkup microduck      # or: unitree-g1
```

It downloads the robot after showing you its license, runs about fifty simulated walks on the
CPU, and writes an HTML report (add `--film` for a 1080p film). On the Microduck, the older
walk-only policy is left on the floor by most shoves from 2 N up. Pollen's newer policy falls a
little more often but always gets back up. On a very slippery floor, neither does, and the
report says that no policy swap fixes that. See [Robot check-up](docs/ROBOT_CHECKUP.md) for the
tests, how falls are explained, licenses, and limits. It is a simulation, not the hardware.

<p align="center">
  <img src="docs/assets/checkup-unitree-g1.webp" width="640" alt="A simulated Unitree G1 humanoid walking with Unitree's own policy takes a 100 N sideways shove and falls, shown in slow motion." />
</p>

Watch the films: [Microduck check-up (1 min)](docs/assets/checkup-microduck.mp4) and
[Unitree G1 check-up (35 s)](docs/assets/checkup-unitree-g1.mp4). GIF versions of both loops are in
[docs/assets](docs/assets/MEDIA_LICENSES.md). In the build editor, both robots are the first
choices in the creature picker too.

Try the [recorded quadruped replay](https://oney-physics-replays.hazycow18.chatgpt.site/creature-lab.html)
in your browser. An [experimental Windows x64 preview](https://github.com/oney-erge/Creature-Lab/releases/tag/preview-windows-2026-10-30)
contains the latest editor changes and uses PyBullet. [Older previews](https://github.com/oney-erge/Creature-Lab/releases/tag/preview-0.2.0)
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

On Windows, use `.\run.bat`. The launcher sets up the environment and opens the
[browser app](docs/WEB_APP.md). To design your own creature instead, press **Build your own**
there, or start the build editor directly with `python scripts/start.py --creature quadruped`.
In the build editor, pick a creature and goal, then click **Run first simulation**. Watch the
replay, inspect the result, and use **Back to design** to make a change. Use **Explain failure** to run a
counterfactual analysis, compare saved runs in History, and download its report
and experiment pack.

For a guided first investigation, open **Results → Failure lessons**, load **Frozen
gait**, simulate, change one motor's range in Movement, and simulate again. Compare
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

- A browser app for published robots (Microduck, Unitree G1): 3D replays, shoves, slippery
  floors, weak batteries, explained falls, an HTML report and a film.
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
| [Browser app](docs/WEB_APP.md) | The app that opens first: robots, replays, check-ups |
| [Robot check-up](docs/ROBOT_CHECKUP.md) | Shoving real robots and explaining their falls |
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
