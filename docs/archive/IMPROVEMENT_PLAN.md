# Creature Lab — Improvement Plan

**Date:** 2026-06-22  
**Premise:** The MVP is complete. `demo → run → evolve → ask` all work, 132 tests pass,
the CLI is end-to-end verified. The question is now: what makes this repo worth using over
existing tools, and how do we build it step by step?

---

## Evaluation of the prior plan

The prior plan (from the conversation session) correctly identified the core differentiators.
Two things it got right that this plan builds on:

- **Identity:** "Every creature is JSON. Every controller is JSON. Every task is JSON.
  Every episode is a trace. Every simulator is an adapter." Already in the repo — keep it.
- **Position:** Creature Lab is the creature-design layer above simulators and below
  agent arenas. Not a simulator. Not a challenge studio. Not Agentarium.

Three things the prior plan got wrong or left incomplete:

1. **It ignored what is already built.** The prior plan was written as if the repo were empty.
   Schema, CLI, PyBullet backend, Viser viewer, evolve, ask, scoring, inspect, doctor — all
   exist and pass tests. The plan should start from that state.
2. **No implementation steps.** Feature bullet lists are not actionable. Each phase below has
   specific files, specific commands, specific acceptance criteria.
3. **Wrong first priority.** The most visible problem right now is that the demo is boring
   (one stationary tripod, no variety). Fix the demo UX before adding new architecture.

---

> **Status:** All phases 0–8 ✅ done (2026-06-22).

## Phase 0 — Fix the demo experience (immediate, no new architecture) ✅

**Outcome (what shipped):** The real cause of the "stationary creature" was twofold:
every creature spawns 1 m above the plane and crash-lands, and the tripod's single-hinge
legs produce almost no net thrust (measured: **0.017 m** forward in 3 s, with 0.42 m of
sideways drift, ending toppled). Rather than tune a fundamentally poor walker, the demo
default is now a **quadruped** with backward-tilted legs (oar-like thrust) that travels
**~0.58 m straight** and stays upright, plus a **worm** that undulates ~0.44 m straight.
`creature-lab demo --creature {quadruped,worm,tripod}` picks a built-in; `library.py` gained
`creature_by_name` / `builtin_creature_names`; `examples/worm.json` and
`examples/quadruped.json` were added. Tripod is kept as a built-in and example for comparison.
All distances were verified empirically against the PyBullet backend.

### Original Phase 0 analysis (superseded by the outcome above)

**Why first:** The current `demo` shows one three-legged creature that falls over and stays
stationary. It is not a compelling first impression. This is a content problem, not a
code problem. Fix it before writing new systems.

**Root cause of stationary tripod:**  
The tripod legs use sinusoidal motors but all three legs share the same phase (0.0). A
symmetric gait with zero phase offset on all legs produces balanced forces that cancel: the
creature oscillates in place. Fix: set distinct phases per leg (e.g. 0.0 / 2.09 / 4.19 rad)
so the legs create a rolling gait with net forward impulse.

**Deliverables:**

```
examples/
  tripod.json            ← fix leg phases, spread anchors further apart
  worm.json              ← new: 4-segment worm with alternating vertical undulation
  quadruped.json         ← new: 4-legged trotting creature
  spider.json            ← new: 6-legged hexapod
  hopper.json            ← new: single-leg hopper
  tasks/
    crawl_forward.json   ← already exists
    reach_target.json    ← already exists
    recover_after_damage.json ← already exists
    hop_forward.json     ← new: single-leg task with a distance gate
```

**Specific changes:**

- [creature_lab/library.py](creature_lab/library.py): `default_creature()` currently returns
  the broken tripod. Update it to return the fixed tripod. Add `creature_by_name(name: str)`
  that loads any built-in creature by name from the examples folder.
- [creature_lab/cli.py](creature_lab/cli.py): `demo` command should accept `--creature` to
  pick a named built-in creature (e.g. `creature-lab demo --creature worm`).
- [examples/tripod.json](examples/tripod.json): Fix the three motor phases.

**Acceptance criteria:**
- `creature-lab demo` shows a creature that visibly travels forward.
- `creature-lab demo --creature worm` shows the worm example.
- `creature-lab demo --creature quadruped` shows the quadruped.
- All new examples validate and simulate without errors.
- `pytest` still green.

---

## Phase 1 — Scaffold commands (differentiator #1) ✅

