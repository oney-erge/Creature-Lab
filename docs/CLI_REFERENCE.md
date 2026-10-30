# CLI Reference

Use `uv run creature-lab --help` for exact options. This page groups commands by workflow.

## Start Here

```bash
python scripts/start.py
uv run creature-lab demo --open-browser
uv run creature-lab build
uv run creature-lab zoo list
uv run creature-lab zoo run quadruped
uv run creature-lab zoo check-showcases
uv run creature-lab report latest
```

- `demo` runs a built-in creature in the live browser viewer.
- `build` opens the browser setup screen for visual creature editing and simulation.
- `zoo list` distinguishes measured showcases from intentionally difficult challenges.
- `zoo run <name>` uses the measured `curated` controller by default and saves its exact
  controller snapshot. Use `--controller sinusoid` for the raw teaching baseline.
- `zoo check-showcases` runs every promoted example against score and fall thresholds.
- `report latest` summarizes the last saved run.

## Launcher Scripts

The root launcher is the recommended first command from a repo checkout:

```powershell
.\run.bat
```

```bash
./run.command  # macOS
./run.sh       # Linux
```

Use `.\run.ps1` from PowerShell. The lower-level launcher below exposes
editor-specific options after the environment is installed:

```bash
python scripts/start.py
```

Useful options:

| Option | Purpose |
| --- | --- |
| `--once` | Run one pass, save the trace, and exit. |
| `--no-open-browser` | Print the viewer URL without opening a browser tab. |
| `--creature worm` | Run a different packaged demo creature. |
| `--creature-path path/to/creature.json` | Run a local CreatureSpec. |
| `--task path/to/task.json` | Override the default task. |
| `--port 8090` | Use a different Viser port. |
| `--full` | Install all optional extras before launching. |
| `--skip-sync` | Reuse the current environment. |
| `--dry-run` | Print commands without running them. |

## Run And Improve

```bash
uv run creature-lab build --preset humanoid
uv run creature-lab build mydude.json --out mydude.json
uv run creature-lab build --project outputs/mydude
uv run creature-lab run examples/quadruped.json --task examples/crawl_forward.json
uv run creature-lab run examples/quadruped.json --task examples/reach_target.json --controller target_seek
uv run creature-lab evolve examples/quadruped.json --task examples/crawl_forward.json --attempts 20
uv run creature-lab optimize examples/quadruped.json --task examples/crawl_forward.json --out gait.json
uv run creature-lab train examples/quadruped.json --task examples/crawl_forward.json --out outputs/trained
uv run creature-lab ask "make it crawl farther" examples/tripod.json --task examples/crawl_forward.json --offline
uv run creature-lab qualify examples/quadruped.json --task examples/reach_target.json --profile target-reach
uv run creature-lab autopsy examples/quadruped.json --task examples/crawl_forward.json --controller sinusoid
uv run creature-lab failure list
uv run creature-lab controller scaffold cpg --out gait.json
uv run creature-lab controller extract examples/quadruped.json --out gait.json
uv run creature-lab run examples/quadruped.json --task examples/crawl_forward.json --controller gait.json
```

- `build` edits a CreatureSpec (or URDF) in a Viser browser UI: tune it, drag task targets in
  3D, read live metrics, a
  robustness sweep, and a qualification pass/fail after Simulate, then save. `--project <dir>`
  binds it to `creature.json`/`task.json` in that directory, autosaving edits and detecting
  external changes with a Reload prompt (see `docs/BUILD_EDITOR.md`).
- `run` simulates one creature/task pair. `--controller` chooses `sinusoid` (default),
  `cpg` (coupled-oscillator gait), `target_seek` (steers the gait toward `task.target` —
  needs a task with one), `posture` (closed-loop PD balance — corrects forward/backward
  lean only, does not walk toward a goal; see Known Issues for why it can't correct
  sideways lean), or a path to a `controller.json` (a portable `ControllerSpec` — see
  `controller` below, or `train`'s output for a `policy`-type one); also available on
  `build`/`bench`/`robustness`/`sim2sim`/`qualify` — **not** `evolve`, see below. The editor
  also offers `curated`, which selects a measured packaged gait or safe feedback fallback.
- `evolve` searches for a better body/gait via `--mutate body,controller` (mutating the body's
  own `MotorSpec` amplitude/frequency/phase — unrelated to the `--controller` flag above; evolve
  always simulates with the default open-loop `sinusoid` policy, it has no `--controller` option).
  `--strategy tool_random` uses seeded random proposals through the validated agent tool layer
  instead of the structural body/controller mutators; it does not call a model. Each proposal
  is recorded in `lineage.json` (`creature-lab lineage <run>` shows it). The former `llm` name
  is a deprecated alias; the separate `ask` command can use a configured model.
- `optimize` tunes a creature's gait (CMA-ES over each motor's amplitude/frequency/phase, body
  untouched — the same search `evolve --strategy cmaes` runs) and saves the result as a portable
  `controller.json` instead of a new creature file. The un-tuned default gait leaves real
  performance on the table: a quadruped example went from score 0.24 to 0.70 (2.9x) in 80
  evaluations. Every zoo locomotion creature ships a pre-optimized `controller.json` — see
  `zoo run --controller optimized` below.
