# Changelog

## Unreleased

- **Bring your own robot and policy.** A robot pack is a folder with a `robot.toml`, a MuJoCo model
  and a trained policy (`.onnx`, or the `.npz` LSTM form of Unitree's G1 policy). `robots validate`
  checks it and says each mistake in plain words (observation length against the policy's input,
  missing joints, a ground plane in the model, a missing torque limit, and more) and walks the
  robot for two seconds; `robots add` and `robots remove` keep a list of added folders; every
  check-up command and the app then treat it like Microduck or the G1, with shoves and loads scaled
  from `mass_kg`. Observation terms, PD or position-servo joints, and named sensors are declared in
  the file ([docs/ROBOT_PACKS.md](docs/ROBOT_PACKS.md), example in `examples/robot-pack/`). The
  Unitree G1 written as a pack runs bit for bit like the built-in adapter. Per-robot staging and
  test levels moved from tables in `render.py` and `checkup.py` onto `RobotInfo`.
- **`robots init FOLDER` drafts `robot.toml`** from a MuJoCo model and its policies: the trunk, mass,
  height, physics step, actuator kind and sensors from the model, and the joint order, gains,
  default pose, action scales and observation layout from an ONNX policy's metadata (mjlab and
  Pollen Robotics write it). Whatever only a person knows is left as `TODO`, and `robots validate`
  warns until it is filled in. A joint can now have its own `action_scale`.
- **Add a robot in the app.** Under the robot cards, **Add your own robot** takes a folder, checks
  it (`POST /api/robots/validate`), shows each problem in plain words and adds it (`/api/robots/add`);
  an added robot has a **Your robot** badge and **Remove from the list**
  (`DELETE /api/robots/{key}`, which never touches its files). The 3D view now draws robots built
  from boxes, capsules, cylinders, spheres and ellipsoids when the model has no meshes, and sizes
  the shove arrow from the robot's own test levels.

## 0.3.0 (2026-11-10)

- **Published on PyPI** as `creature-lab`: `pip install "creature-lab[app]"`, then `creature-lab`.
  Releases are built, tested and published by `release.yml` when a GitHub release is published
  (PyPI trusted publishing; no token in the repository).
- In a side-by-side "what if" view, each panel and timeline line now says which run it is
  ("Original: 150 N shove", "What if: gentler than the 150 N original"). Both used to show the same
  policy name, so the two could not be told apart.
- README rewritten shorter, around a new screen recording of the app (`docs/assets/creature-lab-demo.gif`)
  and a 1-minute tour video. `scripts/media/record_app.py` and `compose_app.py` re-record them from
  the real app (CDP screencast in headless Edge, captions from the runs on screen).
- **A first launch needs no compiler.** The launchers (`run.ps1`, `run.sh`, `scripts/start.py`)
  install only prebuilt packages (`viz`, `web`, `robots`) and keep extras added by hand
  (`--inexact`). PyBullet, which is built from source on Windows and macOS and cost a clean Windows
  start about three minutes (or a failure on a long folder path), is now optional: the classic
  editor and the new `creature-lab quick` fall back to MuJoCo and say so, `doctor` reports it as
  optional, and the error for a missing PyBullet names `--backend mujoco` and the compiler caveat.
  A cold start from an empty cache measured about 16 s on a fast connection.
- **Fix: `./run.sh` stopped after the install on macOS.** macOS ships Bash 3.2, where expanding an
  empty array under `set -u` aborts ("forward[@]: unbound variable"), so a plain `./run.sh` or
  `./run.command` with no extra arguments never started the app. Found by the new first-launch CI
  job, which also showed that a Mac whose newest Python is 3.15 cannot install onnxruntime: the
  launchers now ask uv for Python 3.12 on a first install (an existing environment is kept).
- When an install does fail, the launcher says what to do for the usual causes (a path too long for
  Windows, no C++ build tools, a full disk, no network) instead of leaving raw build errors.
- A bare `creature-lab` now opens the browser app (or says how to install it). The old terminal
  demo is `creature-lab quick`. New `app` extra for pip installs: `pip install "creature-lab[app]"`.