**Outcome (what shipped):** `creature_lab/scaffold/` (pure `generate_*` functions returning
validated specs: worm, quadruped, hexapod, humanoid + `mirror_limb`) and `creature_lab/export/`
(`export_urdf`, plus an `export_mjcf` stub for Phase 8). CLI: `scaffold worm|quadruped|hexapod|
humanoid`, `mirror-limb`, `export-urdf`. All scaffolded walkers were verified to move forward
(+X) — the hexapod needed a lateral/pace gait rather than the quad's diagonal trot. The
generated URDF is well-formed and **loads in PyBullet** (real round-trip, not just XML parse).
19 new tests; full suite green (151 passing), ruff clean.

### Original Phase 1 plan

**Why this is the wedge:** MuJoCo Menagerie is a model library (curated fixed assets).
Creature Lab would be a morphology authoring tool — you describe what you want and get a
valid JSON creature, rather than hand-writing URDF/MJCF. No existing lightweight tool
offers this.

**New CLI commands:**

```bash
creature-lab scaffold worm --segments 4 --out worm.json
creature-lab scaffold quadruped --leg-length 0.3 --out quad.json
creature-lab scaffold hexapod --out hex.json
creature-lab scaffold humanoid --out humanoid.json
creature-lab mirror-limb creature.json --side left --out creature2.json
creature-lab export-urdf creature.json --out robot.urdf
```

**New files to create:**

```
creature_lab/
  scaffold/
    __init__.py
    worm.py          ← generate_worm(segments, radius, length) → CreatureSpec
    quadruped.py     ← generate_quadruped(leg_length, body_size) → CreatureSpec
    hexapod.py       ← generate_hexapod(...) → CreatureSpec
    humanoid.py      ← generate_humanoid(dof) → CreatureSpec
    mirror.py        ← mirror_limb(spec, part_prefix, side) → CreatureSpec
  export/
    __init__.py
    urdf.py          ← export_urdf(spec) → str
    mjcf.py          ← export_mjcf(spec) → str  (stub, flesh out in Phase 8)
```

**Design rules for scaffold generators:**

- Each generator is a pure function: `CreatureSpec` in, `CreatureSpec` out. No side
  effects, no file I/O.
- Every generated creature must pass `validate_creature(spec)` before being returned.
- Generators accept keyword arguments for the key morphological parameters. Defaults
  produce a working creature immediately.
- Motor phases are staggered automatically (e.g. quadruped: FL 0°, FR 90°, RL 180°,
  RR 270°; worm: each segment offset by `2π/n`).

**CLI wiring:**

Add a `scaffold` group to [creature_lab/cli.py](creature_lab/cli.py):

```python
@scaffold_app.command("worm")
def scaffold_worm(segments: int = 4, out: Path = Path("worm.json")): ...
```

**URDF export specifics** ([creature_lab/export/urdf.py](creature_lab/export/urdf.py)):

- Map `PartSpec.shape` → URDF `<geometry>` (`<box>`, `<sphere>`, `<cylinder>`,
  `<mesh>`).
- Map `JointSpec` → URDF `<joint>` with `type="revolute"` (hinge) or `type="fixed"`.
- Emit inertial blocks with identity inertia tensors as stubs.
- Add a test: `export_urdf(spec)` produces valid XML (parse with `xml.etree.ElementTree`).

**Acceptance criteria:**

- `creature-lab scaffold worm --segments 5 --out /tmp/worm.json` produces a file that
  passes `creature-lab validate /tmp/worm.json`.
- `creature-lab scaffold humanoid --out /tmp/h.json` produces a file that validates.
- `creature-lab mirror-limb examples/quadruped.json --side left --out /tmp/q2.json`
  produces a valid spec with mirrored limbs.
- `creature-lab export-urdf examples/tripod.json --out /tmp/r.urdf` produces well-formed
  XML.
- New tests cover: scaffold generators produce valid specs; URDF export parses; mirror
  produces symmetric anchors.

---

## Phase 2 — Creature Zoo (differentiator #2) ✅

**Outcome (what shipped):** `creature_lab/zoo/` ships 5 curated creatures —
`quadruped`, `worm`, `hexapod`, `tripod`, `damaged_quadruped` — each with `creature.json`,
a `tasks/` dir, and computed `baselines/<task>.json` score baselines. `creature_lab/zoo.py`
loads them (`list_zoo_creatures`, `zoo_creature`, `zoo_tasks`, `default_task_name`,
`validate_all`); CLI `zoo list|run|validate-all`. The creatures are generated from the Phase 1
scaffolds (single source of truth). Measured open-loop baselines: worm +0.93, quadruped +0.57,
hexapod +0.54, damaged_quadruped +0.52, tripod **−0.69** (drifts backward — a deliberate
diagnosis subject). 10 new tests.

### Original Phase 2 plan

**Why:** The repo is only shareable and understandable if it has a curated gallery.
"Clone and play" only works if there is something to play with. This is also the
fastest way to demonstrate the scaffold commands from Phase 1.

