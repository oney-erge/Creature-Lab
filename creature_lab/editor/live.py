"""Live Viser build editor."""

from __future__ import annotations

import time
import webbrowser
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from creature_lab.diagnostics import summarize_episode
from creature_lab.editor.controls import BuildControls
from creature_lab.editor.jobs import EditorJobManager, JobCancelled, ProgressReporter
from creature_lab.editor.playback import EditorPlayback
from creature_lab.editor.session import EditorSession
from creature_lab.qualification import BUILTIN_PROFILES, QualificationResult
from creature_lab.qualification import qualify as run_qualify
from creature_lab.robustness import RobustnessResult, run_trials
from creature_lab.runs import DEFAULT_RUNS_DIR, load_trace, save_run
from creature_lab.schema import CreatureSpec, EpisodeTrace, FrameState, TaskSpec
from creature_lab.viewers.viser_viewer import (
    DEFAULT_HOST,
    apply_frame,
    build_scene,
    creature_reach,
    remove_scene,
)

#: (creature, task, *, on_step=None, should_stop=None) -> EpisodeTrace. The keyword
#: hooks are optional so any plain ``(creature, task) -> EpisodeTrace`` callable still
#: works; only the async job wiring in this module uses them.
SimulateFn = Callable[..., EpisodeTrace]

#: Re-frame the camera automatically only when the creature's scale changes by more
#: than this fraction (template swap, add/delete limb, ...) - a single slider drag
#: shouldn't yank the camera around. ``frame_camera`` always reframes regardless.
_REFRAME_THRESHOLD = 0.15


class EditorPreview:
    """3D preview scene for the current editor session."""

    def __init__(
        self,
        server: Any,
        session: EditorSession,
        *,
        on_select: Callable[[str], None],
        on_change: Callable[[], None],
    ) -> None:
        self.server = server
        self.session = session
        self.on_select = on_select
        self.on_change = on_change
        self._handles = None
        self._editor_overlays: list[Any] = []
        self._framed_reach: float | None = None

    def refresh(self) -> None:
        """Full rebuild: tear down and recreate every part, the floor, and overlays.

        Needed whenever the creature's *structure* changed (template swap, add/
        delete/mirror limb, body-param resize, load/reload, undo/redo - any of these
        can change part count, shape, or dimensions). Not needed for a pure selection
        change - see ``refresh_overlays`` for the cheap path used there.
        """
        self._remove_overlays()
        remove_scene(self._handles)
        self._handles = build_scene(self.server, self.session.creature, self.session.task)
        for part_id, handle in self._handles.parts.items():
            handle.on_click(lambda _event, part_id=part_id: self.on_select(part_id))
        frame = self.session.preview_frame()
        apply_frame(self._handles, frame)
        self._add_editor_overlays(frame)
        self._maybe_reframe_camera()

    def _maybe_reframe_camera(self) -> None:
        """Re-frame only when the creature's scale changed enough to matter.

        Without any camera framing at all, a ~0.4 m creature rendered as a
        barely-visible speck against Viser's default camera (see
        docs/KNOWN_ISSUES.md). Gating on a relative-size threshold means a
        template swap (quadruped -> humanoid) reframes automatically, but
        nudging a single body slider mid-edit does not yank the camera around.
        """
        reach = creature_reach(self.session.creature)
        previous = self._framed_reach
        if previous is None or abs(reach - previous) / previous > _REFRAME_THRESHOLD:
            self.frame_camera(reach)

    def frame_camera(self, reach: float | None = None) -> None:
        """Point the camera at the creature from a comfortable isometric distance.

        Sets both ``initial_camera`` (for clients connecting after this call) and
        every already-connected client's live camera, since the editor's browser
        tab is usually already open when a template switch or an explicit
        **Frame creature** click happens.
        """
        if reach is None:
            reach = creature_reach(self.session.creature)
        self._framed_reach = reach
        distance = reach * 2.2
        look_at = (0.0, 0.0, reach * 0.35)
        position = (
            look_at[0] + distance * 0.7,
            look_at[1] - distance * 0.7,
            look_at[2] + distance * 0.55,
        )
        self.server.initial_camera.position = position
        self.server.initial_camera.look_at = look_at
        for client in self.server.get_clients().values():
            client.camera.position = position
            client.camera.look_at = look_at

    def refresh_overlays(self) -> None:
        """Redraw only the selection gizmo/CoM/support-width overlays.

        Used when the selected part changes but no geometry did (see
        ``BuildControls``'s "light" preview mode): part meshes, the floor, and the
        contact-marker pool are left untouched, so this is far cheaper than
        ``refresh`` and doesn't disturb anything the client already rendered.
        """
        if self._handles is None:
            self.refresh()
            return
        self._remove_overlays()
        frame = self.session.preview_frame()
        self._add_editor_overlays(frame)

    def _remove_overlays(self) -> None:
        for extra in self._editor_overlays:
            try:
                extra.remove()
            except Exception:
                pass
        self._editor_overlays = []

    def apply_playback_frame(self, frame: FrameState) -> None:
        """Push one trace frame to the scene without touching GUI state or the camera.

        Called every tick while playback is running/scrubbing (see
        ``BuildControls.tick``) - this must stay cheap since it can run at ~30 Hz.
        """
        if self._handles is not None:
            apply_frame(self._handles, frame)

    def _add_editor_overlays(self, frame) -> None:
        if self._handles is None:
            return
        selected = frame.parts.get(self.session.selected_part_id)
        if selected is not None:
            marker = self.server.scene.add_frame(
                "/editor/selected",
                axes_length=0.16,
                axes_radius=0.008,
                origin_radius=0.025,
                position=selected.position,
            )
            self._editor_overlays.append(marker)
            has_parent_joint = any(
                joint.child == self.session.selected_part_id
                for joint in self.session.creature.joints
            )
            if has_parent_joint:
                gizmo = self.server.scene.add_transform_controls(
                    "/editor/anchor_gizmo",
                    scale=0.25,
                    disable_rotations=True,
                    position=selected.position,
                )
                gizmo.on_drag_end(lambda event: self._move_selected_anchor(event.target.position))
                self._editor_overlays.append(gizmo)
        if self.session.task.target is not None:
            target_gizmo = self.server.scene.add_transform_controls(
                "/editor/target_gizmo",
                scale=0.35,
                disable_rotations=True,
                position=self.session.task.target.position,
            )
            target_gizmo.on_drag_end(lambda event: self._move_target(tuple(event.target.position)))
            self._editor_overlays.append(target_gizmo)
        metrics = self.session.preview_metrics()
        com = self.server.scene.add_icosphere(
            "/editor/com",
            radius=0.035,
            color=(30, 220, 140),
            position=(metrics["com_x"], metrics["com_y"], metrics["com_z"]),
        )
        self._editor_overlays.append(com)
        support = metrics["support_width"]
        if support > 0:
            points = np.asarray(
                [[0.0, -support / 2, 0.015], [0.0, support / 2, 0.015]],
                dtype=np.float32,
            )
            line = self.server.scene.add_line_segments(
                "/editor/support_width",
                points=points.reshape(1, 2, 3),
                colors=(30, 220, 140),
                line_width=3,
            )
            self._editor_overlays.append(line)

    def _move_selected_anchor(self, position: tuple[float, float, float]) -> None:
        self.session.move_selected_anchor_to(tuple(float(value) for value in position))
        self.session.autosave()
        self.refresh()
        self.on_change()

    def _move_target(self, position: tuple[float, float, float]) -> None:
        self.session.set_target_position(tuple(float(value) for value in position))
        self.session.autosave()
        self.refresh()
        self.on_change()