- **The first run is one click.** The app opens on the robot whose first check-up is quickest (the
  G1, about 45 s from nothing), shows a bundled looping clip of its shove before anything is
  downloaded, says how long the first run takes, and **Download and check up** goes straight from
  the license to the results. Measured from an empty package cache with the real Windows launcher:
  about 50 s from the click to a moving, explained robot.
- **"What if…" in the app.** Under any run, one click changes one thing (the shove from the other
  side, harder or gentler, a very slippery floor, half speed or faster, a load on the G1, a weak
  battery on the Microduck), runs it again in a second or two, and opens it beside the original
  with a sentence saying what the change did. A one-policy robot such as the G1 now has a "does
  this change the ending?" story too. `POST /api/runs/{id}/whatif` takes a name from a fixed menu,
  never numbers; the run is saved under the check-up and a repeat reuses it.
- `robots compare BEFORE AFTER` (with `--fail-on-regression`, `--json`, `--markdown`) says which
  tests of a saved check-up got better or worse, for CI and pull-request comments, and
  `robots card` writes an SVG robustness card plus a one-line claim for a README or model card.
- README leads with the one-command start and the same shove on two policies; stale preview-build
  links are gone.

- Add the robot check-up (`creature-lab robots ...`, `robots` extra): run Pollen Robotics'
  Microduck and the Unitree G1 with their published policies in CPU MuJoCo, shove them at eight
  points of the stride, vary grip, battery and load, and explain each fall from the recorded
  evidence. Writes an HTML report and an optional 1080p film. Robot files are downloaded on
  demand against pinned SHA-256 hashes; Microduck's CC BY-NC-SA meshes are never bundled.
- Revert the toy duckling, its PyBullet "showcase" renderer and guided experiment; the check-up
  replaces them. The editor opens on the quadruped again.
- The build editor gets a **Real robots** panel: show Microduck or the G1 in the 3D view from their
  meshes, replay saved check-up runs with a follow camera, and run a check-up in the background.
- `build`, `demo`, `replay` and `compare` now serve on the first free port from the one requested
  and say so. Viser used to move on silently, so the CLI opened the requested port, which an older
  editor often still held.
- Add a **browser app** (`creature-lab app`, `web` and `robots` extras) and make it what the
  launcher opens: pick Microduck or the G1, watch saved shoves in 3D from the real meshes with
  slow motion at the shove and the fall, see the feet's support area and the shove drawn in the
  scene, switch policies, and start a check-up or a download (after the license) from the page.
  FastAPI server in `creature_lab/web/`, React and three.js front end in `web-ui/`, built into
  the committed `creature_lab/web/static/`. `scripts/start.py` defaults to `--mode app` and
  installs the app's extras itself; `--creature`, `--creature-path` or `--task` still open the
  build editor.
- Browser app polish from a full click-through: on wide screens the library, 3D view and results
  each scroll on their own, so picking a run never scrolls the robot away; a downloaded robot is
  shown in the invitation; a download or check-up still running after a page reload is picked up
  again (`GET /api/jobs`); the report opens with its film (served under `/report/`); the history
  is one keyboard stop (arrow keys, plus a skip link); an unreachable server offers **Try again**;
  and the 3D view draws only when something changed.
- Browser app, second pass: the support area is a filled teal (or red) floor patch with a legend,
  the weight point has a plumb line, and both policies can be shown side by side on one clock
  and one timeline with a **Can it be fixed?** panel; the history can be filtered; every view has
  an address and the back button works; **Save a clip** records the run as a WebM with the credit
  line; **Build your own** is now a designer inside the app (sliders, 3D preview, run, result)
  with the classic editor one click away; the 3D view simplifies itself without a GPU and
  respects reduced motion; a finished check-up no longer moves you off the run you are watching.
- Fix the Microduck's support area: MuJoCo reports a mesh foot touching at a few points
  millimetres apart, so the outline was a point. It is now the sole of the foot (the part within
  6 mm of the floor), which makes "balance point vs feet" margins a little more accurate. The
  headline results are unchanged (34 of 48 shoves leave the walk-only policy on the floor, 0 of 48
  for the get-up policy). A walk that went nowhere after a shove reads "Stayed up, barely moved"
  instead of "Walked -0.2 m".
