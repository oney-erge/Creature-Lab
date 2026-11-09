# Contributing

Creature Lab is a tiny local lab for physical robot-creature design loops. Contributions should
strengthen that loop: JSON specs, runs, diagnostics, zoo examples, reports, benchmarks, and docs.

## Good First Contributions

- Add a zoo creature with `creature.json`, at least one task, and a short baseline note.
- Add a task that uses existing schema features: friction, target, damage, impulse, or rewards.
- Improve docs around specs, run artifacts, diagnostics, or examples.
- Add tests for CLI workflows and saved artifacts.

## Local Setup

Run the first-run path:

```bash
python scripts/start.py
```

For full development:

```bash
uv sync --inexact --all-extras
uv run creature-lab doctor
```

The browser app's front end lives in `web-ui/` and is built into the committed
`creature_lab/web/static/`. Change it only with Node installed, and commit the rebuilt bundle
(see [web-ui/README.md](web-ui/README.md)); CI fails when the bundle is stale.

## Before Opening A PR

Run:

```bash
uv sync --all-extras
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

Validate the zoo:

```bash
uv run creature-lab zoo validate-all
uv run creature-lab bench --zoo --task crawl_forward --attempts 1 --seed 0
```

## Adding A Zoo Creature

Create:

```text
creature_lab/zoo/<name>/
  creature.json
  tasks/<task>.json
  baselines/<task>.json   # optional, but useful
```

Keep creature names lowercase with underscores. Prefer simple, readable body graphs over large
specs that are hard to debug.

## Product Boundary

Do not add generic agent orchestration, personas, social simulation, cloud dashboards, or hosted
leaderboards to Creature Lab. Keep the project focused on local embodied design experiments.

Do not commit generated `runs/`, `outputs/`, local reports, GIFs, MP4s, or personal
`CLAUDE.local.md` notes.