**Target zoo structure:**

```
zoo/
  worm/
    creature.json
    tasks/
      crawl_forward.json
      damage_recovery.json
    baselines/
      score.json          ← {"best_score": 0.72, "backend": "pybullet", ...}
      diagnostics.md      ← brief notes on what to expect
  quadruped/
    creature.json
    tasks/
      crawl_forward.json
      reach_target.json
    baselines/
      score.json
      diagnostics.md
  hexapod/
    creature.json
    tasks/
      crawl_forward.json
    baselines/
      score.json
      diagnostics.md
  hopper/
    creature.json
    tasks/
      hop_forward.json
    baselines/
      score.json
      diagnostics.md
  humanoid_minimal/       ← added in Phase 6; placeholder for now
  damaged_quadruped/
    creature.json         ← same as quadruped but with one leg pre-removed
    tasks/
      recover_after_damage.json
    baselines/
      score.json
      diagnostics.md
```

**New CLI command:**

```bash
creature-lab zoo list                    # print the built-in zoo
creature-lab zoo run quadruped           # run the zoo creature with its default task
creature-lab zoo run quadruped --task reach_target
creature-lab zoo validate-all            # validate every zoo creature/task pair
```

**Implementation:**

- Add [creature_lab/zoo.py](creature_lab/zoo.py): `list_zoo_creatures()` → list of names;
  `zoo_creature(name)` → `(CreatureSpec, TaskSpec)`.
- Zoo files live under `creature_lab/zoo/` (as package data) or under a top-level `zoo/`
  directory loaded by path.
- Add `zoo` group to CLI.

**Acceptance criteria:**

- `creature-lab zoo list` prints at least 5 creatures.
- `creature-lab zoo run worm` runs and saves a trace.
- `creature-lab zoo validate-all` exits 0.
- `pytest` tests cover `zoo_creature` loading and `zoo validate-all`.

---

## Phase 3 — Failure diagnosis command (differentiator #3) ✅

**Outcome (what shipped):** `creature_lab/diagnosis.py` — `diagnose(trace, creature, task)`
derives locomotion signals (mass-weighted CoM path, fall time from the root up-axis, joint
effort, ground-contact fractions, motor-vs-limit) and matches 8 failure patterns:
`motor_over_limit`, `no_ground_contact`, `early_fall`, `moving_backward`,
`high_effort_low_result`, `lateral_drift`, `single_leg_drag`, `com_instability`. CLI
`diagnose runs/<id>` (ASCII-safe for Windows cp1252 terminals). Two real bugs found and fixed
during calibration: net displacement and CoM-height variance were both inflated by the one-time
fall from the z=1 spawn, so every healthy walker false-flagged `com_instability` — fixed by
using **horizontal** displacement and measuring height stability only **after the settling
transient**. Verified: healthy walkers flag nothing; tripod → `moving_backward`;
damaged_quadruped → `single_leg_drag`. 8 new tests (7 synthetic + 1 real-episode integration).

**Note on the plan's premise:** the original spec expected `symmetric_cancellation` to fire on
"the unpatched tripod (equal motor phases)". Phase 0 established the tripod's phases were already
staggered and it actually drifts *backward*, so the implemented detectors match real behavior
(`moving_backward`) rather than the assumed cause.

### Original Phase 3 plan

**Why this is the most distinctive feature:** Every existing physics tool (MuJoCo,
PyBullet, Isaac Lab) shows *what* happened. None of them explain *why* the creature failed
in plain terms. This is the feature most useful to both human beginners and LLM agents.

**New CLI command:**

```bash
creature-lab diagnose runs/<id>
```

**Example output:**

```
Diagnosis: runs/abc123
─────────────────────────────────────────────────────────────────────────
  Root displacement   0.03 m in 3.0 s  [POOR — less than 0.1 m expected]
  Total joint motion  8.2 rad           [high actuation, low result]
  Contact symmetry    symmetric         [no net directional impulse]
  Fall               YES at t=1.24 s
  Joint limit hits    72% of frames     [motors exceed limits most of the time]
─────────────────────────────────────────────────────────────────────────
Root cause patterns detected:
  ⚠  Symmetric contact with no net impulse — legs push equally in
     all directions. Offset gait phases to create directional thrust.
  ⚠  Motor amplitudes exceed joint limits on hip_a, hip_b, hip_c.
     Reduce amplitude or widen joint limits.
  ⚠  Creature fell at 1.24 s. Center of mass rose then dropped sharply.
     Lower the torso height or increase leg spread.

Suggested edits:
  1. Offset leg phases: 0.0 / 2.09 / 4.19 rad
  2. Set motor amplitude ≤ joint limit for hip_a, hip_b, hip_c
  3. Reduce torso height by ~20% or increase leg anchor spread

```