- The Docker image now serves the browser app (with the `web` and `robots` extras and a volume for
  downloaded robots); `creature-lab app` honours `CREATURE_LAB_HOST` like `build` and `demo`.
- `build --preset NAME` (and **Build your own** in the app) opens the editor on that creature;
  it used to open on the Microduck whenever the robot was downloaded. `doctor` now reports
  whether the browser app's extras are installed.
- Update five editor tests that still described behavior changed on purpose earlier (the quadruped
  runs a packaged gait, controller choice is undoable, replay requires the same design) and add
  tests for the replay refusal.

## 0.2.0 (preview, 2026-10-29)

- Skip indistinguishable controller counterfactuals, preserve reference and perturbation
  recordings in verified evidence packs, and report individual trial conditions.
- Align side-by-side 3D playback by recorded time and render each task's own terrain and target.

All notable changes to Creature Lab are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).


### Changed

- The former `evolve --strategy llm` name is a deprecated alias for the seeded,
  offline `tool_random` strategy; it never invoked a model. Reports distinguish
  heuristic evidence from calibrated confidence.
- Diagnosis uses an approximate terrain-relative height and reports recorded
  positions outside the finite heightfield. Steep-terrain fall detection remains
  a heuristic.
- Launch with the Python environment that was just synchronized, rather than
  requesting Python 3.11 after a different supported version was installed.
- Explain the PyBullet source-build requirement on Windows and macOS before
  users begin setup.

### Security

- The viewer, replay, compare and build-editor servers now listen on `127.0.0.1` only. They used
  Viser's default, which accepts connections from every network interface, so on a shared network
  anyone could open the build editor. The editor has no sign-in and can open and save files by path.
  To share it on purpose, pass `--host 0.0.0.0` (or set `CREATURE_LAB_HOST`); the command prints a
  warning when you do. The Docker image sets `CREATURE_LAB_HOST=0.0.0.0` inside the container, and
  `compose.yaml` still publishes the port on `127.0.0.1` only. A plain `docker run -p 8080:8080`
  publishes it on all interfaces, so use `-p 127.0.0.1:8080:8080`.
- Added `SECURITY.md`.

### Added

- The editor loads three failure lessons, records a repeatable lateral push,
  runs the existing autopsy, compares saved runs, and downloads reports, verified
  packs, and experimental standalone recorded 3D replays.
- **Re-fit gait:** the build editor's Test phase can now CMA-ES retune a body's own motor
  amplitude/frequency/phase in place, as a background job with progress and Cancel — the same
  search behind `creature-lab optimize`, for when a packaged gait no longer fits an edited body.
  The result is one undo step, like any other design change.
- **Camera framing:** the build/replay viewer now points the camera at the creature and scales
  the flat floor grid to its size (`viewers.viser_viewer.creature_reach`), instead of a fixed
  10x10 m grid; the editor also re-frames automatically on a template swap and offers an explicit
  **Frame creature** button.
- A bare `creature-lab` with no arguments now runs a built-in creature through its measured gait
  and prints score + diagnosis directly to the terminal — no browser or subcommand required.
- Streamlined CLI/docs/scripts: `--help` now leads with `Start Here` instead of `Advanced`;
  maintainer-facing roadmap/release docs moved to `docs/project/`; the root README was trimmed;
  `scripts/start.py`/`scripts/browser_smoke.py` share their process/port helpers.
- **Experiment Autopsy and Failure Zoo:** `creature-lab autopsy` runs a selected-controller
  baseline, curated-controller counterfactual, task-aware perturbation trials, and optional
  backend comparison, then attributes the likely cause and emits JSON/Markdown/HTML plus a
  verified experiment pack. `failure list`/`failure export` provide six intentional teaching
  failures with expected causal categories.
- **Verified design-pack v2:** every saved run snapshots its exact controller and optional policy
  payload; packs hash every byte artifact and semantic JSON model; `verify-pack` detects missing,
  modified, unsafe, or incompatible content. Reports reproduce with the saved controller.
