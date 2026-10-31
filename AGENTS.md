# AGENTS.md

## Project Overview

Creature Lab is a local, Python-first lab for designing, running, diagnosing, and improving
modular robot creatures from JSON.

The durable contracts are:

- Every creature is a `CreatureSpec` JSON document.
- Every task is a `TaskSpec` JSON document.
- Every episode is an `EpisodeTrace` saved under `runs/`.
- Every movement policy can be described as a `ControllerSpec` JSON document (optional; a run
  defaults to the built-in `sinusoid` gait when none is given).
- Every simulator is an adapter behind the same creature/task/trace/controller contracts.

PyBullet is the default simulator, but it must remain isolated as one backend rather than the
shape of the whole project.

## Start Commands

Use the launcher from a checkout:

```powershell
.\run.bat
```

```bash
./run.command  # macOS
./run.sh       # Linux
```

Use `python scripts/start.py` for editor-specific development options after
the root launcher has prepared the environment.

Manual first run:

```bash
uv sync --inexact --extra sim --extra viz
uv run creature-lab demo --open-browser
```

Full development environment:

```bash
uv sync --inexact --all-extras
```

## Checks

Run relevant checks before finishing code changes:

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

For documentation or agent-guidance-only changes, verify referenced paths and run
`git diff --check`; application tests are not required.

For CLI or packaging changes, also run:

```bash
uv run creature-lab doctor
uv run creature-lab validate examples/tripod.json --task examples/crawl_forward.json
```

## Architecture Boundaries

- `creature_lab/schema/` contains data models and must not import physics engines.
- `creature_lab/backends/` contains simulator adapters.
- `creature_lab/viewers/` consumes frame and trace data.
- `creature_lab/editor/` contains build-editor session logic and Viser controls; keep
  `session.py` pure and testable without GUI or physics imports.
- `creature_lab/agents/` uses validated tools and must not access backend internals directly.
- `creature_lab/zoo/` contains packaged creatures, tasks, and baselines.
- `creature_lab/robots/` runs published robots with their trained policies (optional
  `robots` extra). It is separate from the `CreatureSpec` contracts, downloads robot files
  on demand against pinned hashes, and must never bundle files under a license stricter than
  Apache-2.0 (Microduck's meshes are CC BY-NC-SA). `actuator.py`, `analysis.py`, `types.py`,
  `report.py` and `catalog.py` are numpy-only; MuJoCo stays in `rollout.py`, `render.py` and
  the per-robot modules.
- `docs/` explains user workflows, architecture, and roadmap.
- `scripts/` contains repo automation that should run before package dependencies are installed.

## Code Style

- Target Python 3.11+.
- Use Typer for CLI commands and Rich for human-readable terminal output.
- Use Pydantic v2 models for structured JSON data.
- Prefer small, explicit modules over broad abstractions.
- Preserve backend-agnostic behavior unless a command is explicitly backend-specific.
- Do not add dependencies without a clear reason and matching docs.
- Do not add Unity, Godot, Isaac, ROS, CUDA, databases, web frameworks, hosted dashboards, or
  generic agent orchestration for the MVP unless explicitly requested.

## Testing Guidance

- Add tests for meaningful code changes.
- Keep optional integrations behind extras and use `pytest.importorskip` where appropriate.
- Do not require network access, API keys, GUI interaction, or provider credentials for the
  default test suite.
- When changing saved artifacts, update tests and docs together.

## Documentation Guidance

- Keep the first-run path short: launcher first, direct `uv` commands second.
- Document public CLI behavior in `README.md`, `docs/GETTING_STARTED.md`, and
  `docs/CLI_REFERENCE.md` when commands change.
- Document editor behavior in `docs/BUILD_EDITOR.md` when build-mode controls change.
- Keep advanced backend/export details out of the first-run path unless they are required.
- Treat this file as living project guidance; keep it specific and concise.

## Local State And Safety

- Do not commit generated `runs/`, `outputs/`, local reports, GIFs, MP4s, `.venv/`, or
  `CLAUDE.local.md`.
- Treat user-provided JSON as untrusted input and validate before simulation.
- Do not print or commit LLM provider keys or other secrets.

## Git and Handoff

- Preserve unrelated changes and keep commits focused.
- Use the configured repository-owner identity.
- Do not add assistant names, co-author trailers, session links, or tool
  attribution to Git artifacts.
- Report what changed, what was verified, what was skipped, and remaining risks.


## Install and run contract

- Keep `run.bat`, `run.ps1`, `run.command`, and `run.sh` as the stable
  user entry points. They must keep the same `run`, `doctor`, `repair`,
  `docker`, `logs`, and `stop` actions where the application supports them.
- Use the `native-app-delivery` Codex skill when changing first-run setup,
  repair, Docker, or launcher behavior. That is an internal workflow name and
  must not appear in product copy or the public README.
- Keep shared install mechanics in `scripts/install-utils.ps1` and
  `scripts/install-utils.sh`. Preserve idempotent reruns, bounded transient
  retries, install locking, disk checks, user state, and `.setup/install.log`.
- Verify launcher changes with PowerShell parsing, `bash -n`, the focused
  delivery audit, and `docker compose config`. Do not run the full application
  test suite unless the change affects application behavior.