**Implementation:**

New file [creature_lab/diagnosis.py](creature_lab/diagnosis.py):

```python
@dataclass
class DiagnosisResult:
    metrics: dict[str, float]
    patterns: list[str]  # detected failure pattern names
    explanations: list[str]  # human-readable descriptions
    suggestions: list[str]  # concrete edits to try


def diagnose(trace: EpisodeTrace, task: TaskSpec) -> DiagnosisResult: ...
```

**Failure patterns to detect (implement these in order):**

| Pattern | Signal | Explanation |
|---|---|---|
| `symmetric_cancellation` | contacts are symmetric + displacement < threshold | Leg phases cancel each other |
| `motor_over_limit` | any frame where joint target > limit | Motor amplitude exceeds joint limit |
| `early_fall` | fall at t < 30% of duration | Creature falls too fast |
| `high_effort_low_result` | total_joint_motion > 5.0 and displacement < 0.05 | Lots of motion, no progress |
| `no_ground_contact` | zero contacts in first 0.5 s | Creature starts airborne |
| `single_leg_drag` | one limb contacts ground for > 80% of frames | One leg dominates, others don't contribute |
| `com_instability` | CoM height variance > threshold | Center of mass is too variable |

**Wiring:**

- [creature_lab/cli.py](creature_lab/cli.py): add `diagnose` command that loads a run dir
  and calls `diagnose(trace, task)`.
- `EpisodeSummary` already has `net_displacement`, `forward_displacement`,
  `total_joint_motion`, `fell` — reuse these; add CoM height series derivation from frames.

**Acceptance criteria:**

- `creature-lab diagnose runs/<any-run-id>` produces output without crashing.
- The `symmetric_cancellation` pattern fires on the unpatched tripod (equal motor phases).
- The `motor_over_limit` pattern fires when amplitude > limit.
- `pytest` covers at least 4 pattern detectors with synthetic traces.

---

## Phase 4 — Closed-loop control / Gymnasium wrapper ✅

**Outcome (what shipped):** `schema/control.py` (`ObservationSpec`, `ActionSpec`);
`FrameState` gained optional `observations`/`actions` (old traces still load).
`creature_lab/env.py` — `CreatureEnv` with `reset()`/`step(action)->(obs, reward, done, info)`,
`observation_space`/`action_space`; observations are numpy arrays assembled per
`ObservationSpec`, with **root and joint velocities computed by finite difference** so the env
stays backend-agnostic (no engine velocity API needed). A new `PyBulletBackend.observe()` reads
the initial state without stepping. Controllers added: `controllers/cpg.py` (Kuramoto coupled
oscillators), `controllers/pid.py`, `controllers/pose_seq.py`. CLI `run --controller {sinusoid,cpg}`.
Verified: on an uncoordinated (all-phase-0) quadruped the **CPG travels 0.72 m vs the plain
sinusoid's 0.24 m**. 14 new tests.

### Original Phase 4 plan

**Why:** Right now the only controller is `sinusoid` — a fixed open-loop gait. For AI
agents to learn locomotion rather than just having a gait hand-coded, the system needs a
step-by-step observation/action interface. This is also what enables reinforcement learning.

**New schemas** (add to [creature_lab/schema/](creature_lab/schema/)):

```python
# schema/obs.py
class ObservationSpec(StrictModel):
    include_root_pos: bool = True
    include_root_vel: bool = True
    include_joint_angles: bool = True
    include_joint_velocities: bool = True
    include_contacts: bool = False
    include_target_vector: bool = False


# schema/action.py
class ActionSpec(StrictModel):
    mode: Literal["torque", "position", "velocity"] = "position"
    joints: list[str]  # which joints this agent controls
    clip_range: tuple[float, float] = (-1.0, 1.0)
```

**New file** [creature_lab/env.py](creature_lab/env.py):

```python
class CreatureEnv:
    """Gymnasium-compatible wrapper around a SimBackend."""

    def __init__(
        self,
        creature: CreatureSpec,
        task: TaskSpec,
        obs_spec: ObservationSpec,
        action_spec: ActionSpec,
        backend: SimBackend,
    ): ...

    def reset(self, seed: int | None = None) -> np.ndarray: ...
    def step(self, action: np.ndarray) -> tuple[np.ndarray, float, bool, dict]: ...
    def close(self) -> None: ...

    @property
    def observation_space(self) -> dict: ...
    @property
    def action_space(self) -> dict: ...
```

**New controllers:**