- **Executable showcase contracts:** `curated` is the Zoo/editor/demo first-run controller,
  unstable entries are challenges, and `zoo check-showcases` enforces score/no-fall thresholds.
- **Release readiness:** package metadata is 0.2.0, CI covers Linux/Windows/macOS and Python
  3.11/3.12, a dedicated Chromium job drives the real first-run editor, and tagged/manual release
  workflows build verified distributions without publishing automatically.

### Fixed

- **`curated` no longer silently drops the packaged walking gait after a body edit.** The gate
  required an exact `spec_hash` match against the untouched zoo creature, so any slider edit fell
  back to `posture` (which never walks) with nothing indicating a swap happened. Now gated on
  joint-id compatibility instead — the same check `controller validate` already used — so
  resizing, retuning, or recoloring a part no longer defeats it. The Test panel also states what
  `curated` resolves to and notifies if it ever does fall back. See `docs/KNOWN_ISSUES.md`.
- **Build editor layout.** Undo/Redo/Advanced mode moved into an always-visible compact header;
  Project/History collapsed into folders below the phase tabs instead of ~500px of controls
  (7 of them disabled on load) sitting above the primary Design/Motion/Test navigation; the Result
  panel is now pinned directly after Run (Viser's `add_folder(order=...)`) so it survives rebuild
  churn instead of re-appending to the bottom; the Simulate completion message is a friendly
  creature/task/score summary instead of a raw `runs\<hash>` path, and fires a notification. The
  part hierarchy is a clickable button tree instead of static markdown text.
- **The humanoid loop now delivers a measurable result and returns to Design.** Fixed a PyBullet
  tree-order bug that silently mismatched names, joints, contacts, and traces on branched bodies;
  added per-motor force limits and gait center offsets; corrected humanoid mass and horizontal foot
  geometry; and packaged a PyBullet-tuned 12-DOF gait that moves about 0.42 m in 5 s without a
  fall. The editor now owns its Design/Motion/Test phase state and **Back to Design** pauses
  playback and restores the editable preview. Regression tests cover link identity, controller
  fields, body construction, phase restoration, and real-browser operation. `scaffold humanoid`
  and `generate_humanoid()` now default to that footed 12-DOF body; the footless 8-DOF diagnostic
  challenge remains available with `--dof 8`.
- Qualification portability requests can no longer be silently skipped, robustness evaluates
  profile-specific task success rather than just survival, and cancelled partial sweeps cannot
  pass as complete.
- Nonfinite artifact numbers, motors on fixed joints, duplicate controller targets, unsafe
  policy/run paths, XML DTD/entities, and inconsistent target radii are rejected at validation.
- Editor autosave now clears dirty state, pauses on external conflicts, detects deletion/content
  changes, reloads creature+task transactionally, composes nested rotations correctly, and owns
  background-job/browser-process teardown.
- Learned policies record and validate their observation/action ABI and creature/task hashes;
  target tasks observe their targets by default, root orientation/angular velocity are available,
  evaluation seeds match, and both backends can address the same hinge action surface.

### Added earlier in this development cycle

- **`creature-lab optimize`** (Grand Plan Phase 5, Tier 1): tunes a creature's gait (CMA-ES over
  each motor's amplitude/frequency/phase, body untouched) and saves the result as a portable
  `controller.json`, so the existing `evolve --strategy cmaes` search produces a reusable
  artifact instead of a throwaway evolved creature file. Measured on the zoo: quadruped
  0.57 → 1.97 (3.4x), hexapod 0.54 → 1.68 (3.1x), worm 0.93 → 1.51 (1.6x), tripod −0.68 → 0.94
  (its default gait was actually net-negative). `quadruped`/`hexapod`/`tripod`/`worm` each now
  ship this as an additive `controller.json` — `zoo run <name> --controller optimized` opts in,
  and `zoo list` shows which creatures have one; the baked-in default `creature.json` and
  baselines are untouched, so this is zero-risk to existing workflows. A later correction added a
  separately measured controller for the rebuilt 12-DOF humanoid; see the current Zoo docs.
- **`--controller posture`** (Grand Plan Phase 5, Tier 2): the first controller that senses and
  corrects instead of blindly playing a waveform — PD feedback on the previous frame's
  forward/backward lean (`creature_lab/controllers/posture.py`), the same "read prev_frame,
  correct this step" pattern `target_seek` already uses for steering. Measured: a static,
  uncorrected humanoid stance falls at ~2.0s under a 400N forward push; with `posture`'s default
  gains it survives forward and backward pushes up to 1200N and 8s standing with no push at all.
  Honest, measured limitation: every hip/knee/ankle hinge this codebase generates is sagittal-only
  (no side-to-side balance joint anywhere), so `posture` cannot correct sideways tipping — see
  `docs/KNOWN_ISSUES.md`. Available everywhere `--controller` is (CLI, editor Controller
  dropdown, `controller scaffold posture`, `ControllerSpec` with `type: "posture"`).
- **`creature-lab train`** (Grand Plan Phase 5, Tier 3, new optional `rl` extra): trains a real
  PPO policy over `CreatureEnv` (Stable-Baselines3) and saves it as a `policy`-type
  `ControllerSpec` — a `controller.json` + sibling `policy.zip` bundle that runs through
  `--controller <dir>/controller.json` exactly like every other controller type.
  `CreatureEnv` itself was not changed (its `step()`/`reset()` are an older, already-tested API
  real callers depend on); a new `CreatureGymEnv` (`creature_lab/rl/gym_env.py`) wraps it as a
  real `gymnasium.Env` instead — verified against gymnasium's own `check_env` compliance checker.
  `PolicyController` (`creature_lab/controllers/policy.py`) drives a loaded policy through the
  same `(t, prev_frame) -> targets` interface every controller uses, reusing `CreatureEnv`'s own
  observation/action translation rather than duplicating it. Measured, not assumed: a
  100,000-timestep training run on the quadruped example (~110s wall-clock) reached a mean
  episodic return 1.46-2.06x a random baseline on the same task (two independent runs). Scoped
  honestly: a working training loop with a measured positive result, not a promise of a polished
  walker. A later hand-tuned humanoid baseline demonstrates slow PyBullet stepping, but is not an
  RL result or a claim of general bipedal control.
- **Single active roadmap** ([`docs/project/GRAND_PLAN.md`](docs/project/GRAND_PLAN.md)):
  reconciles the three overlapping plan drafts (now archived under `docs/archive/some-plans/`)
  into one phased plan; `docs/project/ROADMAP.md` is reduced to a pointer and
  `docs/archive/IMPROVEMENT_PLAN_2026.md` is marked completed.
  The README now leads with a plain-language "what is this" and the design→move→test→improve loop.
- **Editor foundation, complete** (Grand Plan Phase 1): the build editor is reorganised from a
  vertical folder wall into **Design / Motion / Test** phases with a Project + History header.
  **undo/redo**, named **snapshots**, **reset to template**, **dirty-state** tracking, a
  **Basic/Advanced** mode, and a delete-impact preview so destructive edits (deleting a part with
  children, reloading over unsaved edits) confirm first. **Simulate and the robustness sweep now
  run as background jobs** (`creature_lab/editor/jobs.py`) with a live progress bar, elapsed time,
  and Cancel — `_simulate` and `robustness.run_trials` gained optional, backward-compatible
  `on_step`/`should_stop` hooks for this. A finished run loads into a **Playback** panel
  (`creature_lab/editor/playback.py`: play/pause, frame scrubber, step, restart) instead of
  auto-replaying inline. Non-structural edits (selecting a part or motor) no longer rebuild the
  whole 3D scene — only the affected overlay, or nothing, is touched.
- **Guided design + actionable diagnosis** (Grand Plan Phase 2, shipped subset): a first-run
  creature x goal onboarding picker; human-readable part labels and a part hierarchy tree
  (`creature_lab/editor/labels.py`); diagnosis cards tagged by severity, with an **Apply fix**
  button for patterns that have a safe, bounded, deterministic edit (reduce motor amplitude,
  reverse gait, apply a gait preset, widen stance); an integrated **Run History** panel
  (restore/replay saved runs, `runs.list_recent_runs`); and simplified **Quick/Standard/Thorough**
  robustness levels with a plain-language verdict (`robustness.plain_language_verdict`). Guided
  limb creation, a visual gait composer, a kinematic motion preview, and an explicit before/after
  comparison view remain deferred — see `docs/project/GRAND_PLAN.md` Phase 2.
- **Target-seeking controller** (Grand Plan Phase 3): `--controller target_seek` steers the
  existing CPG gait toward a task's target — body-frame heading-error steering, distance-based
  speed scaling, and a stop radius (`creature_lab/controllers/target_seek.py`), deterministic and
  verified with real-physics scenario tests on both PyBullet and MuJoCo. Works everywhere
  `--controller` already did (`run`, `build`, `bench`, `robustness`, `sim2sim`, `qualify` —
  `evolve` has no `--controller` flag; its `--mutate controller` is a different, unrelated
  thing) via the existing shared `_make_controller`/`_simulate` dispatch, plus a new
  **Controller** dropdown in the build editor's Test phase. Also fixes a pre-existing bug where an
  invalid `--controller` name exited silently with no error message (`typer.BadParameter` raised
  outside a parameter callback isn't printed by Click). New `target_not_approached` diagnosis
  pattern with an Apply-fix that switches to `target_seek`. Posture/balance control and
  per-actuator force/torque limits remain deferred — see `docs/project/GRAND_PLAN.md` Phase 3.
- **`qualify` command** (Grand Plan Phase 4): combines a baseline run, a robustness sweep, and
  (for `backend-portable`, or `--check-portability`) a cross-backend comparison into one
  pass/fail result with a named primary blocker and a recommended next test
  (`creature_lab/qualification.py`). Built-in profiles: `basic-locomotion`, `target-reach`,
  `push-recovery`, `backend-portable`. PyPI publishing, multi-OS CI, and a CLI command-module
  split remain out of scope for this pass — see `docs/project/GRAND_PLAN.md` Phase 4.
- **Audit pass: bug fixes, `ControllerSpec`, and `export-pack`** (Grand Plan Phase 4.5): an
  end-to-end re-verification of Phases 1–4 against the running code found and fixed four real
  bugs — `fell` used to depend on `task.reward.fall_penalty` being configured and is now
  orientation-based (`diagnosis.is_upright`/`first_fall_time`, reward-independent) whenever a
  creature is available; the editor's `target_seek`-without-a-target case surfaced a blank
  `"Failed: "` message instead of the real error; `qualify`'s `target-reach`/`push-recovery`
  profiles ran a full physics baseline before failing on an incompatible task instead of checking
  task/profile compatibility first; and `list_recent_runs` fully pydantic-validated every trace
  (including every recorded frame) just to list a handful of summary rows. Also shipped the two
  highest-value Phase 3/4 deferred items: **`ControllerSpec`**, a fourth portable JSON artifact
  (`creature_lab/schema/controller.py`, `creature_lab/controllers/factory.py`) — `--controller`
  now accepts a `controller.json` path anywhere it accepted a built-in name, a new `controller
  scaffold`/`extract`/`validate` command group authors and checks them, and `TraceMeta.controller`
  records which controller produced a run — and **`creature-lab export-pack`**
  (`creature_lab/exporting.py`), which bundles a run's creature/task/controller/trace plus a
  reproducibility-hash `manifest.json` into one portable, shareable directory. Also added a
  **Qualify** panel to the build editor's Test phase, and a steerability warning when `target_seek`
  is selected on a creature with no `l`/`r`-suffixed motored joint. See
  `docs/project/GRAND_PLAN.md` Phase 4.5.

Earlier phases from
[`docs/archive/IMPROVEMENT_PLAN_2026.md`](docs/archive/IMPROVEMENT_PLAN_2026.md), building on
the complete MVP:

- **Self-contained HTML reports** (Phase R): `report --html` writes a single offline run
  card (score breakdown, signal sparklines, root-path plot, optional embedded GIF,
  diagnosis, and a reproducibility block with a runnable reproduce command).
  `compare --html` writes a before/after comparison report. `gallery build --zoo` now also
  emits `index.html` with baseline-vs-current score coloring per creature.
- **Terrain library** (Phase 1): `TaskSpec.terrain.type` gains `slope`, `steps`, `gaps`, and
  `rough`, built from a shared, deterministic heightfield (`creature_lab/terrain.py`) that
  both the PyBullet and MuJoCo backends simulate with the same shape. Three new quadruped
  zoo tasks: `slope_climb`, `step_over`, `gap_cross`.
- **Robustness and sim2sim analysis** (Phase 2): `robustness <run> --trials N` re-simulates
  under small seeded mass/friction perturbations and reports the score distribution and
  fail rate. `sim2sim <run>` runs the same creature/task on PyBullet and MuJoCo and reports
  the score gap and trajectory divergence. Both support `--save` to write a reportable run.
- **Quality-diversity gallery** (Phase 3): `evolve --strategy map_elites` now persists each
  filled cell's `CreatureSpec`. `archive show <run> --html` renders a scored heatmap (with
  optional per-cell replay GIFs via `--task`); `archive export --cell row,col` pulls one
  elite out as a standalone spec.
- **Sharpened LLM design loop** (Phase 4): `ask`'s prompt (and the offline policy's
  `Observation`) now includes the current diagnosis, so proposals can target a detected
  failure pattern instead of guessing blind. New `evolve --strategy llm` mutation operator
  reuses the offline, no-API-key `RandomToolPolicy` through the validated tool layer;
  per-attempt rationale is saved into `lineage.json`.
