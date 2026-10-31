"""The editor's robot check-up panel: consent stays in the terminal, work stays in a subprocess."""

from pathlib import Path
from types import SimpleNamespace

from creature_lab.editor.robot_panel import RobotCheckupPanel


class _Handle:
    def __init__(self, value=None):
        self.value = value
        self.content = ""
        self.disabled = False
        self._callback = None

    def on_click(self, callback):
        self._callback = callback

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
        return _Handle(initial_value)

    def add_button(self, label, **_):
        return _Handle()


def _panel(tmp_path: Path, **overrides):
    calls = []
    opened = []

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
    panel, calls, _ = _panel(tmp_path, installed=lambda key: False)
    panel._button.click()
    assert calls == []
    assert "creature-lab robots fetch microduck" in panel._status.content
    assert "license" in panel._status.content


def test_a_missing_extra_says_how_to_install_it(tmp_path):
    panel, calls, _ = _panel(tmp_path, missing=lambda: ["mujoco"])
    panel._button.click()
    assert calls == []
    assert "uv sync --inexact --extra robots" in panel._status.content


def test_start_runs_the_check_up_in_a_subprocess_and_blocks_a_second_start(tmp_path):
    panel, calls, _ = _panel(tmp_path)
    panel._button.click()
    assert len(calls) == 1
    assert calls[0][:3] == ["robots", "checkup", "microduck"]
    assert calls[0][3] == "--out" and Path(calls[0][4]).parent == tmp_path
    assert "--yes" not in calls[0]  # never accepts a license for the user
    assert panel.running and panel._button.disabled
    panel._button.click()
    assert len(calls) == 1
    assert "already running" in panel._status.content


def test_a_finished_check_up_opens_its_report(tmp_path):
    panel, calls, opened = _panel(tmp_path)
    panel._button.click()
    out = Path(calls[0][4])
    out.mkdir(parents=True)
    (out / "report.html").write_text("<html></html>", encoding="utf-8")
    panel._process.returncode = 0
    panel._process.poll = lambda: 0
    panel.tick()
    assert opened and opened[0].startswith("file:///") and opened[0].endswith("report.html")
    assert "Done" in panel._status.content
    assert not panel.running and not panel._button.disabled


def test_a_failed_check_up_points_at_the_terminal(tmp_path):
    panel, _, opened = _panel(tmp_path)
    panel._button.click()
    panel._process.returncode = 2
    panel._process.poll = lambda: 2
    panel.tick()
    assert opened == []
    assert "exit code 2" in panel._status.content
    assert not panel.running


def test_tick_does_nothing_while_idle_or_running(tmp_path):
    panel, _, opened = _panel(tmp_path)
    panel.tick()
    panel._button.click()
    panel.tick()
    assert panel.running and opened == []