```
creature_lab/controllers/
  cpg.py          ← central pattern generator: coupled oscillators per joint
  pid.py          ← PID position controller
  pose_seq.py     ← replay a pose sequence (keyframe animation)
```

**Store observations and actions in EpisodeTrace:**

- Add `observations: list[list[float]] | None` and `actions: list[list[float]] | None`
  to `FrameState` (both optional so old traces stay compatible).
- `CreatureEnv.step()` stores observation and action taken into the current frame.

**CLI:**

```bash
creature-lab run examples/tripod.json --task examples/crawl_forward.json --controller cpg
creature-lab run examples/tripod.json --task examples/crawl_forward.json --controller sinusoid
```

**Acceptance criteria:**

- `CreatureEnv` can do `reset() → step() → step() → close()` without error.
- Observations are numpy arrays with shape matching `ObservationSpec`.
- CPG controller produces different per-joint phases that lead to better forward locomotion
  than the single sinusoid (verify by comparing scores from a baseline run).
- Old traces without obs/action fields still load.
- `pytest` covers env reset/step, CPG output, PID step.

---

## Phase 5 — Debug viewer overlays ✅

**Outcome (what shipped):** `creature_lab/viewers/overlays.py` — pure, unit-tested analysis
series (`center_of_mass_trail`, `root_path`, `joint_energy_series`, `metric_series`).
`viser_viewer.py` gained `add_debug_overlays` (CoM trail + root ground path point clouds + a
fall marker from the Phase 3 diagnosis), a `prefix`/`add_floor`-aware `build_scene`, an `offset`
on `apply_frame`, and `compare_traces` (two runs side by side in one scene). `viewers/plotting.py`
plots a metric to PNG/window (matplotlib, added to the `viz` extra). CLI: `view --debug`,
`compare`, `plot`. 8 new tests (overlay math + headless viser/plot). CoM is mass-weighted and
verified (3:1 masses over a 4 m span → CoM at 1.0 m).

### Original Phase 5 plan

**Why:** The current `view` command shows the creature replay, but the viewer is not yet
a debugger. The diagnosis command (Phase 3) tells you *what went wrong in text*; the viewer
should show it *visually*.

**New viewer overlays** ([creature_lab/viewers/viser_viewer.py](creature_lab/viewers/viser_viewer.py)):

| Overlay | Toggle key | Description |
|---|---|---|
| `--com` | C | Center-of-mass trajectory as a colored trail |
| `--root-path` | R | Root body XY path drawn on the floor |
| `--contact-timeline` | T | Per-part foot-contact bar chart in a side panel |
| `--joint-heatmap` | H | Part color indicates actuator effort (blue=low, red=high) |
| `--fall-marker` | F | Red sphere at the CoM position when fall was detected |
| `--score-breakdown` | S | Score component bars (forward/target/energy/fall) per frame |

**New CLI commands:**

```bash
creature-lab view runs/<id> --debug           # enable all overlays
creature-lab compare runs/a runs/b            # side-by-side replay in same viewer
creature-lab plot runs/<id> --metric joint_energy   # matplotlib line chart
```

**Implementation notes:**

- CoM position per frame: `mean(frame.parts[id].position for id in all_parts, weighted by mass)`.
  Mass is available from `CreatureSpec.parts[id].mass`.
- Contact timeline: pre-compute a `dict[str, list[bool]]` from frames before playback starts;
  render as colored rectangles in a Viser GUI panel.
- `compare`: run two `TracePlayer` instances in the same Viser server, offset in X by
  a gap so both creatures are visible simultaneously.

**Acceptance criteria:**

- `creature-lab view runs/<id> --debug` does not crash and shows the CoM trail.
- `creature-lab compare runs/a runs/b` shows two creatures side by side.
- `creature-lab plot runs/<id> --metric joint_energy` saves a PNG or opens a window.
- `pytest` covers CoM calculation correctness.

---

## Phase 6 — Humanoid creature kit ✅

**Outcome (what shipped):** Two zoo entries built from the Phase 1 scaffold —
`humanoid_minimal` (8-DOF; tasks `balance`, `walk`, `push_recovery`) and `humanoid_12dof`
(tasks `walk`, `reach`) — with computed baselines. A new **impulse event** (`ImpulseEventSpec`
on `TaskSpec`, applied by the PyBullet backend via `applyExternalForce`, cross-validated like
`damage_event`) makes `push_recovery` real; verified a sideways shove moves the body. Four
humanoid-specific diagnosis patterns added (gated on a humanoid-naming check so non-humanoids are
untouched): `biped_asymmetric_fall`, `knee_hyperextension`, `arm_swing_absent`, `stance_too_narrow`.
The untuned humanoids fall (as expected) — they are editable/diagnosable data, the point of the
kit. Also fixed a latent `contact_fraction` bug (counted contact *points*, not frames, so a part
could show >100%). The "no objective" validation warning now treats `fall_penalty` as a valid
objective (for balance tasks). 11 new tests.