- **MuJoCo baselines** (Phase 5): every packaged zoo creature/task pair now has a
  real, measured MuJoCo baseline (`baselines/<task>.mujoco.json`) alongside the existing
  PyBullet one; `zoo_baseline(..., backend=...)` and `bench --backend mujoco --zoo` compare
  against the correct one (previously `bench` always compared against the PyBullet
  baseline, even when benchmarking MuJoCo — this silently made the pass/fail threshold
  wrong for every non-default-backend benchmark run).

- **Terrain fidelity in viewer/export/report**: `view`, `compare`, `export`, and the run
  report's embedded GIF now draw the *actual* terrain shape (a `trimesh` heightfield mesh
  in the Viser viewer, a PyBullet heightfield body in `render_trace`) instead of always a
  flat floor. Found in a post-implementation review: the terrain physics was correct but
  every visualization still showed a flat plane, so a `slope_climb`/`gap_cross` replay
  misleadingly showed the creature floating above or sinking into nothing.
- **Terrain surfaced in reports/inspect**: `creature_lab/terrain.describe_terrain()` gives
  a one-line summary (e.g. `"slope (angle=0.2 rad, friction=1)"`), now shown by `inspect`
  and included in every run report (Markdown, HTML, and JSON) — previously a report gave
  no indication of which terrain a run used.
