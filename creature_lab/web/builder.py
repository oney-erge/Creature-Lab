"""Starts the classic build editor on request, so the new app can still hand you a design tool."""

from __future__ import annotations

import atexit
import subprocess
import sys
import time
from collections.abc import Callable, Sequence

from creature_lab.viewers.viser_viewer import DEFAULT_HOST, find_free_port

_RUNNER = "from creature_lab.cli import app; app()"
_FIRST_PORT = 8100
_WAIT_S = 25.0


class BuilderError(RuntimeError):
    """The classic builder could not be started (usually a missing extra)."""


def known_presets() -> list[str]:
    from creature_lab.editor.presets import CREATURE_PRESETS

    return list(CREATURE_PRESETS)


def _launch(args: Sequence[str]) -> subprocess.Popen:
    return subprocess.Popen(  # noqa: S603 - fixed interpreter and our own arguments
        [sys.executable, "-c", _RUNNER, *args],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _port_open(port: int) -> bool:
    import socket

    with socket.socket() as probe:
        probe.settimeout(0.3)
        return probe.connect_ex((DEFAULT_HOST, port)) == 0


class Builder:
    """At most one classic builder runs; asking for another preset restarts it."""

    def __init__(
        self,
        launcher: Callable[[Sequence[str]], subprocess.Popen] = _launch,
        port_open: Callable[[int], bool] = _port_open,
        wait_s: float = _WAIT_S,
    ) -> None:
        self._launcher = launcher
        self._port_open = port_open
        self._wait_s = wait_s
        self._process: subprocess.Popen | None = None
        self._preset: str | None = None
        self._port = 0
        atexit.register(self.stop)

    def stop(self) -> None:
        if self._process is not None and self._process.poll() is None:
            self._process.terminate()
        self._process = None

    def open(self, preset: str) -> str:
        """The URL of a builder editing ``preset``, starting one if needed."""
        if preset not in known_presets():
            raise BuilderError(f"unknown preset {preset!r}")
        if self._process is not None and self._process.poll() is None and self._preset == preset:
            return f"http://localhost:{self._port}"
        self.stop()
        self._port = find_free_port(DEFAULT_HOST, _FIRST_PORT)
        self._preset = preset
        self._process = self._launcher(
            ["build", "--preset", preset, "--no-open-browser", "--port", str(self._port)]
        )
        deadline = time.monotonic() + self._wait_s
        while time.monotonic() < deadline:
            if self._process.poll() is not None:
                self._process = None
                raise BuilderError(
                    "The classic builder needs the viz extra and a physics engine "
                    "(MuJoCo comes with the robots extra): "
                    "uv sync --inexact --extra viz --extra robots"
                )
            if self._port_open(self._port):
                return f"http://localhost:{self._port}"
            time.sleep(0.15)
        self.stop()
        raise BuilderError("The classic builder did not start in time.")