### Original Phase 6 plan

**Why:** The differentiator here is not "we have a humanoid." Isaac Lab, Gymnasium-Robotics,
and MuJoCo Menagerie all have humanoids. The differentiator is: you can *edit, diagnose, and
evolve the humanoid morphology as data* — as easily as any other CreatureSpec.

**New zoo entries** (via scaffold from Phase 1):

```
zoo/
  humanoid_minimal/
    creature.json          ← 8-DOF minimal biped
    tasks/
      balance.json         ← stay upright for T seconds
      walk.json            ← travel 1.0 m forward
      push_recovery.json   ← apply impulse at t=1.5s, recover
    baselines/
      score.json
      diagnostics.md

  humanoid_12dof/
    creature.json          ← 12-DOF humanoid with arms
    tasks/
      walk.json
      reach.json           ← reach a target with one hand
    baselines/
      score.json
      diagnostics.md
```

**New humanoid-specific diagnosis patterns** (add to [creature_lab/diagnosis.py](creature_lab/diagnosis.py)):

| Pattern | Signal |
|---|---|
| `biped_asymmetric_fall` | one side contacts ground more; fall direction consistent |
| `knee_hyperextension` | knee joint hits limit > 50% of stance frames |
| `arm_swing_absent` | arm joints move < 5% of total joint motion |
| `stance_too_narrow` | foot contact width < 0.2 * creature height |

**New humanoid scaffold** ([creature_lab/scaffold/humanoid.py](creature_lab/scaffold/humanoid.py)):

```python
def generate_humanoid(
    height: float = 1.6,
    mass: float = 60.0,
    dof: Literal[8, 12] = 8,
) -> CreatureSpec: ...
```

The generator should produce:
- Torso (box)
- Head (sphere)
- Upper/lower legs (capsule × 4)
- Upper/lower arms if `dof=12` (capsule × 4)
- Hip, knee, ankle joints per side (hinge)
- Shoulder, elbow joints if `dof=12`
- Motor phases staggered for a crude walking gait

**Acceptance criteria:**

- `creature-lab scaffold humanoid --out /tmp/h.json` produces a valid 8-DOF spec.
- `creature-lab scaffold humanoid --dof 12 --out /tmp/h12.json` produces a valid 12-DOF spec.
- Both specs simulate without crash (even if they fall immediately).
- `creature-lab zoo run humanoid_minimal` runs and saves a trace.
- `creature-lab diagnose` detects `biped_asymmetric_fall` on a deliberately lopsided humanoid.
- `pytest` covers scaffold output validity and diagnosis patterns.

---

## Phase 7 — Evolution improvements ✅

**Outcome (what shipped):** `evolve.py` gained typed mutation operators
(`mutate_controller`, `mutate_morphology` — resize limb / shift anchor / perturb hinge axis),
`crossover` (blends one creature's motor params into another's topology, always valid), a
`make_mutator(body, controller)` gate, and four strategies: `hill_climb` (kept, no regression),
`genetic` (population + crossover + elitism), `map_elites` (quality-diversity archive over a
forward-displacement × gait-symmetry grid), and `cmaes` (CMA-ES over motor params, optional
`cmaes` extra). Every strategy returns a lineage (`Attempt` now carries `parent`/`generation`/
`cell`). CLI: `evolve --strategy … --mutate body,controller`, plus a new `lineage` command
(tree view, or `--best N`). Evolve runs now save `lineage.json` and, for MAP-Elites,
`archive.json`. 12 new tests; verified on the live backend (genetic 0.24→0.37, CMA-ES 0.24→0.38
on the example quadruped).

**Deviations from the plan:** (1) lineage is stored as a self-contained `lineage.json` in the
evolve run dir rather than via new `TraceMeta.parent_run_id`/`generation` fields — simpler and
sufficient for the `lineage` command, so those `TraceMeta` fields were not added. (2) Found and
fixed a display bug where Rich parsed `[strategy]` as a markup tag (now parenthesised).

### Original Phase 7 plan

**Why:** The current `evolve` command uses hill-climbing with random mutations. This
is functional but crude. The differentiator against Evolution Gym is that Creature Lab
focuses on *articulated rigid creatures* (not soft voxel robots) with *joint-level
co-evolution of body and controller*.

**New strategies** ([creature_lab/evolve.py](creature_lab/evolve.py)):