- `docs/KNOWN_ISSUES.md`: a living list of latent gaps and deliberate limitations found in
  review, so findings have a home instead of being re-discovered or lost.
- **Self-contained archive heatmaps**: `archive show --html --task` now embeds per-cell
  replay GIFs as `data:` URIs (matching the run report), instead of writing them to a
  sibling directory the page depends on and breaks if moved.
- **CI now wheel-tests the package**: builds the wheel, installs it into a fresh venv, and
  runs `doctor` + `zoo run` against the installed package on every push/PR — the same check
  Phase 5 previously only ran by hand.
- `validate_episode_inputs` warns when a task's **target** lies outside the generated
  terrain's finite extent on non-flat terrain — closes part of the "non-flat terrain has a
  finite 6.4 m extent" known issue (the target-based case; open-ended locomotion tasks
  can't be checked this way, since expected travel isn't derivable from the spec alone).
- `terrain.py` now asserts its default grid is square at import time, since the
  PyBullet/MuJoCo axis convention was only verified empirically for `rows == cols`.

### Fixed

- **A successful onboarding run could still score negative, and the humanoid fell over
  instantly.** Measured every onboarding creature x goal x controller combination through real
  physics (not assumed) and found two separate real bugs:
  - **Reward miscalibration**: `reach_target`'s `energy_penalty` was ~10x too large relative to
    the actual energy an open-loop gait accumulates in a few seconds (measured: ~100-280 raw
    units), so a run that reached 83% of the way to the target still scored **-0.10**.
    `stability_hold` was built only from penalties, so its best possible score was 0 — a creature
    that stayed upright the whole episode could never score positive. Fixed by lowering the
    onboarding `energy_penalty` (re-measured empirically for every preset creature) and adding a
    new **`RewardSpec.survival`** field (`creature_lab/scoring.py`) — the positive mirror of
    `fall_penalty` — so "stay balanced" tasks can actually be won. The Result headline now also
    leads with concrete progress ("Moved 0.83 m closer to the target; stayed upright") with the
    raw score shown below it, not as the sole, unexplained headline.
  - **The humanoid**: a systematic stability sweep found that *any* nonzero open-loop sinusoid
    gait topples this biped in 0.8-3.3s regardless of stance width or leg length — only a fully
    static stance passively balances (a fundamental limitation of open-loop control on a biped,
    not a tunable parameter; real walking needs a balance controller, which doesn't exist yet).
    The onboarding humanoid now defaults to `dof=12` (feet/hands) and `amplitude=0` (a stable
    stance rather than a gait that reliably falls), and picking Humanoid in onboarding
    auto-switches the Goal to **Stay balanced** with an explanatory note, since that's the one
    goal it can actually achieve (measured: stays upright the full episode, score 1.000).
  See `docs/KNOWN_ISSUES.md` for the full measurement writeup.
- **The build editor's first run was unusable** (found by driving the real editor in a headless
  browser, which is the only thing that catches client-side rendering bugs): the Welcome
  onboarding was a Viser modal, and a Viser/Mantine modal traps focus onto its first control —
  which **auto-opened the Creature dropdown right on top of the Start/Skip buttons**. A
  first-time user could not click Start or Skip (clicking either hit a dropdown option), and the
  modal overlay blocked every other click too, so tabs and Simulate appeared dead — "can't go
  back to Design / Test doesn't work / it simply doesn't work." Onboarding is now an inline
  **Get started** panel at the top of the side panel (no focus trap, no auto-open); everything
  below it — tabs, controllers, Simulate — works normally.
