"""`pip install creature-lab` with no extras has to start.

0.4.0's release check failed here: `creature-lab --help` imports every subcommand, and a top-level
`import numpy` in robots/pack.py stopped it on a plain install. CI's wheel smoke test installs the
`sim` extra, which brings numpy, so nothing before the release step noticed.
"""

import subprocess
import sys

import pytest

# The import names of everything the optional extras install.
_EXTRAS = (
    "numpy",
    "pybullet",
    "viser",
    "trimesh",
    "matplotlib",
    "imageio",
    "imageio_ffmpeg",
    "PIL",
    "litellm",
    "cmaes",
    "mujoco",
    "onnxruntime",
    "fastapi",
    "uvicorn",
    "playwright",
    "gymnasium",
    "stable_baselines3",
)
_BLOCK = "import sys; " + "; ".join(f"sys.modules[{name!r}] = None" for name in _EXTRAS)


@pytest.mark.parametrize("args", [["--help"], ["robots", "--help"]])
def test_the_cli_starts_without_any_extra(args):
    result = subprocess.run(
        [sys.executable, "-c", f"{_BLOCK}; from creature_lab.cli import app; app({args!r})"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr[-800:]
    assert "Usage" in result.stdout
