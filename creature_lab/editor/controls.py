"""Viser GUI for the build editor.

The panel is organised as the product loop, not as a wall of folders:

    Undo/Redo + Advanced mode (compact header, always visible)
      -> Design  ->  Motion  ->  Test        (phases, primary navigation)
    Project + History (collapsed folders below the phases - Open/Save,
      snapshots, Reset to template; not needed for a first run)

Each tab owns a few rebuildable folders. A **Basic/Advanced** switch (backed by
``EditorSession.mode``) hides the controls a first-time user does not need.

Simulate and the robustness sweep run through an :class:`~creature_lab.editor.jobs.
EditorJobManager` in the background (see ``editor/live.py``), so the panel stays
responsive; :meth:`BuildControls.tick` is called once per main-loop iteration to poll
job progress and advance trace playback. All the editing/diagnosis/history logic
itself lives in the pure :class:`~creature_lab.editor.session.EditorSession`; this
file only wires widgets to it and decides what to show.
"""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

from creature_lab.diagnosis import diagnose
from creature_lab.diagnostics import summarize_episode
from creature_lab.editor import presets
from creature_lab.editor.jobs import EditorJobManager, JobStatus
from creature_lab.editor.labels import friendly_label, hierarchy_rows
from creature_lab.editor.playback import EditorPlayback
from creature_lab.editor.session import AVAILABLE_CONTROLLERS, EditorSession
from creature_lab.hashing import spec_hash
from creature_lab.qualification import BUILTIN_PROFILES, QualificationResult
from creature_lab.robustness import ROBUSTNESS_LEVELS, RobustnessResult, plain_language_verdict
from creature_lab.runs import DEFAULT_RUNS_DIR, RunSummary, list_recent_runs, load_run
from creature_lab.schema import EpisodeSummary, EpisodeTrace, FrameState, TaskSpec
from creature_lab.schema.creature import ShapeType

_SEVERITY_TAG = {"critical": "**[CRITICAL]**", "warning": "**[WARNING]**", "info": "**[INFO]**"}