- **The Test phase showed conflicting info after a run.** After Simulate, changing the controller,
  task, or body left the old score/breakdown/diagnosis showing next to a status describing a
  different configuration (e.g. a healthy sinusoid score beside a "target_seek needs a target"
  error). A run's result is now tagged with the `(creature, task, controller)` that produced it
  and cleared the moment the live config drifts from it, so the panel never shows a stale result.
- Added `scripts/browser_smoke.py` (new optional `browser` extra) — a headless-browser smoke
  test that drives the editor's first-run journey and asserts it stays usable and error-free.
  This is the class of test that catches the two bugs above; the fake-GUI unit tests
  structurally cannot (see `docs/BUILD_EDITOR.md`).
- **The build editor could fail to render at all** (a blank white page, found via a real
  headless-browser check, not just a server-boots check): the Test phase's Run History dropdown
  passed Viser/Mantine a list of option labels without deduplicating them. Two saved runs with
  the same creature, task, score, and "time ago" bucket (rounded to whole seconds/minutes/tenths
  of an hour) produce an identical label — trivial to hit just by re-running the same example
  twice — and Mantine's underlying `Select` component throws on a duplicate option value, which
  crashed the *entire* React app, not just the dropdown. `BuildControls._unique_run_history_labels`
  now disambiguates colliding labels with the run id, only when they actually collide.
- `bench --zoo --backend mujoco` compared results against the PyBullet baseline (a much
  higher score than nearly every gait achieves on MuJoCo), so the pass/fail threshold was
  meaningless for any backend other than the default.
- `evolve --strategy map_elites` discarded each archived cell's `CreatureSpec`, saving only
  its score/features — `archive export` had nothing to export until this was fixed.

## [0.1.0]

Initial MVP: schemas, CLI, PyBullet and MuJoCo backends, Viser replay, local evolution
(hill-climb/genetic/MAP-Elites/CMA-ES), offline/online `ask` design loop, the Creature Zoo,
diagnosis, URDF/MJCF export, and reports. See [`docs/archive/`](docs/archive/) for the
phase-by-phase history.
