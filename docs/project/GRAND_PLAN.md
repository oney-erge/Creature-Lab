# Creature Lab — Grand Plan (single source of truth)

**Status:** 0.2 implementation complete; future work is evidence-led. This document supersedes the three drafts in `docs/archive/some-plans/`
(final roadmap, streamlined controller roadmap, UI/UX plan) and the completed
[`IMPROVEMENT_PLAN_2026.md`](../archive/IMPROVEMENT_PLAN_2026.md). When those disagree with this
file, this file wins. Keep **one** active roadmap.

## 0.2 delivery summary

The hardening/adoption pass is complete in the working tree:

- **Trust:** finite/path-contained schemas, task-aware qualification, exact controller/policy
  snapshots, atomic run files, version-2 verified packs, and reproducible report commands.
- **Editor:** conflict-safe autosave, transactional reload, rotated nested transforms, draggable
  task targets, cooperative job shutdown, and real-browser process cleanup.
- **First result:** `curated` is the default showcase controller; promoted Zoo entries have
  executable score/fall contracts; unstable entries are labeled challenges.
- **Differentiator:** `autopsy` attributes controller/body-task/fragility/backend failures and
  emits a report plus reproducible pack; the Failure Zoo supplies intentional examples.
- **Release readiness:** version 0.2.0 metadata, Linux/Windows/macOS CI, browser CI, clean-wheel
  smoke, and a manual verified-artifact release workflow.

The older phase narratives below remain as implementation history. Statements that something is
"deferred" there are superseded by this summary and the current CLI reference when the feature
now exists.

---

## 1. What Creature Lab is (say it in one breath)

> **Creature Lab is a failure-first, local workbench for reproducible robot morphology
> experiments.** It determines whether a failure came from the body, controller, task,
> fragility, or simulator—without requiring URDF or simulator code.

The loop, and the whole product, is:

```text
Design → Run → Autopsy → Improve → Verify → Share
```

That sentence is the product. Every screen, command, and doc should make *that* loop obvious
before it shows anything else.

### What it is **not** (hard boundaries, agreed by all three source plans)

Creature Lab is deliberately *not* AgentGymnasium and not a simulation platform. Do **not** add:
multi-agent arenas, agent personas/memory, generic agent orchestration, challenge-generation
chat, world-building systems, leaderboards, cloud execution, hosted dashboards, real-time LLM
motor control, GPU-scale RL infrastructure, or a second frontend framework. An optional LLM may
*edit designs between simulations*; it must never drive the robot at simulation frequency.

---

## 2. The core problem this plan fixes

The engine is strong; the **product is confusing**. Concretely, today:

1. **The repo tells three different stories.** Overlapping roadmaps and three unmerged plan
   drafts make it unclear what Creature Lab *is* and what to do next. → Fixed by this document
   plus doc cleanup (Phase 0, done).
2. **The editor is a vertical folder wall.** `Start / Body / Selected part / Motion / Run /
   Metrics / Robustness` stacked in one narrow panel, basic and advanced controls mixed, raw
   file paths shown before you have a creature.
3. **Editing is fragile.** No undo/redo, no snapshots, delete/template-replace are one-click and
   unrecoverable, and every slider change rebuilds whole UI folders *and* the entire 3D scene.
4. **Running blocks everything.** Simulation runs on the UI thread and immediately plays back;
   no progress, no cancel, no scrubber, results shown as raw Markdown.
5. **A "target" doesn't steer the robot.** Tasks can score a target, but the built-in gaits
   (`sinusoid`, `cpg`) are open-loop and never turn toward it. `CreatureEnv` has the closed-loop
   substrate (observations, actions, target vector) but the normal `run`/editor path bypasses it.

Priorities below are ordered by *how much confusion they remove per unit of work*, which is why
UX and de-confusion come before the controller architecture.

---

## 3. How the three source plans were reconciled

