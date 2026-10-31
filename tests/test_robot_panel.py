"""The editor's robot panel: consent stays in the terminal, work stays out of the editor."""

import os
import time
from pathlib import Path
from types import SimpleNamespace

from robot_helpers import synthetic_run

from creature_lab.editor.robot_panel import RobotCheckupPanel, find_replays


class _Handle:
    def __init__(self, value=None):
        self.value = value
        self.content = ""
        self.disabled = False
        self.visible = True
        self.options = ()
        self._callback = None

    def on_click(self, callback):
        self._callback = callback

    on_update = on_click

    def click(self):
        self._callback(None)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Gui:
    def add_folder(self, label, **_):
        return _Handle()

    def add_markdown(self, content="", **_):
        handle = _Handle()
        handle.content = content
        return handle

    def add_dropdown(self, label, options, initial_value=None, **_):
        handle = _Handle(initial_value)
        handle.options = tuple(options)
        return handle

    def add_button(self, label, **_):
        return _Handle()

    def add_checkbox(self, label, initial_value=False, **_):
        return _Handle(initial_value)


class _Stage:
    """Records what the panel asks of the 3D stage."""

    def __init__(self):
        self.shown, self.played, self.ticks = [], [], []
        self.active, self.robot, self.follow, self.hidden = False, None, True, 0

    def show(self, key, run=None):
        self.shown.append((key, run))
        self.active, self.robot = True, key

    def play(self, run):
        self.played.append(run)

    def hide(self):
        self.active, self.hidden = False, self.hidden + 1

    def tick(self, dt):
        self.ticks.append(dt)


def _save_checkup(out_root: Path, robot="microduck", policy="velstand", name="baseline", **kw):
    folder = out_root / f"{robot}-20261030"
    (folder / policy).mkdir(parents=True, exist_ok=True)
    (folder / policy / "checkup.json").write_text("{}", encoding="utf-8")
    synthetic_run(robot=robot, policy=policy, **kw).save(folder / policy / "runs" / name)
    return folder


def _panel(tmp_path: Path, **overrides):
    calls, opened = [], []

    def launcher(args):
        calls.append(list(args))
        return SimpleNamespace(returncode=None, poll=lambda: None)

    settings = dict(
        out_root=tmp_path,
        launcher=launcher,
        opener=opened.append,
        installed=lambda key: True,
        missing=lambda: [],
    )
    settings.update(overrides)
    return RobotCheckupPanel(_Gui(), **settings), calls, opened


def test_a_robot_that_is_not_downloaded_is_fetched_from_a_terminal(tmp_path):
    stage = _Stage()
    panel, calls, _ = _panel(tmp_path, installed=lambda key: False, stage=stage)
    for button in (panel._run_button, panel._show_button):
        button.click()
    assert calls == [] and stage.shown == []
    assert "creature-lab robots fetch microduck" in panel._status.content
    assert "license" in panel._status.content


def test_a_missing_extra_says_how_to_install_it(tmp_path):
    panel, calls, _ = _panel(tmp_path, missing=lambda: ["mujoco"], stage=_Stage())
    panel._run_button.click()
    assert calls == []
    assert "uv sync --inexact --extra robots" in panel._status.content
    panel._show_button.click()
    assert "uv sync --inexact --extra robots" in panel._status.content


def test_start_runs_the_check_up_in_a_subprocess_and_blocks_a_second_start(tmp_path):
    panel, calls, _ = _panel(tmp_path)
    panel._run_button.click()
    assert len(calls) == 1
    assert calls[0][:3] == ["robots", "checkup", "microduck"]
    assert calls[0][3] == "--out" and Path(calls[0][4]).parent == tmp_path
    assert "--yes" not in calls[0]  # never accepts a license for the user
    assert panel.running and panel._run_button.disabled
    panel._run_button.click()
    assert len(calls) == 1
    assert "already running" in panel._status.content