def run_editor(
    session: EditorSession,
    *,
    simulate: SimulateFn,
    simulate_other_backend: SimulateFn | None = None,
    host: str = DEFAULT_HOST,
    port: int = 8080,
    open_browser: bool = False,
    runs_dir: Path = DEFAULT_RUNS_DIR,
    show_onboarding: bool = False,
) -> None:
    """Start the Viser build editor and block until interrupted.

    ``show_onboarding`` opens the first-run creature x goal picker before the main
    panel is usable; callers that already loaded a specific creature (``--project``,
    a positional path) should leave it off. ``simulate_other_backend``, when given,
    powers the Qualify panel's backend-portable check (see cli.py's ``build``
    command); without it, that check is simply skipped, same as the CLI's `qualify`
    without a second backend.
    """
    import viser

    server = viser.ViserServer(host=host, port=port)
    server.gui.configure_theme(
        control_layout="fixed",
        control_width="large",
        show_logo=False,
        show_share_button=False,
    )
    if open_browser:
        webbrowser.open(f"http://localhost:{port}", new=2)

    def notify(title: str, body: str, color: str) -> None:
        """Broadcast a notification to every connected browser tab.

        Notifications are per-client in Viser (there is no server-wide
        broadcast call), so this fans out over ``get_clients()``. Editor state
        is otherwise server-global (see docs/BUILD_EDITOR.md) - a second tab
        would silently share the same session, so at least the outcome of a
        run is visible everywhere the panel is open.
        """
        for client in server.get_clients().values():
            client.add_notification(title, body, color=color, auto_close_seconds=8.0)

    controls_holder: dict[str, BuildControls] = {}

    def select_part(part_id: str) -> None:
        controls_holder["controls"].scene_selected(part_id)

    def scene_changed() -> None:
        controls = controls_holder.get("controls")
        if controls is not None:
            controls.scene_changed()

    preview = EditorPreview(server, session, on_select=select_part, on_change=scene_changed)

    job_manager = EditorJobManager()
    playback = EditorPlayback()

    def start_simulate_job() -> None:
        # Snapshot now: pydantic models here are always *replaced*, never mutated in
        # place (see EditorSession), so further edits to the live session while this
        # job runs in the background cannot corrupt what's being simulated.
        creature = session.creature
        task_for_run = session.task
        controller = session.controller

        def work(reporter: ProgressReporter) -> tuple[EpisodeTrace, Path]:
            def on_step(done: int, total: int) -> None:
                reporter.report(done / total if total else 1.0, f"{done}/{total} steps")

            try:
                trace = simulate(
                    creature,
                    task_for_run,
                    controller=controller,
                    on_step=on_step,
                    should_stop=lambda: reporter.cancel_requested,
                )
            except Exception:
                if reporter.cancel_requested:
                    raise JobCancelled from None
                raise
            reporter.check_cancelled()
            run_dir = save_run(creature, trace, runs_dir=runs_dir, task=task_for_run)
            return trace, run_dir

        if not job_manager.start(work):
            session.last_message = "A job is already running."

    def start_robustness_job(trials: int, mass_jitter: float, friction_jitter: float) -> None:
        creature = session.creature
        task_for_run = session.task
        controller = session.controller

        def work(reporter: ProgressReporter) -> RobustnessResult:
            def evaluate(trial_creature: CreatureSpec, trial_task: TaskSpec) -> tuple[float, bool]:
                trace = simulate(
                    trial_creature,
                    trial_task,
                    controller=controller,
                    should_stop=lambda: reporter.cancel_requested,
                )
                reporter.check_cancelled()
                return trace.score, bool(summarize_episode(trace, trial_task, trial_creature).fell)

            def on_trial(done: int, total: int) -> None:
                reporter.report(done / total if total else 1.0, f"trial {done}/{total}")

            return run_trials(
                creature,
                task_for_run,
                evaluate,
                trials=trials,
                mass_jitter=mass_jitter,
                friction_jitter=friction_jitter,
                on_trial=on_trial,
                should_stop=lambda: reporter.cancel_requested,
            )

        if not job_manager.start(work):
            session.last_message = "A job is already running."

    def start_qualify_job(profile_name: str) -> None:
        profile_spec = BUILTIN_PROFILES.get(profile_name)
        if profile_spec is None:
            session.last_message = f"Unknown qualification profile {profile_name!r}."
            return
        creature = session.creature
        task_for_run = session.task
        controller = session.controller

        def work(reporter: ProgressReporter) -> QualificationResult:
            def simulate_bound(c: CreatureSpec, t: TaskSpec) -> EpisodeTrace:
                trace = simulate(
                    c,
                    t,
                    controller=controller,
                    should_stop=lambda: reporter.cancel_requested,
                )
                reporter.check_cancelled()
                return trace

            simulate_other_bound = None
            if simulate_other_backend is not None:

                def simulate_other_bound(c: CreatureSpec, t: TaskSpec) -> EpisodeTrace:
                    trace = simulate_other_backend(
                        c,
                        t,
                        controller=controller,
                        should_stop=lambda: reporter.cancel_requested,
                    )
                    reporter.check_cancelled()
                    return trace

            def on_trial(done: int, total: int) -> None:
                reporter.report(done / total if total else 1.0, f"robustness trial {done}/{total}")

            try:
                result = run_qualify(
                    creature,
                    task_for_run,
                    profile_spec,
                    simulate=simulate_bound,
                    simulate_other_backend=simulate_other_bound,
                    on_trial=on_trial,
                    should_stop=lambda: reporter.cancel_requested,
                )
            except Exception:
                if reporter.cancel_requested:
                    raise JobCancelled from None
                raise
            # A stopped-early robustness sweep still returns a QualificationResult
            # (see qualify()'s docstring) rather than raising - but a cancelled
            # qualification is not a meaningful pass/fail verdict, so treat it the
            # same way start_simulate_job/start_robustness_job do.
            reporter.check_cancelled()
            return result

        if not job_manager.start(work):
            session.last_message = "A job is already running."

    def start_refit_gait_job(attempts: int) -> None:
        """CMA-ES-retune this body's own sinusoid motors (amplitude/frequency/
        phase only - morphology untouched), the same search `creature-lab
        optimize`/`evolve --strategy cmaes` already run, aimed at the interactive
        "the packaged gait doesn't fit this edited body" moment (see
        docs/KNOWN_ISSUES.md) instead of a separate CLI step.
        """
        creature = session.creature
        task_for_run = session.task

        def work(reporter: ProgressReporter) -> CreatureSpec:
            import random

            from creature_lab.evolve import cmaes

            calls = 0

            def evaluate(candidate: CreatureSpec) -> float:
                nonlocal calls
                reporter.check_cancelled()
                calls += 1
                reporter.report(0.0, f"evaluating candidate {calls}")
                trace = simulate(candidate, task_for_run, controller="sinusoid")
                return trace.score

            result = cmaes(creature, evaluate, attempts=attempts, rng=random.Random(0))
            reporter.check_cancelled()
            return result.best

        if not job_manager.start(work):
            session.last_message = "A job is already running."

    def start_autopsy_job() -> None:
        """Run the existing counterfactual analysis and save a shareable pack."""
        from creature_lab.autopsy import autopsy_to_html, autopsy_to_markdown, run_autopsy
        from creature_lab.exporting import export_design_pack, verify_design_pack
        from creature_lab.io_utils import atomic_write_text

        creature = session.creature
        task_for_run = session.task
        controller = session.controller

        def work(reporter: ProgressReporter) -> tuple[Any, Path, EpisodeTrace]:
            import json

            completed = 0

            def simulate_with(c: CreatureSpec, t: TaskSpec, selected: str) -> EpisodeTrace:
                nonlocal completed
                reporter.check_cancelled()
                reporter.report(completed / 7, f"simulation {completed + 1}/7")
                try:
                    trace = simulate(
                        c, t, controller=selected, should_stop=lambda: reporter.cancel_requested
                    )
                except Exception:
                    if reporter.cancel_requested:
                        raise JobCancelled from None
                    raise
                reporter.check_cancelled()
                completed += 1
                return trace

            result = run_autopsy(
                creature,
                task_for_run,
                simulate=lambda c, t: simulate_with(c, t, controller),
                simulate_reference=lambda c, t: simulate_with(c, t, "curated"),
                robustness_trials=5,
            )
            reporter.check_cancelled()
            run_dir = save_run(
                creature, result.baseline_trace, runs_dir=runs_dir, task=task_for_run
            )
            saved_trace = load_trace(run_dir)
            report_dir = run_dir / "autopsy"
            report_dir.mkdir()
            pack_dir = report_dir / "experiment_pack"
            export_design_pack(
                creature, task_for_run, saved_trace, out_dir=pack_dir, source_dir=run_dir
            )
            verification = verify_design_pack(pack_dir)
            if not verification.valid:
                raise ValueError(
                    "Experiment pack verification failed: " + "; ".join(verification.errors)
                )
            atomic_write_text(
                report_dir / "autopsy.json", json.dumps(result.to_json_dict(), indent=2)
            )
            atomic_write_text(report_dir / "autopsy.md", autopsy_to_markdown(result))
            atomic_write_text(report_dir / "autopsy.html", autopsy_to_html(result))
            return result, report_dir, saved_trace

        if not job_manager.start(work):
            session.last_message = "A job is already running."

    def start_replay_export_job(trace: EpisodeTrace) -> None:
        from creature_lab.viewers.viser_viewer import recorded_replay_html

        creature = session.creature
        task_for_run = session.task

        def work(reporter: ProgressReporter) -> tuple[str, str]:
            def on_frame(done: int, total: int) -> None:
                reporter.report(done / total if total else 1.0, f"recording frame {done}/{total}")

            try:
                page = recorded_replay_html(
                    creature,
                    trace,
                    task=task_for_run,
                    on_frame=on_frame,
                    should_stop=lambda: reporter.cancel_requested,
                )
            except InterruptedError:
                raise JobCancelled from None
            reporter.check_cancelled()
            return trace.run_id, page

        if not job_manager.start(work):
            session.last_message = "A job is already running."

    controls_holder["controls"] = BuildControls(
        server.gui,
        session,
        job_manager=job_manager,
        playback=playback,
        on_preview=preview.refresh,
        on_preview_light=preview.refresh_overlays,
        on_start_simulate=start_simulate_job,
        on_start_robustness=start_robustness_job,
        on_start_qualify=start_qualify_job,
        on_start_refit_gait=start_refit_gait_job,
        on_start_autopsy=start_autopsy_job,
        on_start_replay_export=start_replay_export_job,
        on_playback_frame=preview.apply_playback_frame,
        notify=notify,
        on_frame_camera=lambda: preview.frame_camera(),
        runs_dir=runs_dir,
        show_onboarding=show_onboarding,
    )
    preview.refresh()

    last_tick = time.monotonic()
    try:
        while True:
            controls = controls_holder["controls"]
            active = job_manager.is_running or playback.playing
            time.sleep(1.0 / 30 if active else 0.25)
            now = time.monotonic()
            dt, last_tick = now - last_tick, now
            controls.tick(dt)
            if session.poll_external_changes():
                controls.notify_external_change()
    except KeyboardInterrupt:
        pass
    finally:
        job_manager.shutdown(timeout=10.0)
        server.stop()