- `train` trains a real PPO policy (Stable-Baselines3 over `CreatureEnv`) and saves it as a
  `controller.json` + `policy.zip` bundle (`--controller <dir>/controller.json` runs it — a
  `policy`-type `ControllerSpec` always needs its sibling `policy.zip`, so move the whole
  directory together, not just the JSON). Needs the optional `rl` extra
  (`uv sync --extra rl` — gymnasium, Stable-Baselines3, torch). Policy payloads may contain
  pickle-based data, so load only policies you trust. New bundles record observation/action ABI
  and creature/task hashes and reject incompatible dimensions. Prints the trained policy's
  mean return against a random baseline on the same task, measured, not assumed — a 100k-timestep
  run on the quadruped example reaches 1.5-2x the random baseline in under 2 minutes. Scoped
  honestly: a working, measured training loop, not a promise of a polished walker — real bipedal
  walking is a research problem. The packaged 12-DOF humanoid is a separate hand-tuned,
  PyBullet-specific open-loop baseline; it is not evidence that PPO learned a humanoid gait.
- `ask` applies validated design edits, offline or with an optional LLM provider. Every
  proposal now sees the current diagnosis (failure patterns + suggestions) alongside the
  score, so an online LLM can target the actual detected problem instead of guessing blind.
- `qualify` combines a baseline run, a task-aware robustness sweep, and (for the `backend-portable`
  profile) a cross-backend comparison into one pass/fail result with a named primary blocker
  and a recommended next test. Built-in profiles: `basic-locomotion`, `target-reach`,
  `push-recovery`, `backend-portable`; `target-reach` and `push-recovery` fail fast with a
  clear "Task setup" check if the task doesn't have what the profile needs (a target, or a
  damage/impulse event) rather than running physics first. `--json` prints a machine-readable
  result. Also available as a **Qualify** panel in `creature-lab build`'s Test phase (see
  `docs/BUILD_EDITOR.md`).
- `autopsy` runs the selected-controller baseline, a distinct curated-controller counterfactual
  when available, task-aware perturbations, and optional backend comparison. It emits
  HTML/Markdown/JSON plus verified packs for the baseline, reference, and perturbation runs.
  Task/profile mismatches are rejected before simulation. Two failed controllers leave the
  cause undetermined; pack verification establishes artifact integrity, not causation.
  The JSON records each trial's seed, mass and friction scales, score, and outcome. Identical
  or indistinguishable controller references are skipped and cannot support an attribution.
- `failure list` and `failure export <id>` expose intentionally broken experiments with an
  expected diagnosis for teaching and regression work.
- `controller scaffold <cpg|target_seek|posture>` writes a starter `controller.json` with that
  controller's own built-in defaults. `controller extract <creature.json>` migrates a
  creature's own gait (`MotorSpec` amplitude/frequency/phase/offset) into an explicit, portable
  sinusoid `controller.json` — the same thing `--controller sinusoid` already does implicitly,
  now a shareable file. `controller validate <controller.json> --creature <creature.json>
  [--task <task.json>]` checks a controller.json against a specific creature/task (for a
  sinusoid spec, warns if none of its joint ids match the creature's motors — such a spec would
  silently drive nothing). Any `controller.json` can then be passed to `--controller` above.

## Replay And Debug

```bash
uv run creature-lab replay runs/<run-id>
uv run creature-lab inspect runs/<run-id>
uv run creature-lab diagnose runs/<run-id>
uv run creature-lab report latest --out report.md
uv run creature-lab report latest --html report.html
uv run creature-lab view runs/<run-id> --open-browser
uv run creature-lab export latest --gif creature.gif
uv run creature-lab export-pack latest --out outputs/my_design_pack
uv run creature-lab verify-pack outputs/my_design_pack
```

- `replay` prints a short trace summary.
- `inspect` prints metadata, hashes, score components, contacts, warnings, and run metrics
  (including which controller produced the run, if known).