class BuildControls:
    """Build and keep the Viser side panel in sync with an ``EditorSession``."""

    def __init__(
        self,
        gui: Any,
        session: EditorSession,
        *,
        job_manager: EditorJobManager,
        playback: EditorPlayback,
        on_preview: Callable[[], None],
        on_preview_light: Callable[[], None] | None = None,
        on_start_simulate: Callable[[], None],
        on_start_robustness: Callable[[int, float, float], None],
        on_start_qualify: Callable[[str], None],
        on_playback_frame: Callable[[FrameState], None],
        notify: Callable[[str, str, str], None] | None = None,
        on_frame_camera: Callable[[], None] | None = None,
        on_start_refit_gait: Callable[[int], None] | None = None,
        on_start_autopsy: Callable[[], None] | None = None,
        on_start_replay_export: Callable[[EpisodeTrace], None] | None = None,
        runs_dir: Path = DEFAULT_RUNS_DIR,
        show_onboarding: bool = False,
    ) -> None:
        self.gui = gui
        self.session = session
        self.job_manager = job_manager
        self.playback = playback
        self.on_preview = on_preview
        self.on_preview_light = on_preview_light or on_preview
        self.on_frame_camera = on_frame_camera or (lambda: None)
        self.on_start_simulate = on_start_simulate
        self.on_start_robustness = on_start_robustness
        self.on_start_qualify = on_start_qualify
        self.on_start_refit_gait = on_start_refit_gait or (lambda attempts: None)
        self.on_start_autopsy = on_start_autopsy
        self.on_start_replay_export = on_start_replay_export
        self.on_playback_frame = on_playback_frame
        #: (title, body, color) -> None, broadcast to every connected browser tab.
        #: Optional so the fake-GUI unit tests don't need to supply one.
        self.notify = notify or (lambda title, body, color: None)
        self.runs_dir = runs_dir
        # Phase containers (created once) and the rebuildable folders inside them.
        # These are explicit show/hide folders instead of browser-local tabs, so a
        # completed run can always provide a real "Back to Design" action that also
        # restores the editable pose in the 3D scene.
        self._phase_selector: Any | None = None
        self._design_tab: Any | None = None
        self._motion_tab: Any | None = None
        self._test_tab: Any | None = None
        self._body_folder: Any | None = None
        self._part_folder: Any | None = None
        self._motion_folder: Any | None = None
        self._task_folder: Any | None = None
        self._playback_folder: Any | None = None
        self._metrics_folder: Any | None = None
        self._robustness_folder: Any | None = None
        self._qualify_folder: Any | None = None
        self._run_history_folder: Any | None = None
        self._onboarding_folder: Any | None = None
        # Persistent handles updated in place.
        self._message: Any | None = None
        self._controller_resolution_md: Any | None = None
        self._controller_dropdown: Any | None = None
        self._simulate_button: Any | None = None
        self._undo_button: Any | None = None
        self._redo_button: Any | None = None
        self._reload_button: Any | None = None
        self._restore_dropdown: Any | None = None
        self._job_progress_bar: Any | None = None
        self._job_status_md: Any | None = None
        self._cancel_button: Any | None = None
        self._playback_slider: Any | None = None
        self._playback_play_button: Any | None = None
        self._robustness_button: Any | None = None
        self._robustness_result_md: Any | None = None
        self._qualify_button: Any | None = None
        self._qualify_result_md: Any | None = None
        self._refit_gait_button: Any | None = None
        self._autopsy_button: Any | None = None
        self._replay_export_button: Any | None = None
        self._replay_export_client: Any | None = None
        self._last_autopsy: Any | None = None
        self._autopsy_report_dir: Path | None = None
        self._pending_signature: tuple[str, str, str] | None = None
        self._last_trace: EpisodeTrace | None = None
        self._last_robustness: RobustnessResult | None = None
        self._last_qualification: QualificationResult | None = None
        #: (creature_hash, task_hash, controller) that produced the currently shown
        #: Result/Robustness/Qualify. When the live config drifts from this, those
        #: results are stale and get cleared so the panel never shows a score from
        #: one configuration next to a status/error from another (see
        #: ``_discard_stale_result``).
        self._last_run_signature: tuple[str, str, str] | None = None
        self._pending_job_kind: str | None = None
        self._run_history_by_label: dict[str, RunSummary] = {}
        self._build(show_onboarding=show_onboarding)

    @property
    def _advanced(self) -> bool:
        return self.session.mode == "advanced"

    # -- top-level layout -------------------------------------------------------

    def _build(self, *, show_onboarding: bool = False) -> None:
        self.gui.add_markdown("## Creature Lab")
        self.gui.add_markdown("_Design -> Move -> Test -> Improve_")
        self.gui.add_markdown("Browser tabs connected to this editor share the same session.")

        # First-run picker, at the top of the panel so it is the first thing seen.
        # Deliberately an inline folder, NOT a modal: a Viser/Mantine modal traps
        # focus onto its first control, which auto-opens the Creature dropdown right
        # over the Start/Skip buttons - making the whole first run unclickable
        # (see docs/KNOWN_ISSUES.md). A normal panel dropdown never auto-opens.
        if show_onboarding:
            self._build_onboarding_panel()

        self._build_header_controls()

        # Phase nav is the primary navigation - it used to sit below ~500px of
        # Project/History controls (7 of them disabled on load); it's now the
        # first thing after the title, matching how it's used (see
        # docs/KNOWN_ISSUES.md). Project/History move to collapsed folders below
        # the tabs - see ``_build_project_folder``/``_build_history_folder``.
        self._phase_selector = self.gui.add_button_group("Phase", ["Design", "Motion", "Test"])
        self._phase_selector.on_click(lambda event: self._show_phase(event.target.value))
        self._message = self.gui.add_markdown("")
        self._build_job_status_widgets()

        self._design_tab = self.gui.add_folder("1 · Design", expand_by_default=True)
        self._motion_tab = self.gui.add_folder("2 · Motion", expand_by_default=True, visible=False)
        self._test_tab = self.gui.add_folder("3 · Test", expand_by_default=True, visible=False)

        with self._design_tab:
            self._build_template_picker()
        with self._test_tab:
            self._build_run_section()
            self._build_refit_gait_section()
            self._build_lesson_section()

        self._build_project_folder()
        self._build_history_folder()

        self._rebuild_all()
        self._update_status()

    def _build_header_controls(self) -> None:
        """Undo/Redo + Advanced mode: compact, and always visible above the tabs.

        Advanced mode has to live outside any folder it also gates (unlike the
        rest of History's contents, see ``_build_history_folder``) since it's the
        one switch that reveals exact dimensions/mass/colour/raw-phase controls
        throughout every tab, not just History's own contents.
        """
        advanced = self.gui.add_checkbox(
            "Advanced mode",
            self._advanced,
            hint="Show exact dimensions, mass, colours, raw phases, friction, and "
            "robustness jitter. Off keeps only the controls needed for a first run.",
        )
        advanced.on_update(
            lambda event: self._safe(
                lambda: self.session.set_mode("advanced" if event.target.value else "basic"),
                rebuild_body=True,
                rebuild_part=True,
                rebuild_motion=True,
                rebuild_task=True,
            )
        )
        self._undo_button = self.gui.add_button("Undo", icon="arrow-back-up")
        self._undo_button.on_click(lambda _event: self._history_action(self.session.undo))
        self._redo_button = self.gui.add_button("Redo", icon="arrow-forward-up")
        self._redo_button.on_click(lambda _event: self._history_action(self.session.redo))

    def _show_phase(self, phase: str) -> None:
        """Show one workflow phase and restore design state when leaving playback."""
        if phase not in {"Design", "Motion", "Test"}:
            return
        if self._phase_selector is not None and self._phase_selector.value != phase:
            self._phase_selector.value = phase
        for name, handle in (
            ("Design", self._design_tab),
            ("Motion", self._motion_tab),
            ("Test", self._test_tab),
        ):
            if handle is not None:
                handle.visible = name == phase
        if phase != "Test":
            self.playback.pause()
            self.on_preview()

    def _build_project_folder(self) -> None:
        with self.gui.add_folder("Project", expand_by_default=False):
            name = self.gui.add_text("Name", self.session.creature.name)
            name.on_update(
                lambda event: self._safe(
                    lambda: self.session.set_name(event.target.value),
                    rebuild_body=False,
                    rebuild_part=False,
                    rebuild_motion=False,
                    rebuild_task=False,
                )
            )
            load_path = self.gui.add_text(
                "Open path",
                str(self.session.source_path or self.session.out_path),
                hint="A .json CreatureSpec, or a .urdf to import (best-effort; meshes/"
                "sensors are skipped and reported as warnings).",
            )
            open_button = self.gui.add_button("Open", icon="folder-open")
            open_button.on_click(
                lambda _event: self._safe(
                    lambda: self.session.load_path(Path(load_path.value)),
                    rebuild_body=True,
                    rebuild_part=True,
                    rebuild_motion=True,
                    rebuild_task=True,
                )
            )
            save_path = self.gui.add_text(
                "Save path",
                str(self.session.out_path),
                hint="Extension picks the format: .json (CreatureSpec), .urdf, or .xml/.mjcf "
                "(MJCF export is one-way; it cannot be re-opened here).",
            )
            save_button = self.gui.add_button("Save", icon="device-floppy", color="green")
            save_button.on_click(
                lambda _event: self._safe(
                    lambda: self.session.save(Path(save_path.value)),
                    rebuild_body=False,
                    rebuild_part=False,
                    rebuild_motion=False,
                    rebuild_task=False,
                )
            )
            if self.session.project_dir is not None:
                self.gui.add_markdown(f"**Project (live-synced):** `{self.session.project_dir}`")
                self._reload_button = self.gui.add_button("Reload from disk", icon="refresh-dot")
                self._reload_button.on_click(lambda _event: self._confirm_reload())
                overwrite_button = self.gui.add_button(
                    "Overwrite disk with editor", icon="device-floppy", color="orange"
                )
                overwrite_button.on_click(lambda _event: self._confirm_overwrite_project())

    def _build_history_folder(self) -> None:
        """Reset-to-template + snapshots. Undo/Redo/Advanced mode live in the
        always-visible header instead - see ``_build_header_controls``."""
        with self.gui.add_folder("History", expand_by_default=False):
            reset = self.gui.add_button("Reset to template", icon="rotate")
            reset.on_click(lambda _event: self._history_action(self.session.reset_to_template))

            snapshot_name = self.gui.add_text("Snapshot name", "")
            save_snapshot = self.gui.add_button("Save snapshot", icon="camera")
            save_snapshot.on_click(
                lambda _event: self._safe(
                    lambda: self.session.save_snapshot(snapshot_name.value),
                    rebuild_body=False,
                    rebuild_part=False,
                    rebuild_motion=False,
                    rebuild_task=False,
                    after=self._refresh_restore_options,
                )
            )
            self._restore_dropdown = self.gui.add_dropdown(
                "Restore", ["(none)", *self.session.snapshot_names()], initial_value="(none)"
            )
            restore_button = self.gui.add_button("Restore snapshot", icon="history")
            restore_button.on_click(lambda _event: self._restore_selected_snapshot())

    def _build_job_status_widgets(self) -> None:
        """Progress bar + status text + cancel, shared by Simulate and Robustness.

        Created once, hidden (``visible=False``) until a job is running - see
        ``_render_job_status``, called every ``tick()``.
        """
        self._job_progress_bar = self.gui.add_progress_bar(0.0, visible=False, animated=True)
        self._job_status_md = self.gui.add_markdown("")
        self._cancel_button = self.gui.add_button("Cancel", icon="player-stop", color="red")
        self._cancel_button.visible = False
        self._cancel_button.on_click(lambda _event: self.job_manager.cancel())

    def _build_template_picker(self) -> None:
        initial = (
            presets.preset_label(self.session.template)
            if self.session.template in presets.CREATURE_PRESETS
            else presets.preset_label("quadruped")
        )
        template = self.gui.add_dropdown(
            "Start from", presets.preset_labels(), initial_value=initial
        )
        template.on_update(
            lambda event: self._safe(
                lambda: self.session.apply_template(
                    presets.preset_name_from_label(event.target.value)
                ),
                rebuild_body=True,
                rebuild_part=True,
                rebuild_motion=True,
                rebuild_task=False,
            )
        )
        frame_button = self.gui.add_button(
            "Frame creature",
            icon="focus-2",
            hint="Point the camera at the creature - lost it off-screen or zoomed too far?",
        )
        frame_button.on_click(lambda _event: self.on_frame_camera())

    def _build_run_section(self) -> None:
        with self.gui.add_folder("Run", expand_by_default=True, order=10):
            back_to_design = self.gui.add_button("Back to Design", icon="arrow-left")
            back_to_design.on_click(lambda _event: self._show_phase("Design"))
            controller = self.gui.add_dropdown(
                "Controller",
                list(AVAILABLE_CONTROLLERS),
                initial_value=self.session.controller,
                hint="'target_seek' steers toward the task's target - pick a task with "
                "one (e.g. reach_target) or it errors when you Simulate.",
            )
            self._controller_dropdown = controller
            controller.on_update(
                lambda event: self._safe(
                    lambda: self.session.set_controller(event.target.value),
                    rebuild_body=False,
                    rebuild_part=False,
                    rebuild_motion=False,
                    rebuild_task=False,
                    preview="none",
                )
            )
            self._controller_resolution_md = self.gui.add_markdown("")
            self._simulate_button = self.gui.add_button(
                "Simulate", icon="player-play", color="blue"
            )
            self._simulate_button.on_click(lambda _event: self._start_simulate())
            validate = self.gui.add_button("Validate", icon="check")
            validate.on_click(lambda _event: self._update_status())

    def _build_lesson_section(self) -> None:
        lessons = {
            "Frozen gait": "frozen-gait",
            "Overdriven gait": "overdriven-gait",
            "Ice-rink task": "ice-rink-task",
        }
        with self.gui.add_folder("Failure lessons", expand_by_default=False, order=26):
            self.gui.add_markdown(
                "Load a deliberately difficult case, simulate it, and change one thing. "
                "Loading replaces the editable body/task and selects the sinusoid controller; "
                "Undo restores the body/task."
            )
            choice = self.gui.add_dropdown("Lesson", list(lessons), initial_value="Frozen gait")
            button = self.gui.add_button("Load lesson")

            def load(_event: Any) -> None:
                self._history_action(
                    lambda: self.session.load_failure_lesson(lessons[choice.value])
                )
                if self._controller_dropdown is not None:
                    self._controller_dropdown.value = self.session.controller

            button.on_click(load)

    def _build_refit_gait_section(self) -> None:
        """CMA-ES re-tune this body's own sinusoid motors (order=25: right after
        Run/Result, before Task) - the fix for a common dead end: editing a body
        can make a packaged gait no longer fit (see docs/KNOWN_ISSUES.md), and
        this turns that into "tune a new one" instead of a manual CLI round trip.
        Needs the optional 'evolve' extra (`uv sync --extra evolve`); without it
        the job fails with a clear message instead of the button doing nothing.
        """
        with self.gui.add_folder("Re-fit gait", expand_by_default=False, order=25):
            self.gui.add_markdown(
                "Retune this body's own motor amplitude/frequency/phase with "
                "CMA-ES (the same search behind `creature-lab optimize`) - the "
                "body itself is never changed. Useful when a template's packaged "
                "gait no longer fits after editing."
            )
            attempts_slider = self.gui.add_slider(
                "Attempts", min=5, max=100, step=5, initial_value=20
            )
            self._refit_gait_button = self.gui.add_button("Re-fit gait", icon="wand")
            self._refit_gait_button.on_click(
                lambda _event: self._start_refit_gait(int(attempts_slider.value))
            )

    # -- rebuild orchestration --------------------------------------------------

    def _rebuild_all(self) -> None:
        self._rebuild_body_controls()
        self._rebuild_part_controls()
        self._rebuild_motion_controls()
        self._rebuild_task_controls()
        self._rebuild_playback_controls()
        self._rebuild_metrics_controls()
        self._rebuild_robustness_controls()
        self._rebuild_qualify_controls()
        self._rebuild_run_history_controls()

    def scene_selected(self, part_id: str) -> None:
        # Selection alone never changes geometry - only the overlay (gizmo/CoM
        # markers) needs to move, so this skips the expensive full scene rebuild.
        self._safe(
            lambda: self.session.select_part(part_id),
            rebuild_body=False,
            rebuild_part=True,
            rebuild_motion=False,
            rebuild_task=False,
            preview="light",
        )

    def scene_changed(self) -> None:
        self._update_status()

    def notify_external_change(self) -> None:
        """Called when the bound project's creature.json/task.json changed on disk."""
        self._update_status()

    def _safe(
        self,
        operation: Callable[[], Any],
        *,
        rebuild_body: bool,
        rebuild_part: bool,
        rebuild_motion: bool,
        rebuild_task: bool,
        after: Callable[[], None] | None = None,
        preview: str = "full",
    ) -> None:
        try:
            operation()
            self.session.autosave()
        except Exception as exc:
            self.session.last_message = f"Error: {exc}"
        self._refresh(
            rebuild_body=rebuild_body,
            rebuild_part=rebuild_part,
            rebuild_motion=rebuild_motion,
            rebuild_task=rebuild_task,
            preview=preview,
        )
        if after is not None:
            after()

    def _history_action(self, operation: Callable[[], Any]) -> None:
        """Undo/redo/reset/apply-fix can all change any part of the design."""
        self._safe(
            operation,
            rebuild_body=True,
            rebuild_part=True,
            rebuild_motion=True,
            rebuild_task=True,
        )

    def _refresh(
        self,
        *,
        rebuild_body: bool,
        rebuild_part: bool,
        rebuild_motion: bool,
        rebuild_task: bool,
        preview: str = "full",
    ) -> None:
        if rebuild_body:
            self._rebuild_body_controls()
        if rebuild_part:
            self._rebuild_part_controls()
        if rebuild_motion:
            self._rebuild_motion_controls()
        if rebuild_task:
            self._rebuild_task_controls()
        if self._discard_stale_result():
            self._rebuild_metrics_controls()
            self._rebuild_playback_controls()
            self._render_robustness_result()
            self._render_qualify_result()
        if preview == "light":
            self.on_preview_light()
        elif preview != "none":
            self.on_preview()
        self._update_status()

    def _remove_folder(self, attr: str) -> None:
        folder = getattr(self, attr)
        if folder is not None:
            try:
                folder.remove()
            except Exception:
                pass
        setattr(self, attr, None)

    # -- Design tab: body -------------------------------------------------------

    def _rebuild_body_controls(self) -> None:
        self._remove_folder("_body_folder")
        with self._design_tab:
            self._body_folder = self.gui.add_folder("Body", expand_by_default=True)
        with self._body_folder:
            if self.session.template == "custom":
                self.gui.add_markdown(
                    "Loaded JSON is custom. Use **Selected part** and the **Motion** tab."
                )
                return
            preset = presets.CREATURE_PRESETS[self.session.template]
            self.gui.add_markdown(f"Template: **{preset.label}**")
            for param in preset.params:
                value = self.session.params[param.key]
                slider = self.gui.add_slider(
                    param.label,
                    min=param.minimum,
                    max=param.maximum,
                    step=param.step,
                    initial_value=int(value) if param.kind == "int" else value,
                )
                slider.on_update(
                    lambda event, key=param.key: self._safe(
                        lambda: self.session.set_body_param(key, float(event.target.value)),
                        rebuild_body=False,
                        rebuild_part=True,
                        rebuild_motion=True,
                        rebuild_task=False,
                    )
                )

    # -- Design tab: selected part ---------------------------------------------

    def _add_hierarchy_tree(self) -> None:
        """Clickable part tree: one small indented button per part.

        Replaces a static markdown tree (just text - selecting a part meant using
        the dropdown below instead, even though the tree already showed the same
        structure) with real clickable structure, one button per row.
        """
        selected_id = self.session.selected_part_id
        for depth, part_id in hierarchy_rows(self.session.creature):
            label = ("&nbsp;&nbsp;&nbsp;" * depth) + friendly_label(part_id)
            button = self.gui.add_button(label, color="blue" if part_id == selected_id else None)
            button.on_click(
                lambda _event, part_id=part_id: self._safe(
                    lambda: self.session.select_part(part_id),
                    rebuild_body=False,
                    rebuild_part=True,
                    rebuild_motion=False,
                    rebuild_task=False,
                    preview="light",
                )
            )

    def _rebuild_part_controls(self) -> None:
        self._remove_folder("_part_folder")
        with self._design_tab:
            self._part_folder = self.gui.add_folder("Selected part", expand_by_default=True)
        with self._part_folder:
            self._add_hierarchy_tree()
            part = self.session.selected_part()
            part_select = self.gui.add_dropdown(
                "Part",
                self.session.part_ids(),
                initial_value=part.id,
            )
            part_select.on_update(
                lambda event: self._safe(
                    lambda: self.session.select_part(event.target.value),
                    rebuild_body=False,
                    rebuild_part=True,
                    rebuild_motion=False,
                    rebuild_task=False,
                    preview="light",
                )
            )

            if self._advanced:
                shape = self.gui.add_dropdown(
                    "Shape",
                    [shape.value for shape in ShapeType],
                    initial_value=part.shape.value,
                )
                shape.on_update(
                    lambda event: self._safe(
                        lambda: self.session.update_selected_part(shape=event.target.value),
                        rebuild_body=False,
                        rebuild_part=True,
                        rebuild_motion=False,
                        rebuild_task=False,
                    )
                )

            self._add_dimension_controls(part)

            if self._advanced:
                mass = self.gui.add_slider(
                    "Mass",
                    min=0.01,
                    max=max(5.0, part.mass * 3),
                    step=0.01,
                    initial_value=part.mass,
                )
                mass.on_update(
                    lambda event: self._safe(
                        lambda: self.session.update_selected_part(mass=float(event.target.value)),
                        rebuild_body=False,
                        rebuild_part=False,
                        rebuild_motion=False,
                        rebuild_task=False,
                    )
                )
                color = tuple(
                    int(round(channel * 255)) for channel in (part.color or (0.6, 0.6, 0.6))
                )
                color_handle = self.gui.add_rgb("Color", color)
                color_handle.on_update(
                    lambda event: self._safe(
                        lambda: self.session.update_selected_part(color=event.target.value),
                        rebuild_body=False,
                        rebuild_part=False,
                        rebuild_motion=False,
                        rebuild_task=False,
                    )
                )

            add_limb = self.gui.add_button("Add limb", icon="plus")
            add_limb.on_click(
                lambda _event: self._safe(
                    self.session.add_limb,
                    rebuild_body=False,
                    rebuild_part=True,
                    rebuild_motion=True,
                    rebuild_task=False,
                )
            )
            delete = self.gui.add_button("Delete part", icon="trash", color="red")
            delete.on_click(lambda _event: self._confirm_delete())
            mirror_left = self.gui.add_button("Mirror left -> right", icon="copy")
            mirror_left.on_click(
                lambda _event: self._safe(
                    lambda: self.session.mirror("left"),
                    rebuild_body=False,
                    rebuild_part=True,
                    rebuild_motion=True,
                    rebuild_task=False,
                )
            )
            if self._advanced:
                mirror_right = self.gui.add_button("Mirror right -> left", icon="copy")
                mirror_right.on_click(
                    lambda _event: self._safe(
                        lambda: self.session.mirror("right"),
                        rebuild_body=False,
                        rebuild_part=True,
                        rebuild_motion=True,
                        rebuild_task=False,
                    )
                )

    def _add_dimension_controls(self, part: Any) -> None:
        if part.shape == ShapeType.BOX and part.size is not None:
            self._add_size_slider("Size X", 0, part.size)
            self._add_size_slider("Size Y", 1, part.size)
            self._add_size_slider("Size Z", 2, part.size)
        elif part.shape == ShapeType.SPHERE and part.radius is not None:
            radius = self.gui.add_slider(
                "Radius", min=0.005, max=0.5, step=0.005, initial_value=part.radius
            )
            radius.on_update(
                lambda event: self._safe(
                    lambda: self.session.update_selected_part(radius=float(event.target.value)),
                    rebuild_body=False,
                    rebuild_part=False,
                    rebuild_motion=False,
                    rebuild_task=False,
                )
            )
        else:
            length = self.gui.add_slider(
                "Length",
                min=0.02,
                max=1.2,
                step=0.01,
                initial_value=part.length or 0.2,
            )
            length.on_update(
                lambda event: self._safe(
                    lambda: self.session.update_selected_part(length=float(event.target.value)),
                    rebuild_body=False,
                    rebuild_part=False,
                    rebuild_motion=False,
                    rebuild_task=False,
                )
            )
            if self._advanced:
                radius = self.gui.add_slider(
                    "Radius",
                    min=0.005,
                    max=0.25,
                    step=0.005,
                    initial_value=part.radius or 0.03,
                )
                radius.on_update(
                    lambda event: self._safe(
                        lambda: self.session.update_selected_part(radius=float(event.target.value)),
                        rebuild_body=False,
                        rebuild_part=False,
                        rebuild_motion=False,
                        rebuild_task=False,
                    )
                )

    def _add_size_slider(
        self, label: str, index: int, current_size: tuple[float, float, float]
    ) -> None:
        slider = self.gui.add_slider(
            label,
            min=0.01,
            max=1.2,
            step=0.01,
            initial_value=current_size[index],
        )
        slider.on_update(
            lambda event: self._safe(
                lambda: self._set_box_size(index, float(event.target.value)),
                rebuild_body=False,
                rebuild_part=False,
                rebuild_motion=False,
                rebuild_task=False,
            )
        )

    def _set_box_size(self, index: int, value: float) -> None:
        part = self.session.selected_part()
        size = list(part.size or (0.2, 0.2, 0.1))
        size[index] = value
        self.session.update_selected_part(size=tuple(size))

    # -- Motion tab -------------------------------------------------------------

    def _rebuild_motion_controls(self) -> None:
        self._remove_folder("_motion_folder")
        with self._motion_tab:
            self._motion_folder = self.gui.add_folder("Movement", expand_by_default=True)
        with self._motion_folder:
            if not self.session.creature.motors:
                self.gui.add_markdown(
                    "No motors yet. Add a hinged limb in **Design** to create one."
                )
                return
            gait = self.gui.add_dropdown(
                "Gait preset",
                ["current", "trot", "pace", "wave", "still"],
                initial_value="current",
            )
            gait.on_update(
                lambda event: self._safe(
                    lambda: self.session.apply_gait(event.target.value),
                    rebuild_body=False,
                    rebuild_part=False,
                    rebuild_motion=True,
                    rebuild_task=False,
                )
            )
            motor_id = self.session.selected_motor()
            motor_select = self.gui.add_dropdown(
                "Joint motor",
                self.session.motor_ids(),
                initial_value=motor_id,
            )
            motor_select.on_update(
                lambda event: self._safe(
                    lambda: self.session.select_motor(event.target.value),
                    rebuild_body=False,
                    rebuild_part=False,
                    rebuild_motion=True,
                    rebuild_task=False,
                    preview="none",  # which motor is selected has no visual effect
                )
            )
            motor = next(m for m in self.session.creature.motors if m.joint == motor_id)
            amplitude = self.gui.add_slider(
                "Range (amplitude)",
                min=0.0,
                max=max(1.8, motor.amplitude),
                step=0.05,
                initial_value=motor.amplitude,
            )
            amplitude.on_update(
                lambda event: self._safe(
                    lambda: self.session.update_selected_motor(amplitude=float(event.target.value)),
                    rebuild_body=False,
                    rebuild_part=False,
                    rebuild_motion=False,
                    rebuild_task=False,
                )
            )
            frequency = self.gui.add_slider(
                "Speed (frequency)", min=0.0, max=6.0, step=0.1, initial_value=motor.frequency
            )
            frequency.on_update(
                lambda event: self._safe(
                    lambda: self.session.update_selected_motor(frequency=float(event.target.value)),
                    rebuild_body=False,
                    rebuild_part=False,
                    rebuild_motion=False,
                    rebuild_task=False,
                )
            )
            if self._advanced:
                offset = self.gui.add_slider(
                    "Center (offset)", min=-1.2, max=1.2, step=0.02, initial_value=motor.offset
                )
                offset.on_update(
                    lambda event: self._safe(
                        lambda: self.session.update_selected_motor(
                            offset=float(event.target.value)
                        ),
                        rebuild_body=False,
                        rebuild_part=False,
                        rebuild_motion=False,
                        rebuild_task=False,
                    )
                )
                phase = self.gui.add_slider(
                    "Phase", min=-6.28, max=6.28, step=0.05, initial_value=motor.phase
                )
                phase.on_update(
                    lambda event: self._safe(
                        lambda: self.session.update_selected_motor(phase=float(event.target.value)),
                        rebuild_body=False,
                        rebuild_part=False,
                        rebuild_motion=False,
                        rebuild_task=False,
                    )
                )
                max_force = self.gui.add_slider(
                    "Max torque (N·m)",
                    min=1.0,
                    max=400.0,
                    step=1.0,
                    initial_value=motor.max_force or 5.0,
                )
                max_force.on_update(
                    lambda event: self._safe(
                        lambda: self.session.update_selected_motor(
                            max_force=float(event.target.value)
                        ),
                        rebuild_body=False,
                        rebuild_part=False,
                        rebuild_motion=False,
                        rebuild_task=False,
                    )
                )

    # -- Test phase: task -------------------------------------------------------

    def _rebuild_task_controls(self) -> None:
        self._remove_folder("_task_folder")
        with self._test_tab:
            self._task_folder = self.gui.add_folder("Task", expand_by_default=True, order=30)
        with self._task_folder:
            task = self.gui.add_dropdown(
                "Task",
                presets.task_names(),
                initial_value=(
                    self.session.task_preset
                    if self.session.task_preset in presets.TASK_PRESETS
                    else "crawl_forward"
                ),
            )
            task.on_update(
                lambda event: self._safe(
                    lambda: self.session.set_task_preset(event.target.value),
                    rebuild_body=False,
                    rebuild_part=False,
                    rebuild_motion=False,
                    rebuild_task=True,
                )
            )
            duration = self.gui.add_slider(
                "Duration",
                min=0.5,
                max=12.0,
                step=0.5,
                initial_value=self.session.task.duration,
            )
            duration.on_update(
                lambda event: self._safe(
                    lambda: self.session.set_task_duration(float(event.target.value)),
                    rebuild_body=False,
                    rebuild_part=False,
                    rebuild_motion=False,
                    rebuild_task=False,
                )
            )
            if self.session.task.target is not None:
                target = self.session.task.target
                self.gui.add_markdown("**Target** — drag the orange target in 3D or tune it here.")
                target_values = list(target.position)
                labels = ("Target X", "Target Y", "Target Z")
                ranges = ((-5.0, 10.0), (-5.0, 5.0), (0.02, 3.0))
                for index, label in enumerate(labels):
                    slider = self.gui.add_slider(
                        label,
                        min=ranges[index][0],
                        max=ranges[index][1],
                        step=0.05,
                        initial_value=target_values[index],
                    )
                    slider.on_update(
                        lambda event, index=index: self._safe(
                            lambda: self._set_target_axis(index, float(event.target.value)),
                            rebuild_body=False,
                            rebuild_part=False,
                            rebuild_motion=False,
                            rebuild_task=False,
                        )
                    )
                radius = self.gui.add_slider(
                    "Target radius",
                    min=0.05,
                    max=2.0,
                    step=0.05,
                    initial_value=target.radius,
                )
                radius.on_update(
                    lambda event: self._safe(
                        lambda: self.session.set_target_radius(float(event.target.value)),
                        rebuild_body=False,
                        rebuild_part=False,
                        rebuild_motion=False,
                        rebuild_task=False,
                    )
                )
            friction = self.gui.add_slider(
                "Friction",
                min=0.0,
                max=max(2.0, self.session.task.terrain.friction),
                step=0.01,
                initial_value=self.session.task.terrain.friction,
            )
            friction.on_update(
                lambda event: self._safe(
                    lambda: self.session.set_task_friction(float(event.target.value)),
                    rebuild_body=False,
                    rebuild_part=False,
                    rebuild_motion=False,
                    rebuild_task=False,
                )
            )
            push = self.session.task.impulse_event
            self.gui.add_markdown(
                "Lateral push is a one-step force on the root at half the episode. "
                "Changing it replaces any existing push event; zero removes it."
            )
            push_force = push.force[1] if push else 0.0
            push_slider = self.gui.add_slider(
                "Lateral push (N)",
                min=min(-500.0, push_force),
                max=max(500.0, push_force),
                step=5.0,
                initial_value=push_force,
            )
            push_slider.on_update(
                lambda event: self._safe(
                    lambda: self.session.set_lateral_push(float(event.target.value)),
                    rebuild_body=False,
                    rebuild_part=False,
                    rebuild_motion=False,
                    rebuild_task=False,
                )
            )

    def _set_target_axis(self, index: int, value: float) -> None:
        if self.session.task.target is None:
            return
        position = list(self.session.task.target.position)
        position[index] = value
        self.session.set_target_position(tuple(position))

    # -- Test phase: run (async) -------------------------------------------------

    def _start_simulate(self) -> None:
        if self.job_manager.is_running:
            self.session.last_message = "A job is already running."
            self._update_status()
            return
        status = self.session.status()
        if not status.ok:
            self.session.last_message = "Fix validation errors before simulating."
            self._update_status()
            return
        self._pending_job_kind = "simulate"
        self._pending_signature = self._current_run_signature()
        self.on_start_simulate()
        self._render_job_status(self.job_manager.status())

    def _start_robustness(self, trials: int, mass_jitter: float, friction_jitter: float) -> None:
        if self.job_manager.is_running:
            self.session.last_message = "A job is already running."
            self._update_status()
            return
        status = self.session.status()
        if not status.ok:
            self.session.last_message = "Fix validation errors before running a robustness sweep."
            self._update_status()
            return
        self._pending_job_kind = "robustness"
        self._pending_signature = self._current_run_signature()
        self.on_start_robustness(trials, mass_jitter, friction_jitter)
        self._render_job_status(self.job_manager.status())

    def _start_qualify(self, profile_name: str) -> None:
        if self.job_manager.is_running:
            self.session.last_message = "A job is already running."
            self._update_status()
            return
        status = self.session.status()
        if not status.ok:
            self.session.last_message = "Fix validation errors before qualifying."
            self._update_status()
            return
        self._pending_job_kind = "qualify"
        self._pending_signature = self._current_run_signature()
        self.on_start_qualify(profile_name)
        self._render_job_status(self.job_manager.status())

    def _start_autopsy(self) -> None:
        if self.on_start_autopsy is None or self.job_manager.is_running:
            self.session.last_message = "A job is already running or analysis is unavailable."
            self._update_status()
            return
        if not self.session.status().ok:
            self.session.last_message = "Fix validation errors before explaining the result."
            self._update_status()
            return
        self._pending_signature = self._current_run_signature()
        self._pending_job_kind = "autopsy"
        self.on_start_autopsy()
        self._render_job_status(self.job_manager.status())

    def _start_replay_export(self, event: Any) -> None:
        client = getattr(event, "client", None)
        if self.job_manager.is_running or self.on_start_replay_export is None or client is None:
            self.session.last_message = "Replay export is unavailable while another job is running."
            self._update_status()
            return
        if self._last_trace is None:
            self.session.last_message = "Simulate or load a compatible replay first."
            self._update_status()
            return
        self._replay_export_client = client
        self._pending_job_kind = "replay_export"
        self.on_start_replay_export(self._last_trace)
        self._render_job_status(self.job_manager.status())

    def _start_refit_gait(self, attempts: int) -> None:
        if self.job_manager.is_running:
            self.session.last_message = "A job is already running."
            self._update_status()
            return
        status = self.session.status()
        if not status.ok:
            self.session.last_message = "Fix validation errors before re-fitting the gait."
            self._update_status()
            return
        if not self.session.creature.motors:
            self.session.last_message = "This body has no motors to re-fit."
            self._update_status()
            return
        self._pending_job_kind = "refit_gait"
        self._pending_signature = self._current_run_signature()
        self.on_start_refit_gait(attempts)
        self._render_job_status(self.job_manager.status())

    # -- background job polling (called from the main loop) ---------------------

    def tick(self, dt: float) -> None:
        """Poll the running job and advance playback. Call once per main-loop iteration."""
        self._tick_job()
        self._tick_playback(dt)

    def _tick_job(self) -> None:
        status = self.job_manager.status()
        self._render_job_status(status)
        if status.state == "completed":
            self._consume_completed_job(status)
            self.job_manager.clear()
        elif status.state in ("cancelled", "failed"):
            self._consume_ended_job(status)
            self.job_manager.clear()

    def _render_job_status(self, status: JobStatus) -> None:
        running = status.state == "running"
        if self._job_progress_bar is not None:
            self._job_progress_bar.visible = running
            self._job_progress_bar.value = status.progress * 100.0
            self._job_progress_bar.animated = running and status.progress <= 0.0
        if self._job_status_md is not None:
            self._job_status_md.content = (
                f"{status.message or 'Running…'} ({status.elapsed:.1f}s)" if running else ""
            )
        if self._cancel_button is not None:
            self._cancel_button.visible = running
        if self._simulate_button is not None:
            self._simulate_button.disabled = running or not self.session.status().ok
        if self._robustness_button is not None:
            self._robustness_button.disabled = running
        if self._qualify_button is not None:
            self._qualify_button.disabled = running
        if self._refit_gait_button is not None:
            self._refit_gait_button.disabled = running
        if self._autopsy_button is not None:
            self._autopsy_button.disabled = running
        if self._replay_export_button is not None:
            self._replay_export_button.disabled = running

    def _current_run_signature(self) -> tuple[str, str, str]:
        """Identity of the current (creature, task, controller) - a run is stale once
        any of these drifts from what produced it."""
        return (
            spec_hash(self.session.creature),
            spec_hash(self.session.task),
            self.session.controller,
        )

    def _discard_stale_result(self) -> bool:
        """Clear a shown Result/Robustness/Qualify once the live config no longer
        matches what produced it. Returns True if anything was cleared (so the caller
        rebuilds the now-empty panels). This is what stops the panel from showing,
        say, a healthy sinusoid score right next to a 'target_seek needs a target'
        error after the controller is switched."""
        if self._last_run_signature is None:
            return False
        if self._last_run_signature == self._current_run_signature():
            return False
        self._last_trace = None
        self._last_robustness = None
        self._last_qualification = None
        self._last_autopsy = None
        self._autopsy_report_dir = None
        self._last_run_signature = None
        self.playback.clear()
        return True

    def _consume_completed_job(self, status: JobStatus) -> None:
        kind, self._pending_job_kind = self._pending_job_kind, None
        signature, self._pending_signature = self._pending_signature, None
        if kind == "replay_export":
            run_id, page = status.result
            client, self._replay_export_client = self._replay_export_client, None
            try:
                if client is not None:
                    client.send_file_download(
                        f"creature-lab-replay-{run_id}.html", page.encode("utf-8")
                    )
                    self.session.last_message = (
                        "Recorded replay is available in the browser download notification."
                    )
            except Exception as exc:
                self.session.last_message = f"Could not send the replay to the browser: {exc}"
            self._update_status()
            return
        if signature is not None and signature != self._current_run_signature():
            self.session.last_message = (
                "The design or task changed while the job ran; its result was not applied. "
                "Completed simulation and analysis runs remain in History."
            )
            self._rebuild_run_history_controls()
            self._update_status()
            return
        if kind == "refit_gait":
            # Route through _history_action (not the run-signature bookkeeping
            # below): this is a body/motor mutation, like Undo/Reset-to-template/
            # Apply-fix, not a new Result/Robustness/Qualify to display - it
            # already handles autosave, a full rebuild, and discarding any
            # now-stale Result/Robustness/Qualify for the previous motor values.
            self._history_action(lambda: self.session.apply_refit_gait(status.result))
            self.notify(
                "Gait re-fitted",
                "Motor amplitude/frequency/phase tuned to this body - see Motion.",
                "blue",
            )
            return
        self._last_run_signature = self._current_run_signature()
        if kind == "simulate":
            trace, run_dir = status.result
            self._last_autopsy = None
            self._autopsy_report_dir = None
            self._last_trace = trace
            self.playback.load(trace)
            first = self.playback.current_frame()
            if first is not None:
                self.on_playback_frame(first)
            self.session.last_message = (
                f"{self.session.creature.name!r} on {self.session.task.name!r}: "
                f"score={trace.score:+.4f} — see Result below."
            )
            self._notify_simulate_result(trace)
            self._rebuild_playback_controls()
            self._rebuild_run_history_controls()
        elif kind == "robustness":
            self._last_robustness = status.result
            self.session.last_message = "Robustness sweep complete."
        elif kind == "qualify":
            self._last_qualification = status.result
            verdict = "PASS" if status.result.passed else "FAIL"
            self.session.last_message = f"Qualification: {verdict} ({status.result.profile})"
        elif kind == "autopsy":
            result, report_dir, trace = status.result
            self._last_autopsy = result
            self._autopsy_report_dir = report_dir
            self._last_trace = trace
            self.playback.load(trace)
            first = self.playback.current_frame()
            if first is not None:
                self.on_playback_frame(first)
            self.session.last_message = f"Analysis saved to {report_dir}."
            self._rebuild_playback_controls()
            self._rebuild_run_history_controls()
        self._rebuild_metrics_controls()
        self._render_robustness_result()
        self._render_qualify_result()
        self._update_status()

    def _notify_simulate_result(self, trace: EpisodeTrace) -> None:
        """Broadcast a notification for the Simulate result.

        The payoff moment of the whole tool used to be one line of body text
        sitting above the Result panel (see docs/KNOWN_ISSUES.md) - make it
        unmissable instead. When 'curated' silently fell back to a weaker
        controller because an edit made the packaged gait no longer fit, say so
        explicitly: that used to look identical to "nothing happened."
        """
        used = trace.meta.controller if trace.meta is not None else None
        if self.session.controller == "curated" and used is not None:
            if not used.endswith("controller.json"):
                from creature_lab.zoo import zoo_optimized_controller

                try:
                    packaged_exists = (
                        zoo_optimized_controller(self.session.creature.name) is not None
                    )
                except KeyError:
                    packaged_exists = False
                if packaged_exists:
                    self.notify(
                        "Curated gait fell back",
                        "This body no longer fits the packaged walking gait, so "
                        f"'curated' used {self.session.describe_controller()} "
                        "instead - see Run for what changed.",
                        "yellow",
                    )
                    return
        summary = summarize_episode(trace, self.session.task, self.session.creature)
        headline = self._progress_headline(summary, self.session.task)
        self.notify("Simulation complete", f"{headline}. Score: {trace.score:+.3f}.", "blue")

    def _consume_ended_job(self, status: JobStatus) -> None:
        self._pending_job_kind = None
        self._pending_signature = None
        self._replay_export_client = None
        if status.state == "cancelled":
            self.session.last_message = "Cancelled."
        else:
            self.session.last_message = f"Failed: {status.error}"
        self._update_status()

    # -- Test phase: playback -----------------------------------------------------

    def _tick_playback(self, dt: float) -> None:
        if self.playback.advance(dt):
            frame = self.playback.current_frame()
            if frame is not None:
                self.on_playback_frame(frame)
            self._sync_playback_widgets()

    def _rebuild_playback_controls(self) -> None:
        self._remove_folder("_playback_folder")
        with self._test_tab:
            self._playback_folder = self.gui.add_folder(
                "Playback", expand_by_default=True, order=40
            )
        self._playback_slider = None
        self._playback_play_button = None
        with self._playback_folder:
            if self.playback.trace is None:
                self.gui.add_markdown("Run **Simulate** to get a trace to play back.")
                return
            self._playback_play_button = self.gui.add_button(
                "Play / Pause",
                icon="player-pause" if self.playback.playing else "player-play",
            )
            self._playback_play_button.on_click(lambda _event: self._toggle_playback())
            self._playback_slider = self.gui.add_slider(
                "Frame",
                min=0,
                max=max(0, self.playback.frame_count - 1),
                step=1,
                initial_value=self.playback.frame_index,
            )
            self._playback_slider.on_update(
                lambda event: self._seek_playback(int(event.target.value))
            )
            step_back = self.gui.add_button("Step -1", icon="chevron-left")
            step_back.on_click(lambda _event: self._step_playback(-1))
            step_fwd = self.gui.add_button("Step +1", icon="chevron-right")
            step_fwd.on_click(lambda _event: self._step_playback(1))
            restart_button = self.gui.add_button("Restart", icon="player-skip-back")
            restart_button.on_click(lambda _event: self._restart_playback())
            if self._advanced:
                loop_checkbox = self.gui.add_checkbox("Loop", self.playback.loop)
                loop_checkbox.on_update(
                    lambda event: setattr(self.playback, "loop", bool(event.target.value))
                )
                speed = self.gui.add_dropdown(
                    "Speed", ["0.25x", "0.5x", "1x", "2x"], initial_value="1x"
                )
                speed.on_update(
                    lambda event: setattr(
                        self.playback, "speed", float(event.target.value.rstrip("x"))
                    )
                )

    def _sync_playback_widgets(self) -> None:
        if self._playback_slider is not None:
            self._playback_slider.value = self.playback.frame_index
        if self._playback_play_button is not None:
            self._playback_play_button.icon = (
                "player-pause" if self.playback.playing else "player-play"
            )

    def _toggle_playback(self) -> None:
        self.playback.toggle()
        self._sync_playback_widgets()

    def _seek_playback(self, frame_index: int) -> None:
        self.playback.seek(frame_index)
        frame = self.playback.current_frame()
        if frame is not None:
            self.on_playback_frame(frame)

    def _step_playback(self, delta: int) -> None:
        self.playback.step(delta)
        self._sync_playback_widgets()
        frame = self.playback.current_frame()
        if frame is not None:
            self.on_playback_frame(frame)

    def _restart_playback(self) -> None:
        self.playback.to_start()
        self._sync_playback_widgets()
        frame = self.playback.current_frame()
        if frame is not None:
            self.on_playback_frame(frame)

    # -- Test phase: scorecard + diagnosis ----------------------------------------

    @staticmethod
    def _progress_headline(summary: EpisodeSummary, task: TaskSpec) -> str:
        """A concrete, plain-language description of what happened, leading with
        whichever objective the task's reward actually weights.

        The raw score alone misleads: an energy penalty (or a task like "stay
        balanced" that is mostly penalties) can put a run that clearly succeeded -
        walked toward the goal, stayed upright - into negative territory, which
        reads as pure failure to a first-time user even though the creature did
        what was asked. Leading with the concrete outcome fixes that without
        hiding or softening the actual score, shown right below it.
        """
        reward = task.reward
        bits: list[str] = []
        if reward.target_distance != 0.0 and summary.target_progress is not None:
            if summary.target_progress >= 0:
                bits.append(f"moved {summary.target_progress:.2f} m closer to the target")
            else:
                bits.append(f"moved {-summary.target_progress:.2f} m farther from the target")
        elif reward.forward_distance != 0.0:
            direction = "forward" if summary.forward_displacement >= 0 else "backward"
            bits.append(f"moved {abs(summary.forward_displacement):.2f} m {direction}")
        if summary.fell is not None:
            bits.append("fell" if summary.fell else "stayed upright")
        if not bits:
            bits.append(f"ran for {summary.duration:.1f}s")
        headline = "; ".join(bits)
        return headline[0].upper() + headline[1:]

    def _rebuild_metrics_controls(self) -> None:
        self._remove_folder("_metrics_folder")
        self._autopsy_button = None
        self._replay_export_button = None
        with self._test_tab:
            # order=20: pinned right after Run regardless of rebuild churn - the
            # payoff of the whole tool shouldn't require scrolling past Task/
            # Playback to see (see docs/KNOWN_ISSUES.md). Folders re-append to the
            # end of their container on every rebuild without an explicit order.
            self._metrics_folder = self.gui.add_folder("Result", expand_by_default=True, order=20)
        with self._metrics_folder:
            if self._last_trace is None:
                self.gui.add_markdown(
                    "Run **Simulate** to see score, displacement, and failure diagnosis here."
                )
                return
            trace = self._last_trace
            summary = summarize_episode(trace, self.session.task, self.session.creature)
            result = diagnose(trace, self.session.creature, self.session.task)

            headline = self._progress_headline(summary, self.session.task)
            self.gui.add_markdown(
                f"### {headline}\nScore: {summary.final_score:+.3f} · {summary.duration:.1f}s"
            )
            lines = [
                f"- Net displacement: {summary.net_displacement:.3f} m",
                f"- Joint motion (sum |change in angle|): {summary.total_joint_motion:.1f}",
            ]
            if summary.target_progress is not None:
                lines.append(f"- Target progress: {summary.target_progress:+.3f} m")
            if summary.component_scores:
                breakdown = ", ".join(
                    f"{key}={value:.3f}" for key, value in summary.component_scores.items()
                )
                lines.append(f"- Score breakdown: {breakdown}")
            self.gui.add_markdown("\n".join(lines))

            if result.patterns:
                self.gui.add_markdown("**Diagnosis**")
                for pattern, explanation, suggestion in zip(
                    result.patterns, result.explanations, result.suggestions, strict=True
                ):
                    self._render_diagnosis_card(pattern, explanation, suggestion)
            else:
                self.gui.add_markdown("No failure patterns detected by these checks.")

            fall_time = result.metrics.get("fall_time", -1.0)
            if fall_time >= 0 and trace.frames:
                fall_index = min(
                    range(len(trace.frames)), key=lambda i: abs(trace.frames[i].t - fall_time)
                )
                jump = self.gui.add_button(f"Show first fall ({fall_time:.2f}s)")
                jump.on_click(lambda _event: self._seek_to_event(fall_index))

            if self.on_start_replay_export is not None:
                self._replay_export_button = self.gui.add_button("Download recorded 3D replay")
                self._replay_export_button.on_click(self._start_replay_export)
                self._replay_export_button.disabled = self.job_manager.is_running
                self.gui.add_markdown(
                    "Experimental standalone viewer; this records poses and does not rerun physics."
                )

            if self.on_start_autopsy is not None:
                self.gui.add_markdown(
                    "**Explain this result:** run the selected controller, a distinct curated "
                    "reference when available, and five seeded mass/friction checks "
                    "(six or seven simulations)."
                )
                self._autopsy_button = self.gui.add_button("Explain failure", icon="search")
                self._autopsy_button.on_click(lambda _event: self._start_autopsy())
                self._autopsy_button.disabled = self.job_manager.is_running
                if self._last_autopsy is not None and self._autopsy_report_dir is not None:
                    autopsy = self._last_autopsy
                    self.gui.add_markdown(
                        f"**Candidate explanation:** {autopsy.primary_cause} "
                        f"({autopsy.confidence} heuristic evidence strength).\n\n"
                        f"{autopsy.summary}\n\nThis is not proof of causation.\n\n"
                        + "\n".join(f"- {item.name}: {item.detail}" for item in autopsy.evidence)
                    )
                    download = self.gui.add_button(
                        "Download analysis and verified pack", icon="download"
                    )
                    download.on_click(self._download_autopsy)

            if summary.warnings:
                self.gui.add_markdown(
                    "**Warnings**\n" + "\n".join(f"- {warning}" for warning in summary.warnings)
                )

    def _render_diagnosis_card(self, pattern: str, explanation: str, suggestion: str) -> None:
        severity = self.session.diagnosis_severity(pattern)
        tag = _SEVERITY_TAG.get(severity, "")
        self.gui.add_markdown(f"{tag} **{pattern}**\n\n{explanation}\n\nSuggestion: {suggestion}")
        fix_label = self.session.diagnosis_fix_label(pattern)
        if fix_label is not None:
            apply_button = self.gui.add_button(f"Apply fix: {fix_label}", icon="wand")
            apply_button.on_click(lambda _event, p=pattern: self._apply_diagnosis_fix(p))

    def _seek_to_event(self, index: int) -> None:
        self.playback.pause()
        self._seek_playback(index)
        self._sync_playback_widgets()

    def _download_autopsy(self, event: Any) -> None:
        import io
        import zipfile

        report_dir = self._autopsy_report_dir
        client = getattr(event, "client", None)
        if report_dir is None or client is None:
            self.session.last_message = "Analysis download is unavailable for this client."
            self._update_status()
            return
        try:
            data = io.BytesIO()
            with zipfile.ZipFile(data, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for path in sorted(report_dir.rglob("*")):
                    if path.is_file() and not path.is_symlink():
                        archive.write(path, path.relative_to(report_dir).as_posix())
            client.send_file_download("creature-lab-analysis.zip", data.getvalue())
        except OSError as exc:
            self.session.last_message = f"Could not prepare analysis download: {exc}"
            self._update_status()

    def _apply_diagnosis_fix(self, pattern: str) -> None:
        self._history_action(lambda: self.session.apply_diagnosis_fix(pattern))

    # -- Test phase: robustness -----------------------------------------------------

    def _rebuild_robustness_controls(self) -> None:
        self._remove_folder("_robustness_folder")
        with self._test_tab:
            self._robustness_folder = self.gui.add_folder(
                "Robustness", expand_by_default=False, order=50
            )
        with self._robustness_folder:
            self.gui.add_markdown(
                "Re-simulate under small seeded mass/friction perturbations. A wide score "
                "spread or high fail rate means the result is fragile, not robust."
            )
            level_dropdown = None
            trials_slider = None
            mass_jitter_slider = None
            friction_jitter_slider = None
            if self._advanced:
                trials_slider = self.gui.add_slider(
                    "Trials", min=2, max=50, step=1, initial_value=10
                )
                mass_jitter_slider = self.gui.add_slider(
                    "Mass jitter", min=0.0, max=0.3, step=0.01, initial_value=0.05
                )
                friction_jitter_slider = self.gui.add_slider(
                    "Friction jitter", min=0.0, max=0.3, step=0.01, initial_value=0.05
                )
            else:
                level_dropdown = self.gui.add_dropdown(
                    "Level", list(ROBUSTNESS_LEVELS), initial_value="Standard"
                )
            self._robustness_button = self.gui.add_button("Run robustness sweep")
            self._robustness_result_md = self.gui.add_markdown("")

            def _run(_event: Any) -> None:
                trials = (
                    int(trials_slider.value)
                    if trials_slider is not None
                    else ROBUSTNESS_LEVELS[level_dropdown.value]
                )
                mass = float(mass_jitter_slider.value) if mass_jitter_slider is not None else 0.05
                friction = (
                    float(friction_jitter_slider.value)
                    if friction_jitter_slider is not None
                    else 0.05
                )
                self._start_robustness(trials, mass, friction)

            self._robustness_button.on_click(_run)
            self._render_robustness_result()

    def _render_robustness_result(self) -> None:
        if self._robustness_result_md is None:
            return
        result = self._last_robustness
        if result is None:
            self._robustness_result_md.content = ""
            return
        lines = [
            plain_language_verdict(result),
            "",
            f"- Mean score: **{result.mean_score:.4f}** (std {result.std_score:.4f})",
            f"- Range: {result.min_score:.4f} to {result.max_score:.4f}",
            f"- Fail rate: {result.fail_rate:.0%}",
        ]
        self._robustness_result_md.content = "\n".join(lines)

    # -- Test phase: qualify ---------------------------------------------------------

    def _rebuild_qualify_controls(self) -> None:
        self._remove_folder("_qualify_folder")
        with self._test_tab:
            self._qualify_folder = self.gui.add_folder("Qualify", expand_by_default=False, order=60)
        with self._qualify_folder:
            self.gui.add_markdown(
                "Combine a baseline run, a robustness sweep, and (for **backend-portable**) "
                "a cross-backend comparison into one pass/fail result with a named blocker "
                "and a recommended next test."
            )
            profile_dropdown = self.gui.add_dropdown(
                "Profile", list(BUILTIN_PROFILES), initial_value="basic-locomotion"
            )
            self._qualify_button = self.gui.add_button("Run qualification", icon="rubber-stamp")
            self._qualify_result_md = self.gui.add_markdown("")

            def _run(_event: Any) -> None:
                self._start_qualify(profile_dropdown.value)

            self._qualify_button.on_click(_run)
            self._render_qualify_result()

    def _render_qualify_result(self) -> None:
        if self._qualify_result_md is None:
            return
        result = self._last_qualification
        if result is None:
            self._qualify_result_md.content = ""
            return
        verdict = "**PASS**" if result.passed else "**FAIL**"
        lines = [f"### Qualification: {verdict} ({result.profile})"]
        for check in result.checks:
            mark = "PASS" if check.passed else "FAIL"
            lines.append(f"- `{mark}` **{check.name}**: {check.detail}")
        if result.primary_blocker is not None:
            lines.append("")
            lines.append(f"**Primary blocker:** {result.primary_blocker}")
            lines.append(f"**Recommended next test:** {result.recommended_next_test}")
        self._qualify_result_md.content = "\n".join(lines)

    # -- Test phase: run history -----------------------------------------------------

    def _rebuild_run_history_controls(self) -> None:
        self._remove_folder("_run_history_folder")
        with self._test_tab:
            self._run_history_folder = self.gui.add_folder(
                "Run History", expand_by_default=False, order=70
            )
        with self._run_history_folder:
            runs = list_recent_runs(self.runs_dir, limit=8)
            self._run_history_by_label = {}
            if not runs:
                self.gui.add_markdown("No saved runs yet. Simulate to create one.")
                return
            labels = self._unique_run_history_labels(runs)
            for label, run in zip(labels, runs, strict=True):
                self._run_history_by_label[label] = run
            dropdown = self.gui.add_dropdown("Run", labels, initial_value=labels[0])
            restore_button = self.gui.add_button("Restore design", icon="download")
            replay_button = self.gui.add_button("Replay", icon="player-play")

            restore_button.on_click(lambda _event: self._restore_run(dropdown.value))
            replay_button.on_click(lambda _event: self._replay_run(dropdown.value))
            if len(labels) > 1:
                other = self.gui.add_dropdown("Compare with", labels, initial_value=labels[1])
                comparison = self.gui.add_markdown("")
                compare_button = self.gui.add_button("Compare saved results")
                compare_button.on_click(
                    lambda _event: self._compare_saved_runs(dropdown.value, other.value, comparison)
                )
                export_button = self.gui.add_button("Download comparison HTML")
                export_button.on_click(
                    lambda event: self._download_comparison(event, dropdown.value, other.value)
                )

    def _compare_saved_runs(self, left_label: str, right_label: str, output: Any) -> None:
        left = self._run_history_by_label.get(left_label)
        right = self._run_history_by_label.get(right_label)
        if left is None or right is None:
            return
        try:
            from creature_lab.reports import build_comparison, build_report

            a = build_report(left.run_dir)
            b = build_report(right.run_dir)
            differences = build_comparison(a, b)["conditions_changed_or_unknown"]
            conditions = ", ".join(differences) if differences else "none detected"

            def fall_label(fell: bool | None) -> str:
                return "fall unknown" if fell is None else "fell" if fell else "no fall detected"

            output.content = (
                f"**{left.run_id}**: score {a['score']:+.3f}, "
                f"forward {a['summary']['forward_displacement']:+.3f} m, "
                f"{fall_label(a['summary']['fell'])}\n\n"
                f"**{right.run_id}**: score {b['score']:+.3f}, "
                f"forward {b['summary']['forward_displacement']:+.3f} m, "
                f"{fall_label(b['summary']['fell'])}\n\n"
                f"**Changed or unknown:** {conditions}. Compare scores only when task, "
                "backend, and evaluation conditions are compatible."
            )
        except (OSError, ValueError) as exc:
            output.content = f"Could not compare these saved runs: {exc}"

    def _download_comparison(self, event: Any, left_label: str, right_label: str) -> None:
        from creature_lab.reports import build_comparison, build_report_bundle
        from creature_lab.reports_html import comparison_to_html

        left = self._run_history_by_label.get(left_label)
        right = self._run_history_by_label.get(right_label)
        client = getattr(event, "client", None)
        if left is None or right is None or client is None:
            return
        try:
            a, trace_a, creature_a, _ = build_report_bundle(left.run_dir)
            b, trace_b, creature_b, _ = build_report_bundle(right.run_dir)
            page = comparison_to_html(
                a,
                b,
                build_comparison(a, b),
                creature_a=creature_a,
                trace_a=trace_a,
                creature_b=creature_b,
                trace_b=trace_b,
            )
            client.send_file_download("creature-lab-comparison.html", page.encode("utf-8"))
        except (OSError, ValueError) as exc:
            self.session.last_message = f"Could not prepare comparison: {exc}"
            self._update_status()

    @staticmethod
    def _run_history_label(run: RunSummary) -> str:
        age = max(0.0, time.time() - run.saved_at)
        if age < 60:
            when = f"{int(age)}s ago"
        elif age < 3600:
            when = f"{int(age / 60)}m ago"
        else:
            when = f"{age / 3600:.1f}h ago"
        return f"{run.creature_name} · {run.task_name} · score {run.score:.3f} · {when}"

    @staticmethod
    def _unique_run_history_labels(runs: list[RunSummary]) -> list[str]:
        """Dropdown option values must be unique - Viser's underlying Mantine Select
        throws (crashing the whole editor GUI, not just the dropdown) if two options
        share a value. Two runs of the same creature/task easily produce an identical
        base label (same score, and 'time ago' is rounded to whole seconds/minutes/
        tenths of an hour) - e.g. simply re-running the same example twice. Disambiguate
        with the run id, but only for labels that actually collide, so the common case
        stays clean."""
        base_labels = [BuildControls._run_history_label(run) for run in runs]
        counts = Counter(base_labels)
        return [
            label if counts[label] == 1 else f"{label} · {run.run_id}"
            for label, run in zip(base_labels, runs, strict=True)
        ]

    def _restore_run(self, label: str) -> None:
        run = self._run_history_by_label.get(label)
        if run is None:
            return
        self._safe(
            lambda: self.session.restore_from_run(
                run.run_dir / "creature.json", run.run_dir / "task.json"
            ),
            rebuild_body=True,
            rebuild_part=True,
            rebuild_motion=True,
            rebuild_task=True,
        )

    def _replay_run(self, label: str) -> None:
        run = self._run_history_by_label.get(label)
        if run is None:
            return
        try:
            creature, task, trace = load_run(run.run_dir)
            if spec_hash(creature) != spec_hash(self.session.creature) or (
                task is not None and spec_hash(task) != spec_hash(self.session.task)
            ):
                self.session.last_message = (
                    "Restore this run's design and task before replaying it."
                )
                self._update_status()
                return
        except Exception as exc:
            self.session.last_message = f"Could not load trace: {exc}"
            self._update_status()
            return
        self._last_trace = trace
        self._last_run_signature = self._current_run_signature()
        self._last_autopsy = None
        self._autopsy_report_dir = None
        self._last_robustness = None
        self._last_qualification = None
        self.playback.load(trace)
        first = self.playback.current_frame()
        if first is not None:
            self.on_playback_frame(first)
        self.session.last_message = f"Loaded replay of run {run.run_id}"
        self._rebuild_playback_controls()
        self._rebuild_metrics_controls()
        self._update_status()

    # -- onboarding ---------------------------------------------------------------

    #: Reserved for presets whose curated behavior cannot yet serve a movement goal.
    #: The 12-DOF humanoid left this set after gaining its measured walking setup.
    def _build_onboarding_panel(self) -> None:
        """First-run creature x goal picker, rendered inline (not as a modal).

        See ``_build`` for why this must not be a modal. Start applies the choice
        and removes the panel; Skip just removes it - both leave a normal editor.
        """
        creature_labels = presets.preset_labels()
        goal_labels = presets.onboarding_goal_labels()
        self._onboarding_folder = self.gui.add_folder("Get started", expand_by_default=True)
        with self._onboarding_folder:
            self.gui.add_markdown(
                "Pick a creature and a goal to get started. You can change everything "
                "later — this just picks a reasonable starting point."
            )
            creature_dropdown = self.gui.add_dropdown(
                "Creature", creature_labels, initial_value=creature_labels[0]
            )
            goal_dropdown = self.gui.add_dropdown("Goal", goal_labels, initial_value=goal_labels[0])
            start_button = self.gui.add_button("Start", icon="player-play", color="blue")
            skip_button = self.gui.add_button("Skip")

            def _start(_event: Any) -> None:
                creature_key = presets.preset_name_from_label(creature_dropdown.value)
                goal_key = presets.onboarding_goal_key_from_label(goal_dropdown.value)
                self._remove_folder("_onboarding_folder")
                self._safe(
                    lambda: self.session.apply_onboarding(creature_key, goal_key),
                    rebuild_body=True,
                    rebuild_part=True,
                    rebuild_motion=True,
                    rebuild_task=True,
                )

            start_button.on_click(_start)
            skip_button.on_click(lambda _event: self._remove_folder("_onboarding_folder"))

    # -- history / snapshots / destructive confirmations ------------------------

    def _refresh_restore_options(self) -> None:
        if self._restore_dropdown is not None:
            self._restore_dropdown.options = ["(none)", *self.session.snapshot_names()]

    def _restore_selected_snapshot(self) -> None:
        if self._restore_dropdown is None:
            return
        name = self._restore_dropdown.value
        if name and name != "(none)":
            self._history_action(lambda: self.session.restore_snapshot(name))

    def _confirm_delete(self) -> None:
        impact = self.session.describe_delete_impact()
        if not impact:
            self.session.last_message = "Root part cannot be deleted."
            self._update_status()
            return
        part = self.session.selected_part_id
        children = [pid for pid in impact if pid != part]
        with self.gui.add_modal("Delete part?") as modal:
            if children:
                self.gui.add_markdown(
                    f"Delete **{part}** and its {len(children)} child part(s)?\n\n"
                    f"`{', '.join(children)}`"
                )
            else:
                self.gui.add_markdown(f"Delete **{part}**?")
            confirm = self.gui.add_button("Delete", icon="trash", color="red")
            cancel = self.gui.add_button("Cancel")

            def _do(_event: Any) -> None:
                modal.close()
                self._safe(
                    self.session.delete_selected_part,
                    rebuild_body=False,
                    rebuild_part=True,
                    rebuild_motion=True,
                    rebuild_task=False,
                )

            confirm.on_click(_do)
            cancel.on_click(lambda _event: modal.close())

    def _confirm_reload(self) -> None:
        if not self.session.is_dirty:
            self._safe(
                self.session.reload_project,
                rebuild_body=True,
                rebuild_part=True,
                rebuild_motion=True,
                rebuild_task=True,
            )
            return
        with self.gui.add_modal("Reload from disk?") as modal:
            self.gui.add_markdown(
                "You have unsaved edits. Reloading discards them and cannot be undone."
            )
            confirm = self.gui.add_button("Discard and reload", icon="refresh-dot", color="red")
            cancel = self.gui.add_button("Cancel")

            def _do(_event: Any) -> None:
                modal.close()
                self._safe(
                    self.session.reload_project,
                    rebuild_body=True,
                    rebuild_part=True,
                    rebuild_motion=True,
                    rebuild_task=True,
                )

            confirm.on_click(_do)
            cancel.on_click(lambda _event: modal.close())

    def _confirm_overwrite_project(self) -> None:
        with self.gui.add_modal("Overwrite project files?") as modal:
            self.gui.add_markdown(
                "This replaces external creature/task edits with the version currently "
                "shown in the editor."
            )
            confirm = self.gui.add_button("Overwrite files", icon="device-floppy", color="red")
            cancel = self.gui.add_button("Cancel")

            def _do(_event: Any) -> None:
                modal.close()
                self._safe(
                    self.session.overwrite_project,
                    rebuild_body=False,
                    rebuild_part=False,
                    rebuild_motion=False,
                    rebuild_task=False,
                    preview="none",
                )

            confirm.on_click(_do)
            cancel.on_click(lambda _event: modal.close())

    # -- status -----------------------------------------------------------------

    def _update_status(self) -> None:
        status = self.session.status()
        metrics = self.session.preview_metrics()
        lines = []
        if self.session.external_change_pending:
            lines.append(
                "**Files changed on disk.** Reload them, or explicitly click "
                "**Overwrite disk with editor**. Autosave is paused to prevent data loss."
            )
            lines.append("")
        dirty = " · unsaved changes" if self.session.is_dirty else ""
        lines.extend(
            [
                f"**{self.session.last_message}**{dirty}",
                "",
                f"- Creature: `{self.session.creature.name}`",
                "- Parts/joints/motors: "
                f"{int(metrics['parts'])}/{int(metrics['joints'])}/{int(metrics['motors'])}",
                f"- CoM height: {metrics['com_z']:.2f} m",
                f"- Support width: {metrics['support_width']:.2f} m",
            ]
        )
        if status.errors:
            lines.append("")
            lines.append("**Errors**")
            lines.extend(f"- {error}" for error in status.errors)
        if status.warnings:
            lines.append("")
            lines.append("**Warnings**")
            lines.extend(f"- {warning}" for warning in status.warnings[:4])
        if self._message is not None:
            self._message.content = "\n".join(lines)
        if self._controller_resolution_md is not None:
            resolved = self.session.describe_controller()
            self._controller_resolution_md.content = f"Runs: **{resolved}**"
        if self._simulate_button is not None:
            self._simulate_button.disabled = not status.ok or self.job_manager.is_running
        if self._undo_button is not None:
            self._undo_button.disabled = not self.session.can_undo
        if self._redo_button is not None:
            self._redo_button.disabled = not self.session.can_redo
