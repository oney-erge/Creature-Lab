"""The `creature-lab app` command and the launcher script that starts it."""

import importlib.util
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from creature_lab.cli import app

runner = CliRunner()
START = Path(__file__).resolve().parent.parent / "scripts" / "start.py"


def test_app_without_its_extras_says_how_to_install_them(monkeypatch):
    monkeypatch.setitem(sys.modules, "uvicorn", None)  # makes `import uvicorn` fail
    result = runner.invoke(app, ["app", "--no-open-browser"])
    assert result.exit_code == 2
    assert "--extra web --extra robots" in result.output


def test_app_serves_the_checkup_folder_on_a_free_port(monkeypatch, tmp_path):
    pytest.importorskip("fastapi")
    uvicorn = pytest.importorskip("uvicorn")
    served = {}
    monkeypatch.setattr(uvicorn, "run", lambda application, **kwargs: served.update(kwargs))
    result = runner.invoke(app, ["app", "--no-open-browser", "--checkups", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert served["host"] == "127.0.0.1"
    assert "serving" in result.output


@pytest.fixture(scope="module")
def start():
    sys.path.insert(0, str(START.parent))  # start.py imports its sibling _process_utils
    try:
        spec = importlib.util.spec_from_file_location("creature_lab_start", START)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.path.remove(str(START.parent))


def _mode(start, monkeypatch, *argv) -> str:
    monkeypatch.setattr(sys, "argv", ["start.py", *argv])
    return start.parse_args().mode


def test_launcher_opens_the_app_unless_a_creature_is_asked_for(start, monkeypatch):
    assert _mode(start, monkeypatch) == "app"
    assert _mode(start, monkeypatch, "--creature", "hexapod") == "build"
    assert _mode(start, monkeypatch, "--mode", "demo") == "demo"


def test_launcher_refuses_a_creature_for_the_app(start, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["start.py", "--mode", "app", "--creature", "worm"])
    with pytest.raises(SystemExit) as stop:
        start.parse_args()
    assert stop.value.code == 2