| Strategy | Flag | Description |
|---|---|---|
| Hill-climb (current) | `--strategy hill_climb` | Keep best, mutate randomly |
| CMA-ES | `--strategy cmaes` | Covariance Matrix Adaptation Evolution Strategy |
| MAP-Elites | `--strategy map_elites` | Grid of (displacement, gait_symmetry) cells |
| Genetic | `--strategy genetic` | Population-based crossover + mutation |

**New mutation operators:**

```python
# In evolve.py
def mutate_morphology(spec: CreatureSpec, rng) -> CreatureSpec:
    """Randomly resize a limb, shift an anchor, or flip a joint axis."""


def mutate_controller(spec: CreatureSpec, rng) -> CreatureSpec:
    """Randomly change motor amplitude, frequency, or phase."""


def crossover(a: CreatureSpec, b: CreatureSpec, rng) -> CreatureSpec:
    """Combine the parts from one creature with the motors from another."""
```

**New CLI options:**

```bash
creature-lab evolve examples/tripod.json --task examples/crawl_forward.json \
  --strategy map_elites \
  --mutate body,controller \
  --attempts 200 \
  --seed 42

creature-lab lineage runs/evolve/<id>   # print ancestral lineage tree
creature-lab lineage runs/evolve/<id> --best 5  # show top 5 ancestors
```

**MAP-Elites grid:**

- Dimension 1: forward displacement (bucketed into 10 bins).
- Dimension 2: gait symmetry (contact left/right ratio, bucketed into 5 bins).
- Each cell stores the best creature for that behavior niche.
- Archive is saved as `runs/evolve/<id>/archive.json` after each generation.

**Lineage trace:**

Add `parent_run_id: str | None` and `generation: int` to `TraceMeta` so the evolution
tree can be reconstructed from run directories.

**Dependency note:** CMA-ES requires `cmaes` (pip). Add as `[tool.uv.extras] evolve = ["cmaes"]`.

**Acceptance criteria:**

- `evolve --strategy hill_climb` still works (no regression).
- `evolve --strategy map_elites --attempts 50` produces an `archive.json`.
- `creature-lab lineage runs/evolve/<id>` prints a tree without crashing.
- `pytest` covers crossover validity (output is valid `CreatureSpec`), MAP-Elites cell
  assignment, and that CMA-ES at least initializes without error.

---

## Phase 8 — Export/import bridge and MuJoCo backend ✅

**Outcome (what shipped):** Full `export_mjcf` ([export/mjcf.py](creature_lab/export/mjcf.py)) —
nested `<body>` tree, hinge `<joint>`, `<position>` servo actuators per motored joint, and
`<contact><exclude>` for parent/child pairs; verified to load in `mujoco.MjModel.from_xml_string`.
A `MuJoCoBackend` ([backends/mujoco_backend.py](creature_lab/backends/mujoco_backend.py)) that
implements `SimBackend`, builds the model from the MJCF exporter at runtime, steps via
`mj_step`, and reuses the shared `scoring` module (so both engines score the same way). URDF
export gained `<transmission>` blocks; a new best-effort `import_urdf`
([export/urdf_import.py](creature_lab/export/urdf_import.py)) parses box/sphere/cylinder links
and revolute/continuous/fixed joints, warning on (and skipping) meshes/sensors. CLI: `export-mjcf`,
`import-urdf`, and `run --backend {pybullet,mujoco}`; `doctor` reports the `mujoco` extra.
URDF export→import round-trips preserve part/joint structure exactly. 14 new tests (MuJoCo tests
skip when the extra is absent).

**Deviations from the plan:** (1) MotorSpec maps to MJCF `<position>` servos rather than plain
`<motor>` torque actuators — `<position>` mirrors Creature Lab's position-control model so the
exported model is actually drivable. (2) Added joint `damping`/`armature` and the `implicitfast`
integrator to the MJCF, without which MuJoCo's solver went to NaN on the light limbs. As the
portability promise predicts, PyBullet-tuned gaits don't reproduce their exact motion under
MuJoCo's different contact/actuator model — the backend runs stably and scores finitely, which
is the contract.

### Original Phase 8 plan

**Why:** This is the compatibility layer that lets Creature Lab creatures leave the
ecosystem and be used in serious robotics tools. But it is a bridge, not the center —
the authoring workflow stays in JSON, and export is an output, not an input.

**URDF export (fully flesh out from Phase 1 stub):**

- Add inertial properties computed from shape dimensions and mass.
- Add material/color blocks.
- Emit `<transmission>` blocks for actuated joints.
- Validate round-trip: export a creature to URDF, import URDF back (limited), compare
  joint structure.