def test_a_finished_check_up_opens_its_report_and_offers_its_replays(tmp_path):
    panel, calls, opened = _panel(tmp_path)
    assert panel._replay_choice.options == ("(run a check-up first)",)
    panel._run_button.click()
    out = Path(calls[0][4])
    out.mkdir(parents=True)
    (out / "report.html").write_text("<html></html>", encoding="utf-8")
    _save_checkup(tmp_path, name="baseline")  # what the subprocess would have written
    panel._process.returncode = 0
    panel._process.poll = lambda: 0
    panel.tick()
    assert opened and opened[0].startswith("file:///") and opened[0].endswith("report.html")
    assert "Done" in panel._status.content
    assert len(panel._replay_choice.options) == 1 and "baseline" in panel._replay_choice.options[0]
    assert not panel.running and not panel._run_button.disabled


def test_a_failed_check_up_points_at_the_terminal(tmp_path):
    panel, _, opened = _panel(tmp_path)
    panel._run_button.click()
    panel._process.returncode = 2
    panel._process.poll = lambda: 2
    panel.tick()
    assert opened == []
    assert "exit code 2" in panel._status.content
    assert not panel.running


def test_tick_does_nothing_while_idle_or_running_but_still_drives_the_stage(tmp_path):
    stage = _Stage()
    panel, _, opened = _panel(tmp_path, stage=stage)
    panel.tick(0.02)
    panel._run_button.click()
    panel.tick(0.02)
    assert panel.running and opened == []
    assert stage.ticks == [0.02, 0.02]


def test_showing_a_robot_reveals_the_way_back(tmp_path):
    stage = _Stage()
    panel, _, _ = _panel(tmp_path, stage=stage)
    assert not panel._back_button.visible
    panel._show_button.click()
    assert stage.shown == [("microduck", None)]
    assert panel._back_button.visible
    panel._back_button.click()
    assert stage.hidden == 1 and not panel._back_button.visible


def test_the_follow_checkbox_reaches_the_stage(tmp_path):
    stage = _Stage()
    panel, _, _ = _panel(tmp_path, stage=stage)
    panel._follow.value = False
    panel._follow._callback(None)
    assert stage.follow is False


def test_replay_loads_the_saved_run_onto_the_stage(tmp_path):
    stage = _Stage()
    _save_checkup(tmp_path, name="baseline")
    panel, _, _ = _panel(tmp_path, stage=stage)
    panel._replay_button.click()
    ((key, run),) = stage.shown
    assert key == "microduck" and run.scenario.policy == "velstand"
    assert "Replaying" in panel._status.content
    assert panel._back_button.visible
    # A second replay of the same robot reuses the stage instead of reloading it.
    panel._replay_button.click()
    assert len(stage.shown) == 1 and len(stage.played) == 1


def test_replay_without_saved_runs_says_what_to_do(tmp_path):
    panel, _, _ = _panel(tmp_path, stage=_Stage())
    panel._replay_button.click()
    assert "Run robot check-up" in panel._status.content


def test_find_replays_lists_the_newest_check_up_in_a_useful_order(tmp_path):
    assert find_replays(tmp_path / "missing") == {}
    _save_checkup(tmp_path, name="shove_3N_fall", push_n=3.0, fall_at=4.6)
    _save_checkup(tmp_path, name="baseline")
    _save_checkup(tmp_path, name="grip_0.15", grip=0.15)
    _save_checkup(tmp_path, policy="alpha_walking", name="shove_3N_ok", push_n=3.0)
    replays = find_replays(tmp_path)
    order = [path.name for path in replays.values()]
    assert order[0] == "baseline"
    assert order.index("shove_3N_fall") < order.index("grip_0.15")
    labels = list(replays)
    assert any(label.endswith("(falls)") for label in labels)
    assert any(label.endswith("(stays up)") for label in labels)
    assert all(label.startswith("Microduck · ") for label in labels)


def test_only_the_newest_check_up_of_a_robot_is_offered(tmp_path):
    first = _save_checkup(tmp_path, name="baseline")
    os.utime(first, (time.time() - 100, time.time() - 100))
    newer = tmp_path / "microduck-newer"
    (newer / "velstand").mkdir(parents=True)
    (newer / "velstand" / "checkup.json").write_text("{}", encoding="utf-8")
    synthetic_run().save(newer / "velstand" / "runs" / "shove_2N_fall")
    paths = list(find_replays(tmp_path).values())
    assert [p.name for p in paths] == ["shove_2N_fall"]
