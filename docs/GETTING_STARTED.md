# Getting Started

This guide is the shortest path from a fresh clone to a moving creature.

## 1. Launch The Build Editor

Use the launcher from the repository root:

```powershell
.\run.bat
```

```bash
./run.command  # macOS
./run.sh       # Linux
```

The first run installs what it needs; later runs reuse the current environment.
If setup fails, inspect `.setup/install.log` in the checkout.
PyBullet 3.2.7 has no Windows or macOS PyPI wheels. A first install there builds
the 80 MB source distribution and requires a working C++ compiler; it can take
several minutes. Linux x86-64 has a Python 3.11 wheel, while other Python and
platform combinations may also need a source build.
For direct control of the build editor after installation, use:

```bash
python scripts/start.py
```

The launcher installs the starter dependencies, runs `doctor`, and opens the interactive
**build editor** in your browser — a setup screen where you configure a creature before running
it, instead of jumping straight into physics.

What you should see:

- A terminal progress log with the editor URL.
- A browser tab at `http://localhost:8080` or the next free port.
- A quadruped preset in the 3D preview, with sliders to tune it, a template picker, part/motor
  editing, and a **Run simulation** button that runs the existing physics pipeline once you're happy
  with the setup.
- After Simulate: a **Metrics** panel (score, displacement, root-cause failure diagnosis) and a
  **Robustness** panel (re-simulate under seeded mass/friction perturbations) right there in the
  same tab — no separate CLI commands needed to see how the run went.

Pick a different starting preset:

```bash
python scripts/start.py --creature humanoid
```

For a fresh launch, choose **Humanoid**, keep **Move forward**, and click **Run first simulation**.
The default curated controller is the packaged 12-DOF walking gait. The replay starts when the run
finishes. **Back to design** restores the editable standing pose instead of leaving the scene
stuck on a replay frame.

Presets are `quadruped`, `hexapod`, `worm`, or `humanoid`. Add `--project outputs/mydude` (via
`uv run creature-lab build --project outputs/mydude`) to bind the editor to a directory whose
`creature.json`/`task.json` and `editor-state.json` autosave edits and detect external changes. See
[`docs/BUILD_EDITOR.md`](BUILD_EDITOR.md) for the full editor walkthrough.

## 2. Just Want The Old Playback Demo?

```bash
python scripts/start.py --mode demo
```

or manually:

```bash
uv sync --inexact --extra sim --extra viz
uv run creature-lab demo --open-browser
```

The `sim` extra installs PyBullet. The `viz` extra installs the browser viewer. The demo runs the
built-in quadruped on the built-in `crawl_forward` task with no setup step. Add `--no-hold` if
you want the command to save a trace and exit after one pass.

Use a different built-in creature:

```bash
python scripts/start.py --mode demo --creature worm
uv run creature-lab demo --creature worm --no-hold
uv run creature-lab demo --creature tripod --no-hold
```

## 3. Browse The Creature Zoo

```bash
uv run creature-lab zoo list
uv run creature-lab zoo run quadruped
uv run creature-lab report latest
uv run creature-lab zoo run worm
```

Zoo creatures are packaged with the library, so these commands work from an installed wheel.
Each saved run updates `runs/latest.txt`, which lets follow-up commands accept `latest`.
The Zoo selects its measured `curated` controller by default; add `--controller sinusoid` only
when you want the raw teaching baseline. Verify all promoted examples with:

```bash
uv run creature-lab zoo check-showcases
```

## 4. Find Out Why It Failed

Run a complete autopsy. It compares the selected controller with a curated counterfactual,
evaluates task-aware perturbations, and writes HTML/Markdown/JSON plus a verified pack:

```bash
uv run creature-lab autopsy examples/quadruped.json \
  --task examples/crawl_forward.json --controller sinusoid
uv run creature-lab verify-pack outputs/autopsy_<run-id>/experiment_pack
```

Learn from an intentionally broken experiment:

```bash
uv run creature-lab failure list
uv run creature-lab failure export frozen-gait --out outputs/frozen-gait
```

## 5. Improve One Creature

Reopen the build editor on a specific preset any time (this is what step 1 launches by default):

```bash
uv run creature-lab build --preset humanoid
```

Once you've saved a creature you like from the editor, improve it with the local evolution loop:

```bash
uv run creature-lab evolve examples/quadruped.json --task examples/crawl_forward.json --attempts 20
```

`evolve` evaluates candidate edits, keeps the best creature, and saves the best run plus its
lineage under `runs/`.

For a deterministic no-provider design loop:

```bash
uv run creature-lab ask "make it crawl farther" examples/tripod.json --task examples/crawl_forward.json --offline
```

## 6. Replay Or Export A Run

```bash
uv run creature-lab view runs/<run-id>
uv run creature-lab diagnose runs/<run-id>
uv run creature-lab report latest --out report.md
```

GIF/MP4 export needs the export extra:

```bash
uv sync --extra sim --extra export
uv run creature-lab export latest --gif creature.gif
```

## Troubleshooting

Run:

```bash
python scripts/start.py --dry-run
uv run creature-lab doctor
```

`--dry-run` prints the launcher commands without running them. `doctor` reports installed extras,
optional providers, and whether the built-in example can simulate.

Common fixes:

- Browser did not open: copy the printed `http://localhost:<port>` URL into your browser.
- Port is busy: rerun with `python scripts/start.py --port 8090`.
- Dependencies failed to install: run `uv sync --inexact --extra sim --extra viz` and retry.
- You only want a quick verification run: use `python scripts/start.py --once --no-open-browser`.