| Question | Final roadmap | Controller roadmap | UI/UX plan | **Decision** |
| --- | --- | --- | --- | --- |
| Product name | "Robot Morphology Workbench" | "Git-native design debugger & qualification lab" | "creature-design workbench" | **Keep "Creature Lab."** Describe it in plain words (§1). No jargon rename. |
| Editor structure | Design/Diagnose/Improve | Build/Movement/Task/Run/Diagnose/Qualify/Export (7 tabs) | Design/Motion/Test (3 phases) | **Design / Motion / Test** (3 Python-owned phases). The extra concepts live *inside* Test. |
| Biggest lever | Adoption + guided mode | Controller architecture | Editor UX | **Editor UX + de-confusion first**, controller architecture second. The user's pain is clarity, not steering. |
| Controller work | "fix offline `ask`", real Gymnasium | Full `ControllerSpec`, target-seek, posture, qualify, autopsy | (mostly out of scope) | **Stage it.** Land the target-seeking controller and a shared runner as a *later* phase, not a big-bang rewrite. |
| Qualification | — | Flagship `qualify` feature | — | **Keep, but later.** Don't advertise "qualification lab" until `qualify` exists. |

Everything all three plans agree on — tabs, basic/advanced modes, undo/redo/snapshots, async
simulation with progress+cancel, playback separated from simulation, actionable diagnosis, run
history, incremental preview, a visual scorecard, and the AgentGymnasium boundary — is adopted
wholesale and is the backbone of Phases 1–2 below.

---

## 4. What already exists (don't rebuild it)

A large amount of the source plans is **already implemented**. Recorded here so no one re-proposes it:

- Portable `CreatureSpec` / `TaskSpec` / `EpisodeTrace` JSON; hashing and run manifests.
- PyBullet **and** MuJoCo backends behind one adapter contract.
- Controllers package: `sinusoid`, `cpg` (coupled oscillators), plus `pid` and `pose_seq`
  building blocks.
- `CreatureEnv`: a step-by-step `reset()/step()` loop with `ObservationSpec` / `ActionSpec`,
  position/velocity/torque modes, and an optional **target-vector observation**.
- Diagnosis, robustness sweeps, sim-to-sim gap, evolution (4 strategies), MAP-Elites archive.
- HTML + Markdown reports, GIF/MP4 export, URDF/MJCF export, best-effort URDF import.
- A Viser build editor with live 3D preview, part selection, body/part/motor editing, validation,
  simulate, robustness, and live project file-sync.
- Curated zoo, benchmarks with per-backend baselines, `doctor`, wheel install-tested in CI.

The gap is **product layer**, not simulation surface area.

---

## 5. Phased roadmap

### Phase 0 — De-confuse the repo ✅ (this change)

- One authoritative roadmap (this file); the three drafts archived under
  `docs/archive/some-plans/`; `ROADMAP.md` reduced to a pointer; `IMPROVEMENT_PLAN_2026.md`
  banner-marked *Completed*.
- README leads with the plain-language "what is this" and the `Design → Move → Test → Understand
  → Improve` loop.

**Done when:** a newcomer reading the README and this file can state what Creature Lab is and
what to do next, and no two docs claim to be "the plan."

### Phase 1 — Editor foundation: safe, reversible, legible ✅

Landed in the pure `EditorSession`/`editor/history.py`/`editor/jobs.py`/`editor/playback.py`
layer first (fully unit-testable, no GUI), then wired into Viser (`editor/controls.py`,
`editor/live.py`).

- **Undo / redo / snapshots**: atomic history entries, named checkpoints, reset-to-template,
  dirty-state tracking (`EditorHistory`, `EditorSession`).
- **Basic / Advanced mode** as session state; Basic shows only the controls needed for a first
  successful experiment.
- **Safe destructive actions:** the session exposes the exact delete impact; the UI requires
  confirmation before delete / reload-with-unsaved-edits.
- **Design / Motion / Test phases** replace the folder wall; Open/Save/Import/Export live in a
  Project section; a persistent History section holds Undo/Redo/Reset/Snapshots.