**MJCF export** ([creature_lab/export/mjcf.py](creature_lab/export/mjcf.py)):

- Map `PartSpec` → MuJoCo `<geom>`.
- Map `JointSpec` → MuJoCo `<joint>`.
- Map `MotorSpec` → MuJoCo `<actuator><motor>`.
- Add a `<contact><exclude>` block for parent/child pairs (standard in MuJoCo MJCF).

**MuJoCo backend** ([creature_lab/backends/mujoco_backend.py](creature_lab/backends/mujoco_backend.py)):

- Implement `SimBackend` protocol.
- Use the MJCF exporter to build the model XML at runtime, load it into `mujoco.MjModel`.
- Map `step()` → `mujoco.mj_step()`.
- Add as `[tool.uv.extras] mujoco = ["mujoco"]`.

**Limited URDF import** ([creature_lab/export/urdf_import.py](creature_lab/export/urdf_import.py)):

- Parse `<link>` → `PartSpec` for simple geometries (box, sphere, cylinder).
- Parse `<joint>` → `JointSpec`.
- Skip materials, meshes, sensors — log a warning for unsupported elements.
- Goal: import MuJoCo Menagerie URDF files for simple robots (ant, hopper).

**New CLI commands:**

```bash
creature-lab export-urdf examples/tripod.json --out tripod.urdf
creature-lab export-mjcf examples/tripod.json --out tripod.xml
creature-lab import-urdf robot.urdf --out robot.json    # best-effort
creature-lab run examples/tripod.json --backend mujoco  # if mujoco extra installed
```

**Acceptance criteria:**

- `export-mjcf examples/tripod.json` produces XML that MuJoCo's `mujoco.MjModel.from_xml_string`
  accepts without error (test is gated on `mujoco` extra being installed).
- MuJoCo backend runs a 1-second episode and produces a trace.
- `import-urdf` can round-trip a simple URDF (export → import → compare joint count).
- `pytest` covers all export/import paths (MuJoCo tests skip when extra absent).

---

## What not to add (guard rails)

These items were in the prior plan's vague suggestions but belong to other products:

| Item | Why not |
|---|---|
| Multi-agent arena UI | That is Agentarium |
| Leaderboard / cloud execution | Product surface, not core tool |
| Photoreal rendering | Use a game engine instead |
| Generic object-building sandbox | Agentarium's territory |
| Natural language challenge descriptions | Agentarium has LLM challenge generation |
| Real-time LLM torque control | Too slow, too expensive, wrong abstraction level |
| Full web dashboard | Scope creep; the Viser viewer is enough for now |
| Beating Isaac Lab at scale | Wrong competition; different niche |

---

## Revised market position

After these 8 phases, Creature Lab occupies a specific niche that no current tool fills:

> **Creature Lab is the smallest tool that can take "I want a creature that walks"
> from zero to: a valid spec, a running simulation, a failure diagnosis, a co-evolved
> body+controller, and an exportable result — without writing URDF or code.**

Competitors and why they are not the same:

| Tool | What it does | Why Creature Lab is different |
|---|---|---|
| MuJoCo Menagerie | Curated model library | Fixed assets, no authoring/evolution loop |
| Evolution Gym | Co-design for soft voxel robots | Voxel-only, no articulated joints, no humanoids |
| Gymnasium-Robotics | Fixed RL benchmark environments | No morphology editing, no diagnosis |
| Isaac Lab | GPU-scale RL training | Heavy, needs NVIDIA hardware, no lightweight design loop |
| Webots | Full robot simulator | C/Python control API, not creature-design-first |
| Agentarium | Multi-agent challenge studio | Broad challenges, not creature-design depth |

---

## Revised roadmap summary

| Phase | Theme | Key commands added | Effort |
|---|---|---|---|
| 0 | Fix demo UX | `demo --creature` | Small |
| 1 | Scaffold commands | `scaffold`, `mirror-limb`, `export-urdf` | Medium |
| 2 | Creature Zoo | `zoo list`, `zoo run`, `zoo validate-all` | Medium |
| 3 | Failure diagnosis | `diagnose` | Medium |
| 4 | Gymnasium control loop | `run --controller`, `CreatureEnv` | Large |
| 5 | Debug viewer overlays | `view --debug`, `compare`, `plot` | Medium |
| 6 | Humanoid kit | `scaffold humanoid`, humanoid zoo entries | Medium |
| 7 | Evolution improvements | `evolve --strategy map_elites`, `lineage` | Large |
| 8 | Export/import bridge | `export-mjcf`, `import-urdf`, `--backend mujoco` | Large |

Start at Phase 0. Each phase is independently shippable. Each phase's acceptance criteria
are the gate to starting the next.
