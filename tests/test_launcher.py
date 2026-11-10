"""The launcher installs only prebuilt wheels for the app, so a first start needs no compiler."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
START = ROOT / "scripts" / "start.py"


def _load_start():
    sys.path.insert(0, str(START.parent))
    try:
        spec = importlib.util.spec_from_file_location("creature_lab_start", START)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(START.parent))


def _dry_run(*args: str) -> str:
    result = subprocess.run(
        [sys.executable, str(START), "--dry-run", "--no-open-browser", "--skip-doctor", *args],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


@pytest.mark.skipif(shutil.which("uv") is None, reason="the launcher needs uv")
def test_the_app_is_installed_without_pybullet():
    """PyBullet is built from source on Windows and macOS; the app must not need it."""
    output = _dry_run("--mode", "app")
    sync = [line for line in output.splitlines() if line.startswith("$ ") and " sync " in line]
    assert sync, output
    assert "--extra web" in sync[0] and "--extra robots" in sync[0]
    assert "--extra sim" not in sync[0]


@pytest.mark.skipif(shutil.which("uv") is None, reason="the launcher needs uv")
def test_the_classic_editor_is_installed_without_pybullet_too():
    """The editor falls back to MuJoCo, which comes with the robots extra."""
    output = _dry_run("--mode", "build")
    sync = [line for line in output.splitlines() if line.startswith("$ ") and " sync " in line]
    assert sync and "--extra sim" not in sync[0], output


@pytest.mark.skipif(shutil.which("uv") is None, reason="the launcher needs uv")
def test_only_the_pybullet_demo_installs_pybullet_and_warns_first():
    output = _dry_run("--mode", "demo", "--skip-sync")
    assert "--extra sim" in output
    assert "C++ compiler" in output


def test_every_mode_names_what_it_probes_and_installs():
    start = _load_start()
    assert set(start.MODE_SETUP) == {"app", "build", "demo"}
    for probe, extras in start.MODE_SETUP.values():
        assert probe.strip()
        assert extras and all(part in {"--extra"} or part.isalpha() for part in extras)
    app_probe, app_extras = start.MODE_SETUP["app"]
    assert "sim" not in app_extras
    assert "pybullet" not in app_probe
    # The editor probe accepts either physics engine.
    assert "mujoco" in start.MODE_SETUP["build"][0]


@pytest.mark.parametrize("script", ["run.ps1", "run.sh"])
def test_the_shared_launchers_keep_hand_installed_extras_and_skip_pybullet(script):
    text = (ROOT / script).read_text(encoding="utf-8")
    sync = next(
        line for line in text.splitlines() if line.startswith(("$syncArgs =", "sync_args=("))
    )
    assert "--inexact" in sync
    assert "web" in sync and "robots" in sync
    assert '"sim"' not in sync and "--extra sim" not in sync


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        (
            "error: Failed to build `pybullet==3.2.7`\n  fatal error C1083: Cannot open include "
            "file: 'btBulletCollisionCommon.h': No such file or directory",
            "path",
        ),
        ("error MSB3491: Could not write lines to file", "path"),
        ("Caused by: failed to create directory (os error 206)", "path"),
        (
            "error: Microsoft Visual C++ 14.0 or greater is required. Get it with 'Microsoft "
            "C++ Build Tools'",
            "C++ build tools",
        ),
        ("gcc: command not found\nerror: command 'gcc' failed", "C++ build tools"),
        ("xcrun: error: invalid active developer path", "C++ build tools"),
        ("No space left on device (os error 28)", "disk is full"),
        ("error: Request failed after 3 retries: dns error: failed to lookup", "network"),
    ],
)
def test_known_install_failures_are_explained_in_plain_words(output, expected):
    start = _load_start()
    advice = start.explain_install_failure(output)
    assert advice is not None and expected in advice


def test_an_unknown_failure_is_left_alone():
    start = _load_start()
    assert start.explain_install_failure("error: something nobody has seen before") is None
    assert start.explain_install_failure("") is None


def test_a_failed_install_prints_the_advice_and_keeps_the_exit_code(capsys):
    start = _load_start()
    script = "import sys; print('error MSB3491: path too long'); sys.exit(3)"
    with pytest.raises(SystemExit) as stopped:
        start.run_step(
            "Install dependencies",
            [sys.executable, "-c", script],
            failure_hint="hint line",
            explain=True,
        )
    captured = capsys.readouterr()
    assert stopped.value.code == 3
    assert "error MSB3491" in captured.out  # the installer's own output is still shown
    assert "What to do:" in captured.err and "short path" in captured.err
    assert "hint line" in captured.err


def test_a_first_install_picks_a_python_with_wheels_but_an_existing_venv_is_kept():
    start = _load_start()
    assert start.first_install_python(venv_exists=False) == ["--python", "3.12"]
    assert start.first_install_python(venv_exists=True) == []


@pytest.mark.parametrize("script", ["run.ps1", "run.sh"])
def test_the_shared_launchers_only_pin_python_for_a_first_install(script):
    text = (ROOT / script).read_text(encoding="utf-8")
    line = next(line for line in text.splitlines() if "--python" in line and ".venv" in line)
    assert "3.12" in line
    # The pin is conditional on there being no .venv yet, so a developer's own venv is not rebuilt.
    assert "-not (Test-Path" in line or "[ -d .venv ] ||" in line