- **Incremental preview** (`EditorPreview.refresh_overlays`): selecting a part only redraws the
  selection gizmo/CoM/support-width overlay, not the whole scene; picking a motor triggers no
  scene update at all. Structural edits (add/delete/mirror/template/undo/redo) still do a full
  rebuild, since topology can change.
- **Async simulation and robustness** (`EditorJobManager`): both run on a background thread with
  a live progress bar, elapsed time, and a Cancel button; the panel never blocks. `_simulate`
  and `robustness.run_trials` grew optional `on_step`/`should_stop` hooks (backward compatible)
  so a job can report progress and cooperatively cancel between physics steps/trials.
- **Playback separated from simulation** (`EditorPlayback`): a finished run loads into a
  Play/Pause + frame-scrubber + step +1/-1 + restart panel instead of auto-replaying inline.
- **Visual scorecard**: the Result panel leads with a score/displacement/fell/duration headline,
  followed by severity-tagged diagnosis cards (see Phase 2).

**Done when:** a beginner can pick a preset, tune it, simulate, read a visual result, and undo
any mistake — without seeing a file path or a raw phase value, and without the UI freezing. ✅

### Phase 2 — Guided design + actionable diagnosis (shipped subset)

Shipped:

- **First-run onboarding**: a *choose a creature* × *choose a goal* modal on a fresh `build`
  launch (goals: move forward / reach a target / stay balanced — backed by the task presets that
  already exist; climb/step/cross-gap goals are deferred until those task presets are exposed in
  the editor, see below).
- **Human-readable part labels** (`editor/labels.py`) and a part **hierarchy tree** (indented
  markdown, selected part bolded) shown above the part selector. The tree is currently
  display-only; selection still happens via the dropdown or clicking the part in 3D.
