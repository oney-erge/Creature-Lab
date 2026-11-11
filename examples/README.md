# Examples

These JSON files are small, editable starting points for local experiments.

Start the packaged demo first:

```bash
python scripts/start.py
```

| File | Type | Run |
| --- | --- | --- |
| `quadruped.json` | CreatureSpec | `uv run creature-lab run examples/quadruped.json --task examples/crawl_forward.json` |
| `tripod.json` | CreatureSpec | `uv run creature-lab run examples/tripod.json --task examples/crawl_forward.json` |
| `worm.json` | CreatureSpec | `uv run creature-lab run examples/worm.json --task examples/crawl_forward.json` |
| `crawl_forward.json` | TaskSpec | Used by locomotion examples |
| `reach_target.json` | TaskSpec | `uv run creature-lab run examples/quadruped.json --task examples/reach_target.json` |
| `recover_after_damage.json` | TaskSpec | Use with a creature that contains the referenced damaged part |
| `robot-pack/` | Robot pack | `uv run creature-lab robots validate examples/robot-pack` (see [Bring your own robot](../docs/ROBOT_PACKS.md)) |

Validate before running:

```bash
uv run creature-lab validate examples/quadruped.json --task examples/crawl_forward.json
```

After a run:

```bash
uv run creature-lab report latest
uv run creature-lab diagnose latest
```

Use the launcher with example files:

```bash
python scripts/start.py --creature-path examples/quadruped.json --task examples/crawl_forward.json
```

For a quick non-interactive check:

```bash
python scripts/start.py --creature-path examples/quadruped.json --task examples/crawl_forward.json --once --no-open-browser
```
