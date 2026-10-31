"""The viewer and editor have no sign-in, so they must listen on this computer only by default."""

from __future__ import annotations

import socket

import pytest
from typer.testing import CliRunner

from creature_lab.cli import app
from creature_lab.runs import save_run
from creature_lab.schema import CreatureSpec, EpisodeTrace, FrameState, TaskSpec
from creature_lab.viewers.viser_viewer import DEFAULT_HOST

runner = CliRunner()

CREATURE = {
    "name": "test_bot",
    "parts": [{"id": "torso", "shape": "box", "size": [0.4, 0.2, 0.1], "mass": 1.0}],
}


def _frame() -> FrameState:
    return FrameState.model_validate({"t": 0.0, "parts": {"torso": {"position": [0, 0, 0]}}})


def _lan_address() -> str | None:
    """This computer's outbound IPv4 address, or None when it has no network (no packet is sent)."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 9))
        address = probe.getsockname()[0]
    except OSError:
        return None
    finally:
        probe.close()
    return None if address.startswith("127.") else address


def _accepts_connections(address: str, port: int) -> bool:
    try:
        socket.create_connection((address, port), timeout=1).close()
    except OSError:
        return False
    return True


def test_default_host_is_loopback():
    assert DEFAULT_HOST == "127.0.0.1"


def test_viewer_is_not_reachable_from_the_network_by_default():
    pytest.importorskip("viser")
    from creature_lab.viewers.viser_viewer import stream_frames

    lan = _lan_address()
    if lan is None:
        pytest.skip("this computer has no non-loopback address to probe")
    port = 8137
    reachable: dict[str, bool] = {}

    def frames():
        reachable["loopback"] = _accepts_connections("127.0.0.1", port)
        reachable["network"] = _accepts_connections(lan, port)
        yield _frame()

    stream_frames(
        CreatureSpec.model_validate(CREATURE), frames(), fps=1000.0, port=port, hold=False
    )

    assert reachable == {"loopback": True, "network": False}


@pytest.mark.parametrize(
    ("given", "expected"), [({}, "127.0.0.1"), ({"host": "0.0.0.0"}, "0.0.0.0")]
)
def test_viewer_passes_the_host_to_viser(monkeypatch, given, expected):
    viser = pytest.importorskip("viser")
    from creature_lab.viewers.viser_viewer import stream_frames

    hosts = []
    real_server = viser.ViserServer

    def recording_server(*args, **kwargs):
        hosts.append(kwargs.get("host"))
        return real_server(*args, **kwargs)

    monkeypatch.setattr(viser, "ViserServer", recording_server)

    stream_frames(
        CreatureSpec.model_validate(CREATURE),
        iter([_frame()]),
        fps=1000.0,
        port=8138,
        hold=False,
        **given,
    )

    assert hosts == [expected]


def _run_build(monkeypatch, args, env=None):
    seen = {}
    monkeypatch.setattr(
        "creature_lab.editor.live.run_editor", lambda session, **kwargs: seen.update(kwargs)
    )
    result = runner.invoke(app, ["build", "--no-open-browser", *args], env=env)
    assert result.exit_code == 0, result.stdout
    return seen, result.stdout


def test_build_listens_on_this_computer_only_by_default(monkeypatch):
    seen, output = _run_build(monkeypatch, [])
    assert seen["host"] == "127.0.0.1"
    assert "warning" not in output


def test_build_host_flag_allows_the_network_and_warns(monkeypatch):
    seen, output = _run_build(monkeypatch, ["--host", "0.0.0.0"])
    assert seen["host"] == "0.0.0.0"
    assert "no sign-in" in output


def test_build_host_can_be_set_from_the_environment(monkeypatch):
    """The Docker image relies on this: the container must listen on 0.0.0.0 inside."""
    seen, _ = _run_build(monkeypatch, [], env={"CREATURE_LAB_HOST": "0.0.0.0"})
    assert seen["host"] == "0.0.0.0"


def test_view_forwards_the_host(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(
        "creature_lab.viewers.viser_viewer.play_trace",
        lambda creature, trace, **kwargs: seen.update(kwargs),
    )
    trace = EpisodeTrace.model_validate(
        {
            "run_id": "run1",
            "creature_name": "test_bot",
            "task_name": "crawl_forward",
            "backend": "pybullet",
            "score": 1.0,
            "frames": [{"t": 0.0, "parts": {"torso": {"position": [0, 0, 0]}}, "score": 0.0}],
        }
    )
    run_dir = save_run(
        CreatureSpec.model_validate(CREATURE),
        trace,
        runs_dir=tmp_path / "runs",
        task=TaskSpec.model_validate({"name": "crawl_forward", "duration": 1.0}),
    )

    assert runner.invoke(app, ["view", str(run_dir)]).exit_code == 0
    assert seen["host"] == "127.0.0.1"

    result = runner.invoke(app, ["view", str(run_dir), "--host", "0.0.0.0"])
    assert result.exit_code == 0, result.stdout
    assert seen["host"] == "0.0.0.0"
    assert "no sign-in" in result.stdout


def test_find_free_port_keeps_a_free_port():
    from creature_lab.viewers.viser_viewer import find_free_port

    with socket.socket() as probe:
        probe.bind((DEFAULT_HOST, 0))
        free = probe.getsockname()[1]
    assert find_free_port(DEFAULT_HOST, free) == free


def test_find_free_port_moves_past_a_port_that_something_else_holds():
    """Viser would silently pick another port, leaving the CLI to open the wrong server."""
    from creature_lab.viewers.viser_viewer import find_free_port

    holder = socket.socket()
    holder.bind((DEFAULT_HOST, 0))
    holder.listen()
    busy = holder.getsockname()[1]
    try:
        found = find_free_port(DEFAULT_HOST, busy)
        assert found > busy
        with socket.socket() as probe:
            probe.bind((DEFAULT_HOST, found))  # really free
    finally:
        holder.close()


def test_find_free_port_leaves_port_zero_alone():
    from creature_lab.viewers.viser_viewer import find_free_port

    assert find_free_port(DEFAULT_HOST, 0) == 0


def test_claiming_a_busy_port_says_so_and_returns_the_port_to_use(monkeypatch):
    from creature_lab import cli

    monkeypatch.setattr(cli, "find_free_port", lambda host, port: port + 2)
    with cli.console.capture() as captured:
        assert cli._claim_port(DEFAULT_HOST, 8080) == 8082
    assert "port 8080 is already in use; using 8082" in captured.get()