- **Actionable diagnosis**: each pattern shows *what happened · why · evidence · severity*, and
  patterns with a safe, bounded, deterministic fix (scale motor amplitude/frequency, reverse
  gait, apply a named gait preset, widen stance) get an **Apply fix** button — one undo step,
  re-simulate manually afterward. Not every pattern has an automatic fix (e.g.
  `no_ground_contact` needs geometry knowledge this can't guess); those still show the
  suggestion text only.
- **Integrated run history**: the Test phase lists recent saved runs (score/task/backend/age) with
  **Restore design** (undoable) and **Replay** (loads the trace into Playback) actions.
- **Simplified robustness**: Basic mode offers Quick/Standard/Thorough (5/10/25 trials); the
  result includes a plain-language verdict ("Robust", "Moderately robust", "Fragile") ahead of
  the raw numbers.

Deferred (real, but lower value per effort than the above, and riskier to get right without a
browser to iterate against): guided limb creation with a ghost preview, a visual phase-circle
gait composer, a kinematic (pre-physics) motion preview, and an explicit before/after comparison
view (run history covers restore/replay; a dedicated score-delta/overlay comparison does not
exist yet — reuse the existing `compare --html` CLI infrastructure in the meantime).

### Phase 3 — Make the target actually steer ✅ (shipped subset)

Staged, not big-bang, and scoped to what actually moves the "Done when" bar rather than a full
`ControllerSpec`/`CreatureEnv`-unification rewrite:

- **`TargetSeekController`** (`creature_lab/controllers/target_seek.py`): wraps the existing CPG
  with deterministic heading-error steering (body-frame target vector, differential left/right
  amplitude modulation by joint-id suffix), distance-based speed scaling, and a stop radius
  (defaults to the target's own radius). No learned model, no LLM — pure trigonometry over the
  previous frame's root pose. Verified with real-physics scenario tests (target ahead/left/right,
  stop radius, determinism) on **both PyBullet and MuJoCo** — see
  `tests/test_controllers.py` and `tests/test_mjcf_mujoco.py`. (MuJoCo's default MJCF actuator
  export makes `generate_quadruped()` a much weaker walker than PyBullet for the same gait — a
  pre-existing backend characteristic, not a controller bug, tracked in `KNOWN_ISSUES.md` — so
  the MuJoCo coverage checks the steering *math* directly plus determinism, rather than a full
  physical scenario.)
- **`--controller target_seek`** works everywhere the existing `--controller sinusoid|cpg` flag
  already did: `run`, `build`, `bench`, `robustness`, `sim2sim`, `qualify` — all route through the
  same `cli._make_controller`/`_simulate`, so this was additive, not a parallel path. (`evolve`
  has no `--controller` flag at all — its `--mutate controller` tunes the body's own `MotorSpec`
  gait parameters, a different, unrelated thing. An earlier version of this doc incorrectly
  listed `evolve` here.) A missing target now reports a clean CLI error (fixed a pre-existing bug
  along the way: raising `typer.BadParameter` from inside `_simulate` rather than a parameter
  callback exited silently with no message — and the *editor's* equivalent case, picking
  `target_seek` with a target-less task, is now caught by `EditorSession.status()` before
  Simulate is even enabled, rather than surfacing as a blank "Failed: " after a round-trip
  through the async job).
- **Editor**: a **Controller** dropdown in the Test phase's Run section
  (`EditorSession.controller`/`set_controller`, not undoable — it's a run setting, not part of
  the saved design) flows through `editor/live.py`'s async simulate/robustness jobs into real
  physics. Validated end-to-end against a live Viser server with real PyBullet.
- **Diagnosis**: a new `target_not_approached` pattern (task has a target, but net progress
  toward it is ~0) with a bounded Apply-fix (switch to `target_seek`).

Deferred: routing everything through one `CreatureEnv`-based shared runner (the CLI's existing
raw-backend-loop path and `CreatureEnv` already produce equivalent traces from the same backend
calls, so this would be an internal architecture cleanup, not a behavior change), posture/balance
PD control, and per-actuator force/torque/velocity limits with saturation recording. None of
these block the steering behavior itself; revisit if/when actuator realism becomes the active
need. (The portable `ControllerSpec` JSON artifact and `controller extract`/`controller scaffold`
commands, listed as deferred here in an earlier version of this doc, shipped in the Phase 4.5
audit pass below.)

**Done when:** a packaged quadruped set to `target_seek` visibly steers to targets ahead / left /
right and stops within the radius, deterministically, on both backends. ✅ — verified via
`run --controller target_seek`, the editor's live Controller dropdown, and real-physics scenario
tests on PyBullet; MuJoCo verified at the controller-math level per the note above.

### Phase 4 — Qualify + release trust (qualify shipped; release/CLI-split deferred)

- **`qualify`** (`creature_lab/qualification.py` + `creature-lab qualify`) combines a baseline
  run, a robustness sweep, and — for the `backend-portable` profile, or `--check-portability` —
  a cross-backend comparison into one pass/fail result with a named **primary blocker** and a
  recommended next test. Built-in profiles: `basic-locomotion`, `target-reach`, `push-recovery`,
  `backend-portable`. `--json` for machine-readable output. Composes `robustness.run_trials` and
  the same `_simulate` path `sim2sim` uses, rather than being a new isolated feature.
  Task-completion-time and actuator-saturation checks from the original sketch are omitted — the
  engine doesn't currently record either signal reliably (no actuator-saturation tracking exists
  yet, and there's no "stop early on success" concept), so a check would be fake precision rather
  than a real signal. Add them if/when Phase 3's deferred actuator-realism work lands.
- **Not done, and not something an agent session can do:** publishing `0.2.0` to PyPI (needs a
  maintainer with real credentials — this was already noted as out of scope in the pre-Phase-0
  `docs/ROADMAP.md`). Multi-OS CI, static versioned docs, and a refreshed demo GIF are real,
  buildable work that simply wasn't the highest-value use of this session relative to `qualify`
  and Phase 3's steering gap — worth a dedicated pass.
- **Not done:** splitting the ~2200-line CLI into command modules, and structured logging. Both
  are mechanical-but-risky refactors of a large, working, well-tested file for a maintainability
  win rather than a user-facing one — better done as their own focused change with nothing else
  in flight, not bundled into a session that already touched `cli.py` extensively for Phase 3/4.

### Phase 4.5 — Audit pass: bugs, gaps, and the ControllerSpec/design-pack extension ✅

A full re-read of Phases 1–4 against the running code (not memory), followed by fixing every real
bug and gap it found, plus the highest-value item from Phase 3/4's deferred lists.

Bugs fixed:

- **`fell` no longer depends on `task.reward.fall_penalty`.** `summarize_episode`'s `fell` used to
  read `trace.meta.score_summary["fall"] < 0`, which is silently `None`/wrong on any task that
  doesn't configure a fall penalty (most of the zoo). It's now orientation-based
  (`diagnosis.is_upright`/`first_fall_time`, root-part quaternion, reward-independent) whenever a
  `creature` is available — `qualify`, `robustness`, the editor, and `inspect` all pass one now.
  This was the most consequential bug found: a robustness/qualify pass could report 0% fail rate
  on a creature that was visibly toppling every trial.
- **Editor: `target_seek` without a target no longer fails with a blank "Failed: " message.**
  `EditorSession.status()` now reports the missing-target error (and a warning when the creature
  has no `l`/`r`-suffixed motored joint for `target_seek` to steer with) *before* Simulate is even
  enabled, instead of surfacing a stripped-empty exception message after a round-trip through the
  async job. `EditorJobManager` also gained a defensive fallback (`type(exc).__name__ ...`) for
  any future exception whose `str()` is empty.
- **`qualify`'s `target-reach`/`push-recovery` profiles now check task compatibility first.**
  Running `target-reach` against a target-less task (or `push-recovery` against a task with no
  damage/impulse event) used to run a full physics baseline and then fail confusingly on "target
  progress" with no target to progress toward. A new "Task setup" check short-circuits before any
  physics runs, with a clear message.
- **`list_recent_runs` no longer fully validates every trace.** The editor's Run History panel
  only needs 5 scalar fields per run; it was constructing full `EpisodeTrace`/`FrameState`/
  `PartPose` pydantic models (every recorded frame) just to list 8 rows. Now reads the same 5
  fields via `json.loads` + dict access.
- Corrected a stale doc claim (this file, `CHANGELOG.md`, `docs/CLI_REFERENCE.md`) that `evolve`
  supports `--controller target_seek` — it doesn't; `evolve --mutate controller` is a different,
  unrelated body-gait mutator.

Shipped, from Phase 3/4's deferred lists:

- **`ControllerSpec`** (`creature_lab/schema/controller.py`): the fourth portable JSON artifact
  alongside creature/task/trace — `type` (`sinusoid`/`cpg`/`target_seek`) plus type-specific
  tuning fields, unset fields falling back to that controller's own built-in defaults.
  `creature_lab/controllers/factory.py`'s `build_controller` turns a spec into a runtime
  controller callable; `extract_sinusoid_spec` migrates a creature's own `MotorSpec` gait into
  one. `--controller` now also accepts a path to a `controller.json` everywhere it already
  accepted a built-in name (`run`, `bench`, `robustness`, `sim2sim`, `qualify` — not `build`,
  whose Controller dropdown only offers the three names), and a new `controller` command group
  (`scaffold`, `extract`, `validate`) authors and checks them.
  `TraceMeta.controller` now records which controller produced a run (name or `.json` path), so a
  saved run is fully self-describing.
- **`creature-lab export-pack`** (`creature_lab/exporting.py`): bundles a run's creature, task,
  controller (reconstructed from `trace.meta.controller`, exact for built-ins and still-present
  `.json` paths, a flagged best-effort sinusoid extraction otherwise), and trace into one portable
  directory plus a `manifest.json` with reproducibility hashes — the "save controller.json /
  trace / manifest" half of this file's §7 definition of done.
- **Qualify in the editor**: a **Qualify** panel in the Test phase (`docs/BUILD_EDITOR.md`) runs the
  same `qualification.qualify()` as the CLI command, as a cancellable background job, against the
  in-editor creature/task without saving a run first.

**Done when:** every bug found in the audit has a regression test proving it's fixed, and the
Phase 3/4 deferred items judged highest-value (a portable controller artifact + design-pack
export) are shipped with the same real-physics verification rigor as the rest of this plan. ✅

### Phase 5 — Capability: gaits and control that actually work (Tiers 1, 2, 3 shipped)

Everything through Phase 4.5 makes the *tooling* around a creature strong — portable specs, two
backends, the editor, diagnosis, robustness, qualify, reports. What stayed thin was the
**creature's actual capability**: every built-in gait is open-loop (it never senses and
corrects), the improve loop's gait search was buried and its output was never saved as a reusable
artifact or shipped as a better default, and the closed-loop substrate (`CreatureEnv`) existed
with nobody driving it. The result at the time was a first run that shuffled ~1 m and a humanoid
that fell over in about a second, regardless of how good the rest of the product was. A follow-up
audit later found that the humanoid measurement was confounded by a PyBullet tree-order bug and
incorrect body/actuator defaults; the corrected result is documented after the tier history. This phase was the direct
answer to that, staged by what a real, working payoff requires:

