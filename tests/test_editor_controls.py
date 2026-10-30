"""Smoke tests for the Viser build panel using a fake GUI.

Viser needs a browser, so these exercise ``BuildControls`` against a minimal fake that
mimics the handful of ``gui.add_*`` methods the panel uses. That catches attribute/API
mistakes in the layout code (wrong method names, bad kwargs, broken rebuild paths)
without a real server. ``EditorJobManager``/``EditorPlayback`` are used for real here
(they have no GUI/physics dependency), so async simulate/robustness and playback are
exercised end-to-end against real background threads.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest

from creature_lab.editor import presets
from creature_lab.editor.controls import BuildControls, _same_replay_scene
from creature_lab.editor.jobs import EditorJobManager, JobCancelled
from creature_lab.editor.playback import EditorPlayback
from creature_lab.editor.session import AVAILABLE_CONTROLLERS, EditorSession, SessionStatus
from creature_lab.qualification import QualificationCheck, QualificationResult
from creature_lab.robustness import RobustnessResult, RobustnessTrial
from creature_lab.runs import RunSummary, save_run
from creature_lab.schema import EpisodeSummary, EpisodeTrace, TaskSpec


def test_replay_scene_accepts_gait_edits_but_rejects_body_edits():
    session = EditorSession()
    original = session.creature
    session.use_editable_gait()
    session.update_selected_motor(amplitude=0.1)
    assert _same_replay_scene(original, session.creature)
    session.update_selected_part(mass=10.0)
    assert not _same_replay_scene(original, session.creature)


def test_comparison_playback_advances_and_stops_at_end():
    controls, _, _, _ = _make_controls(EditorSession())
    seeks = []
    controls.on_seek_comparison = seeks.append
    controls._comparing = True
    controls._comparison_duration = 2.0
    controls._toggle_comparison()
    controls.tick(1.0)
    assert seeks[-1] == pytest.approx(0.5)
    assert controls.comparison_playing
    controls.tick(1.0)
    assert seeks[-1] == 1.0
    assert not controls.comparison_playing


def _fake_trace(creature_name: str = "quadruped", score: float = 0.5) -> EpisodeTrace:
    return EpisodeTrace.model_validate(
        {
            "run_id": "fake",
            "creature_name": creature_name,
            "task_name": "crawl_forward",
            "backend": "pybullet",
            "score": score,
            "frames": [
                {"t": 0.0, "parts": {"torso": {"position": (0.0, 0.0, 0.1)}}, "score": 0.0},
                {"t": 0.1, "parts": {"torso": {"position": (0.2, 0.0, 0.1)}}, "score": score},
            ],
        }
    )


def _fake_robustness_result() -> RobustnessResult:
    trials = [
        RobustnessTrial(seed=i, score=1.0, fell=False, mass_scale=1.0, friction_scale=1.0)
        for i in range(3)
    ]
    return RobustnessResult(
        trials=trials, mean_score=1.0, std_score=0.0, min_score=1.0, max_score=1.0, fail_rate=0.0
    )


def _fake_qualification_result(passed: bool = True) -> QualificationResult:
    checks = [QualificationCheck("Baseline task success", passed, "score=0.5, fell=False")]
    return QualificationResult(
        profile="basic-locomotion",
        passed=passed,
        checks=checks,
        primary_blocker=None if passed else "Baseline task success",
        recommended_next_test=None if passed else "Run diagnose.",
    )


class _Handle:
    """A stand-in for any Viser GUI handle; also usable as a context manager."""

    def __init__(self, value: Any = None) -> None:
        self.value = value
        self.content = ""
        self.disabled = False
        self.visible = True
        self.animated = False
        self.icon = None
        self.kind: str | None = None
        self.text: str | None = None
        self.options: list[str] = []
        self._update = None
        self._click = None

    @property
    def target(self) -> _Handle:
        return self  # mirrors Viser's real GuiEvent.target

    def on_update(self, fn):  # noqa: ANN001
        self._update = fn

    def on_click(self, fn):  # noqa: ANN001
        self._click = fn

    def click(self) -> None:
        if self._click is not None:
            self._click(self)

    def update(self, value: Any) -> None:
        """Simulate a client-driven change: set value, then fire on_update."""
        self.value = value
        if self._update is not None:
            self._update(self)

    def remove(self) -> None:
        pass

    def close(self) -> None:
        pass

    def __enter__(self) -> _Handle:
        return self

    def __exit__(self, *exc: Any) -> bool:
        return False


class _TabGroup:
    def add_tab(self, label: str, icon: str | None = None) -> _Handle:
        return _Handle()

    def remove(self) -> None:
        pass


class _FakeGui:
    """Enough of ``viser.GuiApi`` to build the panel."""

    def __init__(self) -> None:
        self.handles: list[_Handle] = []
        self.modals: list[_Handle] = []

    def _mk(self, value: Any = None) -> _Handle:
        handle = _Handle(value)
        self.handles.append(handle)
        return handle

    def add_markdown(self, content: str = "", **_k: Any) -> _Handle:
        return self._mk(content)

    def add_folder(self, label: str, expand_by_default: bool = True, **_k: Any) -> _Handle:
        handle = self._mk()
        handle.kind = "folder"
        handle.text = label
        return handle

    def add_tab_group(self, **_k: Any) -> _TabGroup:
        return _TabGroup()

    def add_button_group(self, label: str, options: list[str], **_k: Any) -> _Handle:
        handle = self._mk(options[0] if options else None)
        handle.kind = "button_group"
        handle.text = label
        handle.options = list(options)
        return handle

    def add_text(self, label: str, initial_value: str = "", **_k: Any) -> _Handle:
        return self._mk(initial_value)

    def add_button(self, label: str, **_k: Any) -> _Handle:
        handle = self._mk()
        handle.icon = _k.get("icon")
        handle.kind = "button"
        handle.text = label
        return handle

    def add_checkbox(self, label: str, initial_value: bool = False, **_k: Any) -> _Handle:
        return self._mk(initial_value)

    def add_dropdown(
        self, label: str, options: list[str], initial_value: Any = None, **_k: Any
    ) -> _Handle:
        fallback = options[0] if options else None
        handle = self._mk(initial_value if initial_value is not None else fallback)
        handle.options = list(options)
        return handle

    def add_slider(
        self,
        label: str,
        min: float = 0,
        max: float = 1,
        step: float = 1,
        initial_value: Any = 0,
        **_k: Any,
    ) -> _Handle:
        return self._mk(initial_value)

    def add_rgb(self, label: str, initial: Any = (0, 0, 0), **_k: Any) -> _Handle:
        return self._mk(initial)

    def add_modal(self, title: str, **_k: Any) -> _Handle:
        handle = _Handle()
        handle.kind = "modal"
        handle.text = title
        self.modals.append(handle)
        return handle

    def add_progress_bar(self, value: float = 0.0, **_k: Any) -> _Handle:
        handle = self._mk(value)
        handle.visible = _k.get("visible", True)
        handle.animated = _k.get("animated", False)
        return handle


def _wait_until(predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("condition was not met within timeout")


def _wait_for_job_consumed(controls: BuildControls, is_done) -> None:
    """Drive ``tick()`` until ``is_done()`` (a zero-arg predicate) is true."""

    def _tick_and_check() -> bool:
        controls.tick(0.0)
        return is_done()

    _wait_until(_tick_and_check)


def _make_controls(
    session: EditorSession,
    *,
    on_start_simulate=None,
    on_start_robustness=None,
    on_start_qualify=None,
    on_start_refit_gait=None,
    runs_dir: Path | None = None,
    show_onboarding: bool = False,
) -> tuple[BuildControls, list[str], EditorJobManager, EditorPlayback]:
    events: list[str] = []
    job_manager = EditorJobManager()
    playback = EditorPlayback()

    def _default_start_simulate() -> None:
        job_manager.start(lambda reporter: (_fake_trace(), Path("runs/fake")))

    def _default_start_robustness(trials: int, mass: float, friction: float) -> None:
        job_manager.start(lambda reporter: _fake_robustness_result())

    def _default_start_qualify(profile_name: str) -> None:
        job_manager.start(lambda reporter: _fake_qualification_result())

    def _default_start_refit_gait(attempts: int) -> None:
        job_manager.start(lambda reporter: session.creature.model_copy(deep=True))

    controls = BuildControls(
        _FakeGui(),
        session,
        job_manager=job_manager,
        playback=playback,
        on_preview=lambda: events.append("preview_full"),
        on_preview_light=lambda: events.append("preview_light"),
        on_start_simulate=on_start_simulate or _default_start_simulate,
        on_start_robustness=on_start_robustness or _default_start_robustness,
        on_start_qualify=on_start_qualify or _default_start_qualify,
        on_start_refit_gait=on_start_refit_gait or _default_start_refit_gait,
        on_playback_frame=lambda frame: events.append("frame"),
        runs_dir=runs_dir or Path("runs"),
        show_onboarding=show_onboarding,
    )
    # These tests inject a fake re-fit implementation without the optional package.
    controls._has_cmaes = True
    return controls, events, job_manager, playback


def test_panel_builds_in_basic_mode():
    controls, _, _, _ = _make_controls(EditorSession())
    assert controls._design_tab is not None
    assert controls._motion_tab is not None
    assert controls._test_tab is not None


def test_back_to_design_restores_the_editable_preview():
    controls, events, _, playback = _make_controls(EditorSession())
    playback.load(_fake_trace())
    controls._show_phase("Test")

    controls._show_phase("Design")

    assert controls._design_tab.visible is True
    assert controls._motion_tab.visible is False
    assert controls._test_tab.visible is False
    assert playback.playing is False
    assert events[-1] == "preview_full"


def test_panel_builds_in_advanced_mode():
    session = EditorSession()
    session.set_mode("advanced")
    controls, _, _, _ = _make_controls(session)
    assert controls._body_folder is not None


def test_controller_dropdown_defaults_to_session_controller_and_updates_it():
    session = EditorSession()
    session.set_controller("cpg")
    controls, _, _, _ = _make_controls(session)

    dropdown = next(h for h in controls.gui.handles if h.options == list(AVAILABLE_CONTROLLERS))
    assert dropdown.value == "cpg"

    dropdown.update("target_seek")

    assert session.controller == "target_seek"


def test_scene_selection_uses_the_light_preview_path():
    controls, events, _, _ = _make_controls(EditorSession())

    controls.scene_selected("leg_0l")

    assert "preview_light" in events
    assert "preview_full" not in events


def test_structural_edit_uses_the_full_preview_path():
    session = EditorSession()
    controls, events, _, _ = _make_controls(session)
    session.select_part("torso")

    controls._safe(
        session.add_limb,
        rebuild_body=False,
        rebuild_part=True,
        rebuild_motion=True,
        rebuild_task=False,
    )

    assert "preview_full" in events


def test_motor_selection_skips_preview_entirely():
    session = EditorSession()
    controls, events, _, _ = _make_controls(session)

    controls._safe(
        lambda: session.select_motor(session.motor_ids()[-1]),
        rebuild_body=False,
        rebuild_part=False,
        rebuild_motion=True,
        rebuild_task=False,
        preview="none",
    )

    assert "preview_full" not in events
    assert "preview_light" not in events


def test_delete_confirmation_modal_builds_for_non_root_part():
    session = EditorSession()
    session.select_part("leg_0l")
    controls, _, _, _ = _make_controls(session)

    controls._confirm_delete()  # opens a modal (fake) — must not raise


def test_custom_loaded_creature_renders_body_placeholder(tmp_path):
    out = tmp_path / "c.json"
    EditorSession(template="worm", out_path=out).save()
    session = EditorSession.from_path(out)
    assert session.template == "custom"

    controls, _, _, _ = _make_controls(session)  # custom body branch
    assert controls._body_folder is not None


# -- async simulate ----------------------------------------------------------------


def test_tick_consumes_completed_simulate_job_and_loads_playback():
    controls, events, job_manager, playback = _make_controls(EditorSession())
    controls._start_simulate()
    assert controls._pending_job_kind == "simulate"

    _wait_for_job_consumed(controls, lambda: playback.trace is not None)

    assert playback.frame_count == 2
    assert "frame" in events
    assert controls._last_trace is not None
    assert job_manager.status().state == "idle"  # consumed and cleared


def test_changing_controller_discards_the_stale_result():
    """Conflicting-info bug: after Simulate, switching the controller left the old
    score/diagnosis showing next to a status that now describes a different config
    (e.g. a healthy sinusoid score beside a 'target_seek needs a target' error).
    The stale result must be cleared."""
    session = EditorSession()  # controller defaults to the curated first-run policy
    controls, _, _, playback = _make_controls(session)
    controls._start_simulate()
    _wait_for_job_consumed(controls, lambda: controls._last_trace is not None)
    assert controls._last_run_signature is not None

    dropdown = next(h for h in controls.gui.handles if h.options == list(AVAILABLE_CONTROLLERS))
    dropdown.update("cpg")

    assert controls._last_trace is None
    assert controls._last_run_signature is None
    assert playback.trace is None


def test_changing_the_body_discards_the_stale_result():
    session = EditorSession()
    controls, _, _, _ = _make_controls(session)
    controls._start_simulate()
    _wait_for_job_consumed(controls, lambda: controls._last_trace is not None)

    key = next(iter(session.params))
    controls._safe(
        lambda: session.set_body_param(key, float(session.params[key]) * 0.9 + 0.001),
        rebuild_body=False,
        rebuild_part=True,
        rebuild_motion=True,
        rebuild_task=False,
    )

    assert controls._last_trace is None  # body changed -> old run no longer applies


def test_selecting_a_part_keeps_the_result():
    """Guard against over-clearing: selection doesn't change the creature/task/
    controller, so a shown result must survive it."""
    session = EditorSession()
    controls, _, _, _ = _make_controls(session)
    controls._start_simulate()
    _wait_for_job_consumed(controls, lambda: controls._last_trace is not None)

    other_part = session.creature.parts[1].id
    controls.scene_selected(other_part)

    assert controls._last_trace is not None


def test_toggling_advanced_mode_keeps_the_result():
    session = EditorSession()
    controls, _, _, _ = _make_controls(session)
    controls._start_simulate()
    _wait_for_job_consumed(controls, lambda: controls._last_trace is not None)

    controls._safe(
        lambda: session.set_mode("advanced"),
        rebuild_body=True,
        rebuild_part=True,
        rebuild_motion=True,
        rebuild_task=True,
    )

    assert controls._last_trace is not None  # display mode isn't part of the run config


def test_simulate_refuses_to_start_a_second_job_while_running():
    started = []

    def slow_start() -> None:
        started.append(1)
        controls.job_manager.start(lambda reporter: time.sleep(0.2))

    session = EditorSession()
    controls, _, job_manager, _ = _make_controls(session, on_start_simulate=slow_start)

    controls._start_simulate()
    assert len(started) == 1
    controls._start_simulate()  # should refuse; job already running
    assert len(started) == 1
    assert "already running" in session.last_message

    _wait_until(lambda: not job_manager.is_running)  # let the background thread finish


def test_simulate_refused_when_session_invalid(monkeypatch):
    session = EditorSession()
    controls, _, job_manager, _ = _make_controls(session)
    monkeypatch.setattr(session, "status", lambda: SessionStatus(ok=False, errors=["bad"]))

    controls._start_simulate()

    assert job_manager.status().state == "idle"
    assert "fix validation errors" in session.last_message.lower()


def test_cancel_button_requests_cancellation():
    gate_started = []

    def slow_start() -> None:
        def work(reporter):
            gate_started.append(1)
            while not reporter.cancel_requested:
                time.sleep(0.005)
            raise JobCancelled

        controls.job_manager.start(work)

    controls, _, job_manager, _ = _make_controls(EditorSession(), on_start_simulate=slow_start)
    controls._start_simulate()
    _wait_until(lambda: len(gate_started) == 1)

    controls._cancel_button.click()
    _wait_until(lambda: job_manager.status().state == "cancelled")


# -- playback ------------------------------------------------------------------------


def test_playback_toggle_and_seek_do_not_crash():
    controls, events, job_manager, playback = _make_controls(EditorSession())
    controls._start_simulate()
    _wait_for_job_consumed(controls, lambda: playback.trace is not None)

    controls._toggle_playback()
    assert playback.playing is True
    controls._seek_playback(1)
    assert playback.frame_index == 1
    controls._step_playback(-1)
    assert playback.frame_index == 0
    controls._restart_playback()
    assert playback.frame_index == 0


def test_tick_advances_playback_and_calls_frame_callback():
    controls, events, job_manager, playback = _make_controls(EditorSession())
    controls._start_simulate()
    _wait_for_job_consumed(controls, lambda: playback.trace is not None)

    playback.play()
    events.clear()
    controls.tick(10.0)  # far more than enough to advance at least one frame
    assert "frame" in events


# -- diagnosis apply-fix ---------------------------------------------------------------


def test_apply_diagnosis_fix_from_panel_rebuilds_and_is_undoable():
    session = EditorSession(template="quadruped")
    controls, _, _, _ = _make_controls(session)

    controls._apply_diagnosis_fix("moving_backward")

    assert session.can_undo


# -- robustness ------------------------------------------------------------------------


def test_robustness_sweep_runs_as_background_job():
    controls, _, job_manager, _ = _make_controls(EditorSession())

    controls._start_robustness(5, 0.05, 0.05)
    assert controls._pending_job_kind == "robustness"

    _wait_for_job_consumed(controls, lambda: controls._last_robustness is not None)

    assert controls._last_robustness.mean_score == 1.0


# -- qualify ------------------------------------------------------------------------


def test_qualify_runs_as_background_job_and_reports_pass():
    controls, _, job_manager, _ = _make_controls(EditorSession())

    controls._start_qualify("basic-locomotion")
    assert controls._pending_job_kind == "qualify"

    _wait_for_job_consumed(controls, lambda: controls._last_qualification is not None)

    assert controls._last_qualification.passed is True
    assert "PASS" in controls.session.last_message


def test_qualify_reports_fail_and_primary_blocker():
    def start_failing_qualify(profile_name: str) -> None:
        job_manager.start(lambda reporter: _fake_qualification_result(passed=False))

    session = EditorSession()
    controls, _, job_manager, _ = _make_controls(session, on_start_qualify=start_failing_qualify)

    controls._start_qualify("basic-locomotion")
    _wait_for_job_consumed(controls, lambda: controls._last_qualification is not None)

    assert controls._last_qualification.passed is False
    assert controls._last_qualification.primary_blocker == "Baseline task success"
    assert "FAIL" in session.last_message


def test_qualify_refuses_to_start_while_a_job_is_running():
    def slow_start(profile_name: str) -> None:
        controls.job_manager.start(lambda reporter: time.sleep(0.2))

    session = EditorSession()
    controls, _, job_manager, _ = _make_controls(session, on_start_qualify=slow_start)

    controls._start_qualify("basic-locomotion")
    assert job_manager.is_running
    controls._start_qualify("basic-locomotion")  # should refuse; job already running
    assert "already running" in session.last_message

    _wait_until(lambda: not job_manager.is_running)


def test_qualify_refused_when_session_invalid(monkeypatch):
    session = EditorSession()
    controls, _, job_manager, _ = _make_controls(session)
    monkeypatch.setattr(session, "status", lambda: SessionStatus(ok=False, errors=["bad"]))

    controls._start_qualify("basic-locomotion")

    assert job_manager.status().state == "idle"
    assert "fix validation errors" in session.last_message.lower()


def test_qualify_result_renders_in_the_fake_gui():
    controls, _, job_manager, _ = _make_controls(EditorSession())

    controls._start_qualify("basic-locomotion")
    _wait_for_job_consumed(controls, lambda: controls._last_qualification is not None)

    assert controls._qualify_result_md is not None
    assert "PASS" in controls._qualify_result_md.content
    assert "basic-locomotion" in controls._qualify_result_md.content


# -- re-fit gait -----------------------------------------------------------------------


def _tuned_creature(session: EditorSession):
    tuned = session.creature.model_copy(deep=True)
    tuned.motors[0].amplitude = round(tuned.motors[0].amplitude + 0.2, 4)
    return tuned


def test_refit_gait_runs_as_background_job_and_applies_tuned_motors():
    session = EditorSession()
    before = session.creature.motors[0].amplitude

    def start_refit(attempts: int):
        job_manager.start(lambda reporter: _tuned_creature(session))

    controls, _, job_manager, _ = _make_controls(session, on_start_refit_gait=start_refit)

    controls._start_refit_gait(20)
    assert controls._pending_job_kind == "refit_gait"

    _wait_for_job_consumed(controls, lambda: session.creature.motors[0].amplitude != before)

    assert session.creature.motors[0].amplitude == pytest.approx(before + 0.2)
    assert session.can_undo  # routed through _history_action, like Undo/Apply-fix
    assert "re-fit" in session.last_message.lower()


def test_refit_gait_refuses_to_start_while_a_job_is_running():
    def slow_start(attempts: int) -> None:
        controls.job_manager.start(lambda reporter: time.sleep(0.2))

    session = EditorSession()
    controls, _, job_manager, _ = _make_controls(session, on_start_refit_gait=slow_start)

    controls._start_refit_gait(20)
    assert job_manager.is_running
    controls._start_refit_gait(20)  # should refuse; job already running
    assert "already running" in session.last_message

    _wait_until(lambda: not job_manager.is_running)


def test_refit_gait_refused_when_session_invalid(monkeypatch):
    session = EditorSession()
    controls, _, job_manager, _ = _make_controls(session)
    monkeypatch.setattr(session, "status", lambda: SessionStatus(ok=False, errors=["bad"]))

    controls._start_refit_gait(20)

    assert job_manager.status().state == "idle"
    assert "fix validation errors" in session.last_message.lower()


def test_refit_gait_refused_when_creature_has_no_motors():
    session = EditorSession()
    session.creature.motors.clear()
    controls, _, job_manager, _ = _make_controls(session)

    controls._start_refit_gait(20)

    assert job_manager.status().state == "idle"
    assert "no motors" in session.last_message.lower()


# -- run history -----------------------------------------------------------------------


def test_run_history_lists_and_restores_a_saved_run(tmp_path):
    creature = EditorSession(template="hexapod").creature
    save_run(creature, _fake_trace(creature_name="hexapod"), runs_dir=tmp_path)

    session = EditorSession(template="quadruped")
    controls, _, _, _ = _make_controls(session, runs_dir=tmp_path)

    assert controls._run_history_by_label
    label = next(iter(controls._run_history_by_label))
    controls._restore_run(label)

    assert session.creature.name == "hexapod"
    assert session.can_undo


def test_run_history_replay_loads_playback_without_mutating_session(tmp_path):
    creature = EditorSession(template="hexapod").creature
    save_run(creature, _fake_trace(creature_name="hexapod"), runs_dir=tmp_path)

    session = EditorSession(template="quadruped")
    controls, _, _, playback = _make_controls(session, runs_dir=tmp_path)

    label = next(iter(controls._run_history_by_label))
    controls._replay_run(label)

    assert playback.trace is not None
    assert session.creature.name == "quadruped"  # replay doesn't restore the design


def test_run_history_empty_state_does_not_crash(tmp_path):
    controls, _, _, _ = _make_controls(EditorSession(), runs_dir=tmp_path / "nope")
    assert controls._run_history_by_label == {}


def test_run_history_labels_stay_unique_when_runs_collide(tmp_path):
    """Two runs with the same creature/task/score/age bucket produce an identical
    base label (e.g. simply re-running the same example twice - not a contrived
    edge case, it's the common case). Viser's dropdown is a Mantine Select, which
    throws on a duplicate option value and crashes the *entire* editor GUI to a
    blank page - not just the dropdown - so this must never happen, however
    unlikely the underlying collision looks."""
    now = time.time()
    runs = [
        RunSummary(
            run_dir=tmp_path / run_id,
            run_id=run_id,
            creature_name="tripod",
            task_name="crawl_forward",
            backend="pybullet",
            score=0.017,
            saved_at=now,
        )
        for run_id in ("aaaaaaaaaaaa", "bbbbbbbbbbbb", "cccccccccccc")
    ]

    labels = BuildControls._unique_run_history_labels(runs)

    assert len(labels) == len(set(labels)) == 3
    for label, run in zip(labels, runs, strict=True):
        assert run.run_id in label


def test_run_history_dropdown_never_has_duplicate_options(tmp_path):
    creature = EditorSession(template="hexapod").creature
    for run_id in ("run-one", "run-two"):
        trace = _fake_trace(creature_name="tripod", score=0.017)
        save_run(creature, trace.model_copy(update={"run_id": run_id}), runs_dir=tmp_path)

    controls, _, _, _ = _make_controls(EditorSession(), runs_dir=tmp_path)

    dropdown = next(h for h in controls.gui.handles if h.options and "tripod" in h.options[0])
    assert len(dropdown.options) == len(set(dropdown.options))
    assert len(controls._run_history_by_label) == 2  # both runs individually restorable


# -- progress-first result headline -----------------------------------------------------


def _summary(**overrides) -> EpisodeSummary:
    base = dict(
        frame_count=10,
        duration=5.0,
        final_score=0.0,
        net_displacement=1.0,
        forward_displacement=0.0,
        total_joint_motion=1.0,
        target_progress=None,
        fell=None,
    )
    base.update(overrides)
    return EpisodeSummary.model_validate(base)


def _task(**reward) -> TaskSpec:
    data: dict = {"name": "t", "duration": 1.0, "reward": reward}
    if reward.get("target_distance"):
        data["target"] = {"position": [1.0, 0.0, 0.15], "radius": 0.15}
    return TaskSpec.model_validate(data)


def test_headline_leads_with_forward_progress_for_a_locomotion_task():
    summary = _summary(forward_displacement=0.58, fell=False)
    task = _task(forward_distance=1.0)
    assert BuildControls._progress_headline(summary, task) == "Moved 0.58 m forward; stayed upright"


def test_headline_describes_backward_movement_honestly():
    summary = _summary(forward_displacement=-0.9, fell=True)
    task = _task(forward_distance=1.0)
    headline = BuildControls._progress_headline(summary, task)
    assert "0.90 m backward" in headline
    assert "fell" in headline


def test_headline_leads_with_target_progress_when_the_task_rewards_a_target():
    """Regression: a run that visibly made target progress used to show a raw
    negative score with no context (energy penalty swamped the target reward) -
    the headline must foreground the concrete progress instead."""
    summary = _summary(target_progress=0.83, forward_displacement=0.58, fell=False)
    task = _task(forward_distance=0.0, target_distance=1.0)
    headline = BuildControls._progress_headline(summary, task)
    assert headline == "Moved 0.83 m closer to the target; stayed upright"


def test_headline_describes_moving_away_from_the_target():
    summary = _summary(target_progress=-0.2, fell=False)
    task = _task(forward_distance=0.0, target_distance=1.0)
    headline = BuildControls._progress_headline(summary, task)
    assert "0.20 m farther from the target" in headline


def test_headline_for_a_pure_balance_task_only_mentions_upright_state():
    summary = _summary(fell=False)
    task = _task(forward_distance=0.0, survival=1.0, fall_penalty=1.0)
    assert BuildControls._progress_headline(summary, task) == "Stayed upright"


def test_headline_falls_back_to_duration_when_nothing_else_applies():
    summary = _summary(duration=3.5, fell=None)
    task = _task(forward_distance=0.0)
    assert BuildControls._progress_headline(summary, task) == "Ran for 3.5s"


# -- onboarding -------------------------------------------------------------------------


def test_onboarding_shown_when_requested():
    controls, _, _, _ = _make_controls(EditorSession(), show_onboarding=True)
    # "Move forward" is a goal-dropdown value unique to the onboarding picker.
    assert any(h.value == "Move forward" for h in controls.gui.handles)
    assert controls._onboarding_folder is not None


def test_onboarding_not_shown_by_default():
    controls, _, _, _ = _make_controls(EditorSession())
    assert not any(h.value == "Move forward" for h in controls.gui.handles)
    assert controls._onboarding_folder is None


def test_onboarding_is_inline_not_a_modal():
    """Regression: onboarding must be an inline folder, never a modal. A Viser modal
    traps focus onto its first control, auto-opening the Creature dropdown over the
    Start/Skip buttons and making the whole first run unclickable (a real, blank-
    first-run bug found by driving the editor in a browser)."""
    controls, _, _, _ = _make_controls(EditorSession(), show_onboarding=True)
    assert controls._onboarding_folder is not None
    assert controls._onboarding_folder.kind == "folder"
    # No modal should have been created for onboarding.
    assert controls.gui.modals == []


def test_onboarding_start_applies_choice_and_removes_panel():
    session = EditorSession()
    controls, _, _, _ = _make_controls(session, show_onboarding=True)
    start = next(h for h in controls.gui.handles if getattr(h, "text", None) == "Start")

    start.click()

    assert controls._onboarding_folder is None  # panel removed
    # apply_onboarding ran: the goal-driven task preset is now active (default goal
    # is "Move forward" -> a locomotion task), and it is one undo step.
    assert session.can_undo


def test_onboarding_skip_removes_panel_without_changing_the_design():
    session = EditorSession(template="hexapod")
    controls, _, _, _ = _make_controls(session, show_onboarding=True)
    before = session.creature.name
    skip = next(h for h in controls.gui.handles if getattr(h, "text", None) == "Skip")

    skip.click()

    assert controls._onboarding_folder is None
    assert session.creature.name == before  # skip changed nothing


def test_onboarding_selecting_humanoid_keeps_move_forward_goal():
    """The 12-DOF humanoid has a measured curated walking gait, so onboarding must
    preserve the user's Move forward goal instead of silently changing their intent."""
    controls, _, _, _ = _make_controls(EditorSession(), show_onboarding=True)
    creature_labels = presets.preset_labels()
    goal_labels = presets.onboarding_goal_labels()
    creature_dropdown = next(h for h in controls.gui.handles if h.options == creature_labels)
    goal_dropdown = next(h for h in controls.gui.handles if h.options == goal_labels)
    assert goal_dropdown.value == "Move forward"  # sanity: default before any change

    creature_dropdown.update("Humanoid")

    assert goal_dropdown.value == "Move forward"
