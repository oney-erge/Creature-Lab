"""The ``creature-lab robots`` command group."""

from typer.testing import CliRunner

from creature_lab.cli import app

runner = CliRunner()


def test_robots_list_names_both_robots():
    result = runner.invoke(app, ["robots", "list"])
    assert result.exit_code == 0
    assert "microduck" in result.output
    assert "unitree-g1" in result.output


def test_an_unknown_robot_is_rejected_with_the_choices():
    result = runner.invoke(app, ["robots", "fetch", "walle", "--yes"])
    assert result.exit_code != 0
    assert "microduck" in result.output


def test_fetch_without_consent_downloads_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("CREATURE_LAB_ROBOTS_DIR", str(tmp_path / "cache"))
    result = runner.invoke(app, ["robots", "fetch", "microduck"])  # stdin is not a terminal
    assert result.exit_code == 1
    text = " ".join(result.output.replace("│", " ").split())  # undo the notice box's wrapping
    assert "CC BY-NC-SA 4.0" in text
    assert "Not downloaded" in text
    assert not (tmp_path / "cache").exists()


def test_commands_that_need_the_extra_explain_how_to_install_it(monkeypatch, tmp_path):
    """Checked before anything imports numpy/mujoco, so a base install gets a clear message."""
    monkeypatch.setattr("creature_lab.robots.cli.missing_extra", lambda: ["mujoco"])
    for args in (
        ["robots", "checkup", "microduck"],
        ["robots", "film", str(tmp_path)],
        ["robots", "loop", str(tmp_path)],
    ):
        result = runner.invoke(app, args)
        assert result.exit_code == 2, args
        assert "--extra robots" in result.output, args