- **Tier 1 — Optimize the gait (shipped ✅).** `creature-lab optimize <creature> --task <task>`
  runs the existing `evolve --strategy cmaes` search (motor amplitude/frequency/phase; morphology
  untouched) and saves the result as a portable `controller.json`
  (`creature_lab/controllers/factory.extract_sinusoid_spec`) instead of a throwaway evolved
  creature file. Measured, not assumed: **quadruped 0.57 → 1.97 (3.4x)**, **hexapod 0.54 → 1.68
  (3.1x)**, **worm 0.93 → 1.51 (1.6x)**, and **tripod −0.68 → 0.94** (its default gait was
  actually net-negative — worse than standing still — and optimization fixes that outright), all
  in ~100 CMA-ES evaluations (a couple of CPU-minutes). Every zoo locomotion creature (quadruped,
  hexapod, tripod, worm) now ships this as an additive `controller.json` alongside its unchanged
  `creature.json` — `zoo run <name> --controller optimized` opts in; nothing about the existing
  baked-in gait, regression baselines, or default behavior changed, so this is zero-risk to
  existing workflows. `zoo list` shows which creatures have one. At this stage the humanoid did
  not get one; that conclusion was superseded by the correction note below.
- **Tier 2 — Closed-loop balance (shipped ✅).** `PostureController`
  (`creature_lab/controllers/posture.py`, `--controller posture`) reads the previous frame's root
  orientation and applies PD feedback to correct forward/backward lean, instead of blindly playing
  a waveform — the same "read prev_frame, correct this step" pattern `target_seek` already uses
  for steering, now doing balance. This is what actually answers "the humanoid can't walk": Phase
  4.5's audit proved *any* nonzero open-loop gait topples it in under 3.3s regardless of stance or
  CoM tuning — no amount of gait optimization fixes a structural balance problem, only feedback
  does. Measured, not assumed: a static (uncorrected) stance falls at ~2.0s under a 400N forward
  push; with `PostureController`'s default gains it survives forward *and* backward pushes up to
  1200N and 8s of standing with no push at all, with only mild positional drift, never falling.
  Honest scope limit, found the same way: every hip/knee/ankle hinge this codebase generates is
  sagittal-only (`axis=[0,1,0]`) — there is no side-to-side (roll) balance joint anywhere, on any
  creature, so this controller structurally cannot correct sideways tipping. It measurably does
  not need to for the packaged lateral `push_recovery` impulse (passive stance already survives
  it), but a stronger lateral push still topples the creature regardless. See
  `docs/KNOWN_ISSUES.md` for the exact numbers and what a real fix would need (a new hip
  ab/adduction joint).