- `diagnose` explains likely failure patterns and suggested edits.
- `report` writes a Markdown or JSON summary with score, diagnostics, artifacts, and a
  reproducibility block. `--html` also writes a self-contained HTML run card (score
  breakdown, signal sparklines, root-path plot, and an optional embedded GIF preview).
- `view` replays recorded poses in the browser viewer.
- `export` renders a recorded trace to GIF or MP4.
- `export-pack` bundles a run into one portable, shareable directory: `creature.json`,
  `task.json` (if any), `controller.json`, `trace.json`, and a `manifest.json` with
  reproducibility hashes — no dependency on `runs/` or anything else on the machine that
  produced it. Current runs snapshot the exact controller when they are saved; learned-policy
  packs copy the model payload as well. Older runs fall back with an explicit warning rather
  than claiming exact reproduction. `verify-pack` checks all byte/semantic hashes, schemas,
  bundle-contained paths, and policy presence before use. Defaults to `outputs/<run_id>_pack`
  when `--out` is omitted. `--json` prints the manifest.

Most run-reading commands accept either `runs/<run-id>`, a `trace.json` path, a bare run id
under `runs/`, or `latest`.

## Advanced

```bash
uv run creature-lab scaffold quadruped --out quad.json
uv run creature-lab scaffold humanoid --out humanoid.json  # footed 12-DOF default
uv run creature-lab scaffold humanoid --dof 8 --out footless-challenge.json
uv run creature-lab mirror-limb half_creature.json --side left --out symmetric.json
uv run creature-lab export-urdf quad.json --out quad.urdf
uv run creature-lab export-mjcf quad.json --out quad.xml
uv run creature-lab import-urdf robot.urdf --out robot.json
uv run creature-lab compare runs/<a> runs/<b>
uv run creature-lab compare runs/<a> runs/<b> --html diff.html
uv run creature-lab plot runs/<run-id> --metric joint_energy --out energy.png
uv run creature-lab bench --zoo --task crawl_forward --attempts 3 --out runs/bench.json
uv run creature-lab schema creature --out docs/schemas/creature.schema.json
uv run creature-lab gallery build --zoo --out docs/assets/zoo --no-media
uv run creature-lab lineage runs/<evolve-run-id>
uv run creature-lab archive show runs/<map-elites-run-id> --html archive.html
uv run creature-lab archive export runs/<map-elites-run-id> --cell 3,2 --out elite.json
uv run creature-lab robustness runs/<run-id> --trials 10
uv run creature-lab sim2sim runs/<run-id>
uv run creature-lab doctor
uv run creature-lab version
```

These commands are useful for authoring, interoperability, run comparison, diagnostics, and
environment checks. They are intentionally outside the first-run path.

- `archive show` (only useful after `evolve --strategy map_elites`) prints the filled
  behaviour cells as a table, or `--html` renders a scored heatmap; add `--task` to embed a
  replay GIF per cell. `archive export --cell row,col` pulls one elite out as a standalone,
  editable `CreatureSpec` JSON.
- `robustness` re-simulates a creature/task under small seeded mass/friction perturbations
  and reports the score mean/std/fail-rate — a wide spread means the gait only works for the
  exact recorded parameters. Add `--save` to write a reportable run (`report <dir>` then
  shows a Robustness section). The same engine is available as a **Robustness** panel inside
  `creature-lab build` (see `docs/BUILD_EDITOR.md`), run directly against the in-editor
  creature without saving a run first.
- `sim2sim` runs the same creature/task on both PyBullet and MuJoCo and reports the score gap
  and mean root-position divergence — a concrete measure of the "specs are portable, physics
  is backend-dependent" contract. Add `--save` for a reportable run.

## Machine-Readable Output

Use `--json` on `run`, `evolve`, `optimize`, `train`, `ask`, `inspect`, `diagnose`, `report`,
`zoo list`, `zoo run`, `robustness`, `sim2sim`, `qualify`, and `export-pack` when another tool
needs structured output instead of Rich tables.

## Optional Extras

| Extra | Enables |
| --- | --- |
| `sim` | PyBullet backend and physics rendering |
| `viz` | Viser browser viewer and plotting |
| `export` | GIF/MP4 writing |
| `evolve` | `evolve --strategy cmaes` and `optimize` (both CMA-ES-based) |
| `rl` | `train` (PPO over `CreatureEnv` via Stable-Baselines3) and loading a trained `policy` controller |
| `mujoco` | MuJoCo backend and MJCF loading tests |
| `llm` | Online `ask` mode through LiteLLM |
