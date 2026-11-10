"""Modules that must load without MuJoCo, because their extras do not include it."""

import subprocess
import sys

import pytest

pytest.importorskip("viser")

_BLOCK_MUJOCO = "import sys; sys.modules['mujoco'] = None; "


@pytest.mark.parametrize(
    "module",
    [
        "creature_lab.editor.live",  # the classic editor, which needs only the sim and viz extras
        "creature_lab.robots.checkup",  # reading a saved check-up needs no simulator
        "creature_lab.robots.report",
        "creature_lab.robots.analysis",
    ],
)
def test_module_imports_without_mujoco(module):
    result = subprocess.run(
        [sys.executable, "-c", f"{_BLOCK_MUJOCO}import {module}"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr[-600:]