- **Tier 3 — Learned locomotion (shipped ✅, deliberately scoped honestly).** `creature-lab train
  <creature> --task <task>` (new optional `rl` extra: gymnasium + Stable-Baselines3 + torch)
  trains a real PPO policy and saves it as a `policy`-type `ControllerSpec` (a `controller.json` +
  a sibling `policy.zip` bundle, the same "artifact travels as a small directory" pattern
  `export-pack` already established). `CreatureEnv` itself was **not** changed - its
  `step()`/`reset()` are an older, already-tested 4-tuple/plain-obs API real callers depend on
  (`tests/test_env.py`) - instead a new `CreatureGymEnv` (`creature_lab/rl/gym_env.py`) wraps it
  as a real `gymnasium.Env` (proper `Box` spaces, split `terminated`/`truncated`), verified against
  gymnasium's own `check_env` compliance checker, not just "it runs." `PolicyController`
  (`creature_lab/controllers/policy.py`) then drives a loaded policy through the same
  `(t, prev_frame) -> targets` interface every other controller uses, so a trained policy composes
  with `run`/`qualify`/`robustness`/the editor exactly like `sinusoid`/`posture` do - it reuses
  `CreatureEnv`'s own (pure, backend-untouched) observation/action translation methods rather than
  duplicating that math. Measured, not assumed: a 100,000-timestep PPO run on the quadruped
  (~110s wall-clock) reached a mean episodic return **1.46-2.06x** a random baseline on the same
  env/eval seeds (two independent runs, direct-function and full-CLI). Scoped honestly, stated
  up front in the command's own help text: this is a working training loop with a measured
  positive result, not a promise of a polished walker — genuinely good learned bipedal walking is
  a real research problem, not a short-training-run outcome, and was not attempted with PPO here.

**Done when:** the zoo's default first impression is a well-coordinated gait, not a shuffle
(Tier 1 ✅); the humanoid can stay upright and resist a push instead of falling within a second
(Tier 2 ✅); and at
least one creature has visibly learned locomotion through `CreatureEnv` rather than had it
hand-tuned (Tier 3 ✅ — quadruped, measured 1.46-2.06x over random; bipedal walking remains future
work, not attempted by the RL tier).

#### Follow-up correction — a scoped humanoid walker

A deeper audit found that PyBullet link identities on branched, multi-level bodies had been
recorded in breadth-first order while the engine exposed them depth-first. The supposed humanoid
joint/contact evidence was therefore not trustworthy. After fixing that invariant, adding
horizontal feet, normalizing requested mass, allowing per-motor torque and gait center offsets,
and retuning, the packaged `humanoid_12dof` moves about **0.417 m in 5 s without falling** on
PyBullet and remains upright for a measured 30 s run. It is a slow open-loop stepping/shuffling
experiment with alternating foot contacts—not a polished or learned dynamic walker. The gait is
backend-specific (upright but slightly backward on MuJoCo) and eventually drifts laterally because
the body lacks hip roll DOFs. The editor uses this exact packaged controller when its body matches,
and its Back to Design action now pauses playback and restores the editable pose.

---

## 6. Explicitly deferred / out of scope for now

Real but later, and never at the cost of the core loop: waypoint & contact-adaptive controllers
beyond Phase 5's balance/posture and RL work, external (non-`CreatureEnv`) learned-policy
adapters, hardware-feasibility packs, MJCF import, a Creature Lab GitHub Action, the Failure Zoo
teaching set.

---

## 7. Definition of done for the whole plan

A new user can: install the package → open the editor → pick a creature preset → choose *Move to
target* → drag a target → run → watch it steer → get a body/controller-specific failure
explanation → preview/apply a bounded fix → run robustness + sim-to-sim → get a qualification
pass/fail → save `creature.json` / `task.json` / `controller.json` / trace / manifest / HTML
report → and reproduce it with one command. At that point Creature Lab is a coherent
design-diagnose-improve tool, not a body editor bolted to an oscillator.
