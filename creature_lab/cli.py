"""Command-line interface for Creature Lab."""

from __future__ import annotations

import json
import random
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Annotated, Any, TypeVar
from xml.etree.ElementTree import ParseError as ET_PARSE_ERROR

import typer
from pydantic import BaseModel, ValidationError
from rich.console import Console
from rich.table import Table

from creature_lab import VERSION, qualification
from creature_lab.controllers.factory import curated_controller, extract_sinusoid_spec
from creature_lab.controllers.sinusoid import sinusoid_targets
from creature_lab.diagnostics import collect_doctor_checks, summarize_episode
from creature_lab.evolve import (
    Evaluation,
    cmaes,
    genetic,
    hill_climb,
    make_mutator,
    map_elites,
    tool_random_mutate,
)
from creature_lab.exporting import export_design_pack, verify_design_pack
from creature_lab.hashing import spec_hash
from creature_lab.library import (
    builtin_creature_names,
    creature_by_name,
    default_creature,
    default_task,
)
from creature_lab.runs import (
    DEFAULT_RUNS_DIR,
    new_run_id,
    resolve_run_path,
    resolve_trace_path,
    save_run,
)
from creature_lab.schema import (
    ControllerSpec,
    CreatureSpec,
    EpisodeTrace,
    FrameState,
    TaskSpec,
    TraceMeta,
)
from creature_lab.schema.trace import TRACE_SCHEMA_VERSION
from creature_lab.validation import EpisodeInputError, validate_episode_inputs
from creature_lab.viewers.viser_viewer import DEFAULT_HOST

app = typer.Typer(
    help=(
        "Tiny local lab for designing, running, diagnosing, and improving "
        "modular robot-creatures from JSON."
    )
)
console = Console()

ModelT = TypeVar("ModelT", bound=BaseModel)


def _load_spec(path: Path, model: type[ModelT]) -> ModelT:
    if not path.exists():
        console.print(f"[red]error:[/red] file not found: {path}")
        raise typer.Exit(code=2)

    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        console.print(f"[red]invalid JSON[/red] in {path}: {exc}")
        raise typer.Exit(code=1) from exc

    try:
        return model.model_validate(data)
    except ValidationError as exc:
        console.print(f"[red]invalid {model.__name__}[/red] in {path}:")
        for error in exc.errors():
            location = ".".join(str(part) for part in error["loc"]) or "(root)"
            console.print(f"  [yellow]{location}[/yellow]: {error['msg']}")
        raise typer.Exit(code=1) from exc


def _write_stdout(text: str) -> None:
    console.file.write(text)
    if not text.endswith("\n"):
        console.file.write("\n")


def _print_json(data: Any) -> None:
    _write_stdout(json.dumps(data, indent=2, sort_keys=True))


def _resolve_run_path(path: Path, runs_dir: Path = DEFAULT_RUNS_DIR) -> Path:
    try:
        return resolve_run_path(path, runs_dir=runs_dir)
    except FileNotFoundError as exc:
        console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=2) from exc


def _resolve_trace_path(path: Path, runs_dir: Path = DEFAULT_RUNS_DIR) -> Path:
    try:
        return resolve_trace_path(path, runs_dir=runs_dir)
    except FileNotFoundError as exc:
        console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=2) from exc


def _run_dir_for(path: Path, runs_dir: Path = DEFAULT_RUNS_DIR) -> Path:
    resolved = _resolve_run_path(path, runs_dir=runs_dir)
    return resolved if resolved.is_dir() else resolved.parent


def _load_creature_for_trace(
    path: Path, creature_path: Path | None, runs_dir: Path = DEFAULT_RUNS_DIR
) -> CreatureSpec:
    """Load the creature for a trace, defaulting to creature.json in the run directory."""
    if creature_path is None:
        run_dir = _run_dir_for(path, runs_dir=runs_dir)
        creature_path = run_dir / "creature.json"
    return _load_spec(creature_path, CreatureSpec)


def _load_task_for_trace(
    path: Path, task_path: Path | None, runs_dir: Path = DEFAULT_RUNS_DIR
) -> TaskSpec | None:
    """Load the task for a trace: explicit --task, else task.json in the run dir if present."""
    if task_path is not None:
        return _load_spec(task_path, TaskSpec)
    run_dir = _run_dir_for(path, runs_dir=runs_dir)
    candidate = run_dir / "task.json"
    return _load_spec(candidate, TaskSpec) if candidate.exists() else None


def _saved_run_payload(
    creature: CreatureSpec, task: TaskSpec, trace: EpisodeTrace, run_dir: Path
) -> dict[str, Any]:
    return {
        "run_id": trace.run_id,
        "run_dir": str(run_dir),
        "creature": creature.name,
        "task": task.name,
        "backend": trace.backend,
        "score": trace.score,
        "frames": len(trace.frames),
    }


def _check_inputs(creature: CreatureSpec, task: TaskSpec) -> None:
    """Cross-validate inputs before simulating: warn on soft issues, abort on hard errors."""
    try:
        warnings = validate_episode_inputs(creature, task)
    except EpisodeInputError as exc:
        console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    for warning in warnings:
        console.print(f"[yellow]warning:[/yellow] {warning}")


def _require_backend(name: str = "pybullet") -> tuple[type, str]:
    """Resolve a backend class + version string by name, exiting if it is missing."""
    if name == "pybullet":
        try:
            from creature_lab.backends.pybullet_backend import PyBulletBackend, backend_version
        except ImportError as exc:
            console.print(
                "[red]error:[/red] pybullet is not installed. Install it with "
                "`uv sync --extra sim`."
            )
            raise typer.Exit(code=2) from exc
        return PyBulletBackend, backend_version()
    if name == "mujoco":
        try:
            from creature_lab.backends.mujoco_backend import MuJoCoBackend, backend_version
        except ImportError as exc:
            console.print(
                "[red]error:[/red] mujoco is not installed. Install it with "
                "`uv sync --extra mujoco`."
            )
            raise typer.Exit(code=2) from exc
        return MuJoCoBackend, backend_version()
    console.print(f"[red]error:[/red] unknown backend {name!r} (choose: pybullet, mujoco)")
    raise typer.Exit(code=2)


def _build_meta(
    creature: CreatureSpec,
    task: TaskSpec,
    *,
    seed: int | None,
    score_summary: dict[str, float],
    backend_version: str,
    controller: str | None = None,
) -> TraceMeta:
    """Build the provenance/reproducibility metadata stamped into a trace."""
    return TraceMeta(
        schema_version=TRACE_SCHEMA_VERSION,
        lab_version=VERSION,
        backend_version=backend_version,
        timestep=task.timestep,
        seed=seed,
        creature_hash=spec_hash(creature),
        task_hash=spec_hash(task),
        score_summary=score_summary,
        warnings=validate_episode_inputs(creature, task),
        controller=controller,
    )


def _trace_from_frames(
    creature: CreatureSpec,
    task: TaskSpec,
    frames: list[FrameState],
    *,
    meta: TraceMeta,
    backend: str = "pybullet",
) -> EpisodeTrace:
    return EpisodeTrace(
        run_id=new_run_id(),
        creature_name=creature.name,
        task_name=task.name,
        backend=backend,
        score=frames[-1].score,
        frames=frames,
        meta=meta,
    )


def _make_controller(name: str, creature: CreatureSpec, task: TaskSpec):
    """Build a controller callable ``(t, prev_frame) -> targets``.

    ``name`` is either a built-in controller name (``sinusoid``/``cpg``/
    ``target_seek``/``posture``) or a path to a ``controller.json`` (a portable
    ``ControllerSpec`` - see ``creature_lab.controllers.factory.build_controller``
    and ``creature-lab controller scaffold/extract``), detected by a ``.json`` suffix.

    Reports errors via ``console.print`` + ``typer.Exit`` rather than
    ``typer.BadParameter``: this runs deep inside ``_simulate``, not from a Typer
    parameter callback, and Click only pretty-prints ``BadParameter`` when it is
    raised from the latter - raised here, it would exit silently with no message.
    """
    if name == "curated":
        name = _curated_controller(creature)
    if name.lower().endswith(".json"):
        return _make_controller_from_spec_file(Path(name), creature, task)
    if name == "hold":
        return lambda _t, _prev=None: {}
    if name == "sinusoid":
        return lambda t, prev=None: sinusoid_targets(creature, t)
    if name == "cpg":
        from creature_lab.controllers.cpg import CPGController

        return CPGController(creature)
    if name == "target_seek":
        from creature_lab.controllers.target_seek import TargetSeekController

        if task.target is None:
            console.print(
                "[red]error:[/red] controller 'target_seek' requires a task with a target "
                "(e.g. --task examples/reach_target.json)"
            )
            raise typer.Exit(code=2)
        return TargetSeekController(creature, task)
    if name == "posture":
        from creature_lab.controllers.posture import PostureController

        return PostureController(creature)
    console.print(
        f"[red]error:[/red] unknown controller {name!r} (choose: sinusoid, cpg, target_seek, "
        "posture, or a path to a controller.json)"
    )
    raise typer.Exit(code=2)


#: Resolves 'curated' for both the CLI and the build editor - see its docstring.
_curated_controller = curated_controller


def _make_controller_from_spec_file(path: Path, creature: CreatureSpec, task: TaskSpec):
    """Load a ``controller.json`` (a ``ControllerSpec``) and build the controller it
    describes. See ``creature_lab.controllers.factory.build_controller``."""
    from creature_lab.controllers.factory import build_controller
    from creature_lab.schema import ControllerSpec

    spec = _load_spec(path, ControllerSpec)
    try:
        return build_controller(spec, creature, task, base_dir=path.resolve().parent)
    except ValueError as exc:
        console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=2) from exc


def _simulate(
    creature: CreatureSpec,
    task: TaskSpec,
    *,
    gui: bool = False,
    seed: int | None = None,
    controller: str = "sinusoid",
    backend: str = "pybullet",
    on_step: Callable[[int, int], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> EpisodeTrace:
    """Run one physics episode on the named backend and return its trace (unsaved).

    ``on_step(completed, total)`` and ``should_stop()`` are optional hooks for a
    caller running this off the main thread (see ``creature_lab.editor.jobs``) to
    report progress and cooperatively cancel between steps. Both default to no-ops,
    so this stays a plain blocking call for every other caller.
    """
    resolved_controller = _curated_controller(creature) if controller == "curated" else controller
    policy = _make_controller(resolved_controller, creature, task)
    backend_cls, version = _require_backend(backend)
    sim = backend_cls(gui=gui)
    total_steps = task.step_count()
    try:
        sim.build(creature, task, seed=seed)
        frames: list[FrameState] = []
        prev: FrameState | None = None
        for step_index in range(total_steps):
            if should_stop is not None and should_stop():
                break
            t = step_index * task.timestep
            sim.apply_joint_control(policy(t, prev), mode="position")
            prev = sim.step(task.timestep)
            frames.append(prev)
            if on_step is not None:
                on_step(step_index + 1, total_steps)
        score_summary = sim.score_summary()
    finally:
        sim.close()

    if not frames:
        console.print("[yellow]warning:[/yellow] task duration too short to run any steps")
        raise typer.Exit(code=1)

    meta = _build_meta(
        creature,
        task,
        seed=seed,
        score_summary=score_summary,
        backend_version=version,
        controller=resolved_controller,
    )
    return _trace_from_frames(creature, task, frames, meta=meta, backend=backend)


@app.callback(invoke_without_command=True)
def _default(ctx: typer.Context) -> None:
    """Run a quick built-in episode and print its score and diagnosis.

    With no subcommand, this loads the built-in quadruped, runs its measured gait, and
    shows what happened - no browser, no arguments, nothing beyond `uv sync --extra sim`.
    Use `creature-lab build` for the visual editor, or `--help` for every command.
    """
    if ctx.invoked_subcommand is not None:
        return
    from creature_lab.diagnosis import diagnose as run_diagnosis

    creature = default_creature()
    task_spec = default_task()
    _check_inputs(creature, task_spec)
    trace = _simulate(creature, task_spec, controller="curated")
    run_dir = save_run(creature, trace, task=task_spec)

    console.print(
        f"[green]done[/green] {creature.name!r} on {task_spec.name!r}: "
        f"score={trace.score:.4f} ({len(trace.frames)} step(s)) -> {run_dir}"
    )

    result = run_diagnosis(trace, creature, task_spec)
    if result.patterns:
        console.print("\n[bold]Root-cause patterns detected:[/bold]")
        for pattern, explanation in zip(result.patterns, result.explanations, strict=True):
            console.print(f"  [yellow]! {pattern}[/yellow] - {explanation}")
    else:
        console.print("\n[green]no failure patterns detected[/green] - this run looks healthy.")

    console.print(
        "\nTry [bold]creature-lab build[/bold] for the visual editor, or "
        "[bold]creature-lab --help[/bold] for every command."
    )


HostOption = Annotated[
    str,
    typer.Option(
        envvar="CREATURE_LAB_HOST",
        help="Address to listen on. The default accepts connections from this computer only; "
        "use 0.0.0.0 to let other devices connect (there is no sign-in).",
    ),
]


def _warn_if_network_exposed(host: str) -> None:
    """Say plainly when the viewer is reachable from other devices; it has no sign-in."""
    if host in {"127.0.0.1", "localhost", "::1"}:
        return
    console.print(
        f"[yellow]warning:[/yellow] listening on {host}. Anyone who can reach this port can "
        "use the viewer and editor (no sign-in). Do this only on a network you trust, or behind "
        "a port mapping that stays on this computer, as the Docker setup does."
    )


@app.command(rich_help_panel="Start Here")
def demo(
    creature_path: Annotated[
        Path | None, typer.Argument(help="CreatureSpec JSON (overrides --creature).")
    ] = None,
    creature_name: Annotated[
        str | None,
        typer.Option(
            "--creature",
            help="Built-in creature to demo (quadruped, worm, tripod). Default: quadruped.",
        ),
    ] = None,
    task: Annotated[
        Path | None, typer.Option(help="TaskSpec JSON (default: built-in crawl_forward).")
    ] = None,
    fps: Annotated[float, typer.Option(help="Playback frames per second.")] = 60.0,
    host: HostOption = DEFAULT_HOST,
    port: Annotated[int, typer.Option(help="Port for the Viser server.")] = 8080,
    open_browser: Annotated[
        bool,
        typer.Option(
            "--open-browser/--no-open-browser",
            help="Open the local viewer URL in the default browser.",
        ),
    ] = False,
    save: Annotated[bool, typer.Option(help="Save the streamed episode as a trace.")] = True,
    hold: Annotated[
        bool, typer.Option(help="Keep serving and looping after the run (Ctrl+C to stop).")
    ] = True,
    seed: Annotated[int | None, typer.Option(help="Seed recorded in the trace metadata.")] = None,
    runs_dir: Annotated[
        Path, typer.Option(help="Directory to save the episode trace under.")
    ] = DEFAULT_RUNS_DIR,
) -> None:
    """Simulate a creature and stream its motion live to a Viser browser viewer.

    With no arguments it uses the built-in quadruped and crawl-forward task, so it
    works from an installed package without the repository's examples/ directory.
    Use ``--creature worm`` (or ``tripod``) to pick a different built-in, or pass a
    CreatureSpec JSON path to load your own.
    """
    if creature_path:
        creature = _load_spec(creature_path, CreatureSpec)
    elif creature_name:
        try:
            creature = creature_by_name(creature_name)
        except KeyError as exc:
            available = ", ".join(builtin_creature_names())
            console.print(
                f"[red]error:[/red] unknown creature {creature_name!r}; choose one of: {available}"
            )
            raise typer.Exit(code=2) from exc
    else:
        creature = default_creature()
    task_spec = _load_spec(task, TaskSpec) if task else default_task()
    _check_inputs(creature, task_spec)

    backend_cls, version = _require_backend()
    try:
        from creature_lab.viewers.viser_viewer import stream_frames
    except ImportError as exc:
        console.print(
            "[red]error:[/red] viser is not installed. Install it with `uv sync --extra viz`."
        )
        raise typer.Exit(code=2) from exc

    backend_holder: list = []
    demo_controller = _curated_controller(creature)
    demo_policy = _make_controller(demo_controller, creature, task_spec)

    def live_frames() -> Iterator[FrameState]:
        backend = backend_cls()
        backend_holder.append(backend)
        try:
            backend.build(creature, task_spec, seed=seed)
            previous: FrameState | None = None
            for step_index in range(task_spec.step_count()):
                targets = demo_policy(step_index * task_spec.timestep, previous)
                backend.apply_joint_control(targets, mode="position")
                previous = backend.step(task_spec.timestep)
                yield previous
        finally:
            backend.close()

    _warn_if_network_exposed(host)
    console.print(
        f"[green]serving[/green] {creature.name!r} on http://localhost:{port} (Ctrl+C to stop)"
    )
    frames = stream_frames(
        creature,
        live_frames(),
        task=task_spec,
        fps=fps,
        host=host,
        port=port,
        hold=hold,
        open_browser=open_browser,
    )

    if save and frames:
        summary = backend_holder[0].score_summary() if backend_holder else {}
        meta = _build_meta(
            creature,
            task_spec,
            seed=seed,
            score_summary=summary,
            backend_version=version,
            controller=demo_controller,
        )
        trace = _trace_from_frames(creature, task_spec, frames, meta=meta)
        run_dir = save_run(creature, trace, runs_dir=runs_dir, task=task_spec)
        console.print(f"[green]saved[/green] {len(frames)} frame(s) -> {run_dir}")


@app.command(rich_help_panel="Run And Improve")
def run(
    creature_path: Annotated[Path, typer.Argument(help="Path to a CreatureSpec JSON file.")],
    task: Annotated[Path, typer.Option(help="Path to a TaskSpec JSON file.")],
    controller: Annotated[
        str,
        typer.Option(
            help="Controller: 'sinusoid', 'cpg', 'target_seek' (needs a task with a target), "
            "'posture' (PD balance), or a path to a controller.json."
        ),
    ] = "sinusoid",
    backend: Annotated[
        str, typer.Option(help="Physics backend: 'pybullet' or 'mujoco'.")
    ] = "pybullet",
    gui: Annotated[bool, typer.Option(help="Open a PyBullet GUI window.")] = False,
    seed: Annotated[int | None, typer.Option(help="Seed recorded in the trace metadata.")] = None,
    runs_dir: Annotated[
        Path, typer.Option(help="Directory to save the episode trace under.")
    ] = DEFAULT_RUNS_DIR,
    json_output: Annotated[
        bool, typer.Option("--json", help="Print machine-readable run metadata.")
    ] = False,
) -> None:
    """Run a short physics episode, save its trace, and print the final score."""
    creature = _load_spec(creature_path, CreatureSpec)
    task_spec = _load_spec(task, TaskSpec)
    _check_inputs(creature, task_spec)
    trace = _simulate(
        creature, task_spec, gui=gui, seed=seed, controller=controller, backend=backend
    )
    run_dir = save_run(creature, trace, runs_dir=runs_dir, task=task_spec)
    if json_output:
        _print_json(_saved_run_payload(creature, task_spec, trace, run_dir))
        return

    console.print(
        f"[green]done[/green] {creature.name!r} on {task_spec.name!r}: "
        f"score={trace.score:.4f} ({len(trace.frames)} step(s)) -> {run_dir}"
    )


@app.command(rich_help_panel="Replay And Debug")
def replay(
    path: Annotated[Path, typer.Argument(help="Path to a trace.json file or run directory.")],
    runs_dir: Annotated[
        Path, typer.Option(help="Directory used when resolving the `latest` alias.")
    ] = DEFAULT_RUNS_DIR,
) -> None:
    """Print a summary of a saved episode trace."""
    trace = _load_spec(_resolve_trace_path(path, runs_dir), EpisodeTrace)
    duration = trace.frames[-1].t  # total simulated time (final frame timestamp)
    console.print(
        f"[green]trace[/green] {trace.run_id!r}: {trace.creature_name!r} on "
        f"{trace.task_name!r} via {trace.backend!r} — {len(trace.frames)} frame(s), "
        f"{duration:.2f}s, score={trace.score:.4f}"
    )


@app.command(rich_help_panel="Advanced")
def version() -> None:
    """Print the Creature Lab version."""
    console.print(f"creature-lab {VERSION}")


_STATUS_STYLE = {"ok": "green", "missing": "red", "warn": "yellow", "info": "cyan"}


@app.command(rich_help_panel="Advanced")
def doctor() -> None:
    """Check the environment: optional extras, providers, and that examples run."""
    table = Table(title=f"creature-lab {VERSION} doctor")
    table.add_column("check")
    table.add_column("status")
    table.add_column("detail")
    for check in collect_doctor_checks():
        style = _STATUS_STYLE.get(check.status, "white")
        table.add_row(check.name, f"[{style}]{check.status}[/{style}]", check.detail)
    console.print(table)


@app.command(rich_help_panel="Advanced")
def validate(
    path: Annotated[Path, typer.Argument(help="Path to a CreatureSpec JSON file.")],
    task: Annotated[
        Path | None,
        typer.Option(help="Also validate a TaskSpec and cross-check it against the creature."),
    ] = None,
) -> None:
    """Validate a creature JSON file (and optionally a task) against the schema."""
    creature = _load_spec(path, CreatureSpec)
    console.print(
        f"[green]valid[/green] creature {creature.name!r}: "
        f"{len(creature.parts)} part(s), {len(creature.joints)} joint(s), "
        f"{len(creature.motors)} motor(s)"
    )
    if task is not None:
        task_spec = _load_spec(task, TaskSpec)
        console.print(f"[green]valid[/green] task {task_spec.name!r}")
        _check_inputs(creature, task_spec)
        console.print("[green]ok[/green] creature and task are compatible")


@app.command(rich_help_panel="Start Here")
def build(
    creature_path: Annotated[
        Path | None,
        typer.Argument(
            help="Optional CreatureSpec JSON to edit instead of starting from a preset."
        ),
    ] = None,
    preset: Annotated[
        str,
        typer.Option(help="Starting preset: quadruped, hexapod, worm, or humanoid."),
    ] = "quadruped",
    out: Annotated[
        Path,
        typer.Option("--out", "-o", help="Where Save JSON writes the CreatureSpec."),
    ] = Path("outputs/build_creature.json"),
    task: Annotated[
        Path | None,
        typer.Option(help="Optional TaskSpec JSON for simulation and validation."),
    ] = None,
    task_preset: Annotated[
        str,
        typer.Option(help="Task preset when --task is not supplied."),
    ] = "crawl_forward",
    project: Annotated[
        Path | None,
        typer.Option(
            "--project",
            help=(
                "Bind to a project directory: creature.json/task.json there are loaded on "
                "start and kept live-synced with the editor (autosave on edit, external "
                "edits detected with a Reload prompt). Overrides --preset/creature_path/--task."
            ),
        ),
    ] = None,
    controller: Annotated[
        str,
        typer.Option(
            help="Controller for Simulate: 'curated' (best first-run behavior), "
            "'sinusoid', 'cpg', 'target_seek' (needs a target), or 'posture'."
        ),
    ] = "curated",
    backend: Annotated[
        str, typer.Option(help="Physics backend for Simulate: 'pybullet' or 'mujoco'.")
    ] = "pybullet",
    seed: Annotated[int | None, typer.Option(help="Seed recorded in simulated traces.")] = None,
    host: HostOption = DEFAULT_HOST,
    port: Annotated[int, typer.Option(help="Port for the Viser build editor.")] = 8080,
    open_browser: Annotated[
        bool,
        typer.Option(
            "--open-browser/--no-open-browser",
            help="Open the build editor URL in the default browser.",
        ),
    ] = True,
    runs_dir: Annotated[
        Path, typer.Option(help="Directory to save simulated traces under.")
    ] = DEFAULT_RUNS_DIR,
) -> None:
    """Open the browser build editor for presets, live tuning, validation, and simulation."""
    from creature_lab.editor import presets as editor_presets
    from creature_lab.editor.live import run_editor
    from creature_lab.editor.session import AVAILABLE_CONTROLLERS, EditorSession

    if preset not in editor_presets.CREATURE_PRESETS:
        available = ", ".join(editor_presets.preset_names())
        console.print(f"[red]error:[/red] unknown preset {preset!r}; choose one of: {available}")
        raise typer.Exit(code=2)
    if task_preset not in editor_presets.TASK_PRESETS:
        available = ", ".join(editor_presets.task_names())
        console.print(
            f"[red]error:[/red] unknown task preset {task_preset!r}; choose one of: {available}"
        )
        raise typer.Exit(code=2)
    if controller not in AVAILABLE_CONTROLLERS:
        # The editor dropdown intentionally offers stable named controllers, so
        # a bad --controller here would otherwise silently break the dropdown's
        # initial value instead of failing at launch.
        available = ", ".join(AVAILABLE_CONTROLLERS)
        console.print(
            f"[red]error:[/red] unknown controller {controller!r} for build; choose one of: "
            f"{available}"
        )
        raise typer.Exit(code=2)

    task_spec = (
        _load_spec(task, TaskSpec)
        if task is not None
        else editor_presets.generate_task(task_preset)
    )
    if project is not None:
        session = EditorSession(template=preset, task=task_spec, out_path=out)
        session.bind_project(project)
    elif creature_path is not None:
        session = EditorSession.from_path(creature_path, task=task_spec, out_path=out)
    else:
        session = EditorSession(
            template=preset,
            task=task_spec,
            out_path=out,
        )
    session.task_preset = task_preset if task is None else task_spec.name
    session.controller = controller

    def simulate_current(
        creature: CreatureSpec,
        task_for_run: TaskSpec,
        *,
        controller: str = "sinusoid",
        on_step: Callable[[int, int], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> EpisodeTrace:
        _check_inputs(creature, task_for_run)
        return _simulate(
            creature,
            task_for_run,
            seed=seed,
            controller=controller,
            backend=backend,
            on_step=on_step,
            should_stop=should_stop,
        )

    other_backend = "mujoco" if backend == "pybullet" else "pybullet"

    def simulate_other_backend(
        creature: CreatureSpec, task_for_run: TaskSpec, *, controller: str = "sinusoid"
    ) -> EpisodeTrace:
        """For the editor's Qualify panel's backend-portable check - same as
        ``simulate_current`` but pinned to the backend the session isn't already
        using. Kept in cli.py (not editor/live.py) since only the CLI layer knows
        about concrete backend names; the editor treats `simulate` as opaque."""
        _check_inputs(creature, task_for_run)
        return _simulate(
            creature, task_for_run, seed=seed, controller=controller, backend=other_backend
        )

    _warn_if_network_exposed(host)
    console.print(
        f"[green]serving[/green] build editor on http://localhost:{port} (Ctrl+C to stop)"
    )
    run_editor(
        session,
        simulate=simulate_current,
        simulate_other_backend=simulate_other_backend,
        host=host,
        port=port,
        open_browser=open_browser,
        runs_dir=runs_dir,
        # Only greet with the creature x goal picker on a truly fresh launch - not
        # when the user already pointed at a specific creature or project.
        show_onboarding=creature_path is None and project is None,
    )


def _gait_symmetry(trace: EpisodeTrace) -> float:
    """Right-side share of ground contacts in [0, 1] (0.5 = symmetric / no l/r parts)."""
    left = right = 0
    for frame in trace.frames:
        for part_id in {c.part_id for c in frame.contacts}:
            if part_id.endswith("_l"):
                left += 1
            elif part_id.endswith("_r"):
                right += 1
    total = left + right
    return 0.5 if total == 0 else right / total


def _feature_evaluate(creature: CreatureSpec, task: TaskSpec) -> Evaluation:
    """Evaluate a creature, returning its score plus a (forward, symmetry) descriptor."""
    trace = _simulate(creature, task)
    summary = summarize_episode(trace, task, creature)
    return Evaluation(trace.score, (summary.forward_displacement, _gait_symmetry(trace)))


@app.command(rich_help_panel="Run And Improve")
def evolve(
    creature_path: Annotated[Path, typer.Argument(help="Path to a CreatureSpec JSON file.")],
    task: Annotated[Path, typer.Option(help="Path to a TaskSpec JSON file.")],
    strategy: Annotated[
        str, typer.Option(help="hill_climb, genetic, map_elites, cmaes, or tool_random.")
    ] = "hill_climb",
    mutate_opt: Annotated[
        str, typer.Option("--mutate", help="What to mutate: body, controller, or body,controller.")
    ] = "body,controller",
    attempts: Annotated[int, typer.Option(help="Number of candidate evaluations.")] = 10,
    seed: Annotated[int, typer.Option(help="Random seed for reproducible evolution.")] = 0,
    runs_dir: Annotated[
        Path, typer.Option(help="Directory to save the best creature and trace under.")
    ] = DEFAULT_RUNS_DIR,
    json_output: Annotated[
        bool, typer.Option("--json", help="Print machine-readable best-run metadata.")
    ] = False,
) -> None:
    """Evolve a creature from a seed, saving the best one, a lineage, and any archive."""
    creature = _load_spec(creature_path, CreatureSpec)
    task_spec = _load_spec(task, TaskSpec)
    _check_inputs(creature, task_spec)
    rng = random.Random(seed)

    if strategy == "llm":
        typer.echo(
            "Warning: --strategy llm is deprecated; it uses random tools, not a model. "
            "Use --strategy tool_random.",
            err=True,
        )
        strategy = "tool_random"
    if strategy not in {"hill_climb", "genetic", "map_elites", "cmaes", "tool_random"}:
        console.print(
            "[red]error:[/red] --strategy must be hill_climb, genetic, map_elites, cmaes, "
            "or tool_random"
        )
        raise typer.Exit(code=2)

    targets = {part.strip() for part in mutate_opt.split(",") if part.strip()}
    if not targets <= {"body", "controller"}:
        console.print("[red]error:[/red] --mutate must be 'body', 'controller', or both")
        raise typer.Exit(code=2)
    # tool_random ignores --mutate: every edit goes through the validated agent tool layer instead
    # of the structural body/controller mutators. Record each proposal's rationale (even
    # rejected ones) so it can be saved into lineage.json for `report`/`lineage` to show.
    tool_notes: list[str] = []

    def _record_tool_note(proposal: Any) -> None:
        tool_notes.append(f"{proposal.tool}: {proposal.note}" if proposal.note else proposal.tool)

    def _tool_mutate_and_record(spec: CreatureSpec, r: random.Random) -> CreatureSpec:
        return tool_random_mutate(spec, r, on_propose=_record_tool_note)

    mutate_fn = (
        _tool_mutate_and_record
        if strategy == "tool_random"
        else make_mutator("body" in targets, "controller" in targets)
    )

    def evaluate(candidate: CreatureSpec) -> float:
        return _simulate(candidate, task_spec).score

    try:
        if strategy in ("hill_climb", "tool_random"):
            result = hill_climb(creature, evaluate, attempts=attempts, rng=rng, mutate_fn=mutate_fn)
        elif strategy == "genetic":
            result = genetic(creature, evaluate, attempts=attempts, rng=rng, mutate_fn=mutate_fn)
        elif strategy == "map_elites":
            result = map_elites(
                creature,
                lambda c: _feature_evaluate(c, task_spec),
                attempts=attempts,
                rng=rng,
                mutate_fn=mutate_fn,
            )
        else:  # cmaes
            result = cmaes(creature, evaluate, attempts=attempts, rng=rng)
    except (RuntimeError, ValueError) as exc:
        console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    best_trace = _simulate(result.best, task_spec, seed=seed)
    run_dir = save_run(result.best, best_trace, runs_dir=runs_dir, task=task_spec)

    # Persist the lineage (and MAP-Elites archive) so `lineage` can render them later.
    lineage = [
        {
            "index": a.index,
            "parent": a.parent,
            "generation": a.generation,
            "score": a.score,
            "accepted": a.accepted,
            "cell": list(a.cell) if a.cell is not None else None,
            **(
                {"note": tool_notes[a.index - 1]}
                if strategy == "tool_random" and 0 < a.index <= len(tool_notes)
                else {}
            ),
        }
        for a in result.history
    ]
    (run_dir / "lineage.json").write_text(
        json.dumps({"strategy": strategy, "nodes": lineage}, indent=2)
    )
    if result.archive:
        archive = {
            f"{cell[0]},{cell[1]}": {
                "score": entry["score"],
                "features": list(entry["features"]),
                "spec": entry["spec"].model_dump(mode="json"),
            }
            for cell, entry in result.archive.items()
        }
        (run_dir / "archive.json").write_text(json.dumps(archive, indent=2))

    if json_output:
        payload = _saved_run_payload(result.best, task_spec, best_trace, run_dir)
        payload["strategy"] = strategy
        payload["attempts"] = attempts
        payload["seed_score"] = result.history[0].score
        payload["best_score"] = result.best_score
        _print_json(payload)
        return

    table = Table(title=f"{creature.name!r} evolve ({strategy}, {attempts} attempts, seed {seed})")
    table.add_column("attempt", justify="right")
    table.add_column("score", justify="right")
    table.add_column("result")
    for attempt in result.history:
        label = "seed" if attempt.index == 0 else ("kept" if attempt.accepted else "rejected")
        style = "green" if attempt.accepted else "dim"
        table.add_row(str(attempt.index), f"{attempt.score:.4f}", f"[{style}]{label}[/{style}]")
    console.print(table)
    if result.archive:
        console.print(f"[cyan]archive[/cyan]: {len(result.archive)} behaviour cell(s) filled")
    console.print(
        f"[green]best[/green] score={result.best_score:.4f} "
        f"(seed score={result.history[0].score:.4f}) -> {run_dir}"
    )


@app.command(rich_help_panel="Run And Improve")
def optimize(
    creature_path: Annotated[Path, typer.Argument(help="Path to a CreatureSpec JSON file.")],
    task: Annotated[Path, typer.Option(help="Path to a TaskSpec JSON file.")],
    attempts: Annotated[
        int, typer.Option(help="Number of CMA-ES evaluations (higher = better, slower).")
    ] = 80,
    seed: Annotated[int, typer.Option(help="Random seed for reproducible optimization.")] = 0,
    backend: Annotated[
        str, typer.Option(help="Physics backend to evaluate on: 'pybullet' or 'mujoco'.")
    ] = "pybullet",
    out: Annotated[
        Path | None,
        typer.Option("--out", "-o", help="Write the optimized controller.json here (else stdout)."),
    ] = None,
    name: Annotated[str, typer.Option(help="Name recorded in the controller.json.")] = "optimized",
    json_output: Annotated[
        bool, typer.Option("--json", help="Print machine-readable optimization metadata.")
    ] = False,
) -> None:
    """Optimize a creature's sinusoid gait and save it as a portable controller.json.

    CMA-ES tunes each motor's amplitude/frequency/phase (the creature's body is never
    touched) to maximize the task's score - the same search `evolve --strategy cmaes`
    already does, aimed specifically at producing a reusable controller artifact
    instead of a new creature file. Needs the 'evolve' extra (`uv sync --extra evolve`).
    A quadruped example creature went from score 0.24 to 0.70 (2.9x) in 80 evaluations
    (a couple of CPU-minutes) - the un-tuned default sinusoid gait leaves real
    performance on the table for every locomotion task.
    """
    creature = _load_spec(creature_path, CreatureSpec)
    task_spec = _load_spec(task, TaskSpec)
    _check_inputs(creature, task_spec)
    rng = random.Random(seed)

    def evaluate(candidate: CreatureSpec) -> float:
        return _simulate(candidate, task_spec, backend=backend).score

    try:
        result = cmaes(creature, evaluate, attempts=attempts, rng=rng)
    except (RuntimeError, ValueError) as exc:
        console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    controller_spec = extract_sinusoid_spec(result.best, name=name)
    seed_score = result.history[0].score
    best_score = result.best_score
    rendered = controller_spec.model_dump_json(indent=2, exclude_none=True)
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(rendered)

    if json_output:
        _print_json(
            {
                "creature": creature.name,
                "task": task_spec.name,
                "attempts": attempts,
                "seed_score": seed_score,
                "best_score": best_score,
                "out": str(out) if out is not None else None,
            }
        )
        return

    if out is None:
        # Nothing else asked for the artifact, so it goes to stdout - matches
        # `controller scaffold`/`controller extract`'s no-destination behavior.
        _write_stdout(rendered)
        return

    ratio = f"{best_score / seed_score:.2f}x" if seed_score > 0 else "n/a"
    console.print(
        f"[green]optimized[/green] {creature.name!r}: score {seed_score:.4f} -> "
        f"{best_score:.4f} ({ratio}) -> {out}"
    )


@app.command(rich_help_panel="Run And Improve")
def train(
    creature_path: Annotated[Path, typer.Argument(help="Path to a CreatureSpec JSON file.")],
    task: Annotated[Path, typer.Option(help="Path to a TaskSpec JSON file.")],
    timesteps: Annotated[int, typer.Option(help="Total PPO training timesteps.")] = 100_000,
    seed: Annotated[int, typer.Option(help="Random seed for training and evaluation.")] = 0,
    eval_episodes: Annotated[
        int, typer.Option(help="Episodes to evaluate the trained policy and the baseline over.")
    ] = 5,
    out: Annotated[
        Path,
        typer.Option("--out", "-o", help="Directory to write controller.json + the policy file."),
    ] = Path("outputs/trained_policy"),
    name: Annotated[str, typer.Option(help="Name recorded in the controller.json.")] = "trained",
    json_output: Annotated[
        bool, typer.Option("--json", help="Print machine-readable training metadata.")
    ] = False,
    overwrite: Annotated[
        bool, typer.Option(help="Replace an existing trained-policy output directory.")
    ] = False,
) -> None:
    """Train a policy to control a creature via PPO (Stable-Baselines3, over
    CreatureEnv) and save it as a controller.json + policy file bundle.

    Grand Plan Phase 5, Tier 3: a creature learning to move through closed-loop
    reinforcement learning, rather than a hand-tuned open-loop gait (`optimize`) or
    hand-tuned feedback (`--controller posture`). Scoped honestly: this trains a real
    policy and reports its measured improvement over a random baseline on the same
    task - it is a working proof, not a promise of a polished walker (real bipedal
    walking is a research problem, not a short-training-run outcome). Needs the
    'rl' extra (`uv sync --extra rl`).
    """
    try:
        from creature_lab.rl.train import train_ppo
    except ImportError as exc:
        console.print(
            "[red]error:[/red] the 'rl' extra is not installed. "
            "Install it with `uv sync --extra rl`."
        )
        raise typer.Exit(code=2) from exc

    creature = _load_spec(creature_path, CreatureSpec)
    task_spec = _load_spec(task, TaskSpec)
    _check_inputs(creature, task_spec)
    if timesteps < 1 or eval_episodes < 1:
        console.print("[red]error:[/red] --timesteps and --eval-episodes must be at least 1")
        raise typer.Exit(code=2)
    if out.exists() and any(out.iterdir()) and not overwrite:
        console.print(f"[red]error:[/red] output directory already exists: {out}")
        raise typer.Exit(code=2)

    if not json_output:
        console.print(
            f"[cyan]training[/cyan] {creature.name!r} on {task_spec.name!r}: "
            f"{timesteps} PPO timesteps (seed {seed})..."
        )
    result = train_ppo(
        creature, task_spec, timesteps=timesteps, seed=seed, eval_episodes=eval_episodes
    )

    import os
    import platform
    import shutil
    import tempfile
    from importlib.metadata import version as package_version

    from creature_lab.io_utils import atomic_write_text
    from creature_lab.schema import ControllerSpec, ControllerType

    policy_filename = "policy.zip"

    controller_spec = ControllerSpec(
        name=name,
        type=ControllerType.POLICY,
        policy_file=policy_filename,
        observation=result.observation_spec,
        action=result.action_spec,
        creature_hash=spec_hash(creature),
        task_hash=spec_hash(task_spec),
        policy_format="stable-baselines3/PPO (trusted files only)",
        runtime_versions={
            "python": platform.python_version(),
            "stable-baselines3": package_version("stable-baselines3"),
            "torch": package_version("torch"),
            "gymnasium": package_version("gymnasium"),
        },
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{out.name}.", dir=out.parent))
    try:
        result.model.save(str(stage / policy_filename))
        atomic_write_text(
            stage / "controller.json",
            controller_spec.model_dump_json(indent=2, exclude_none=True),
        )
        if out.exists():
            shutil.rmtree(out)
        os.replace(stage, out)
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise

    if json_output:
        _print_json(
            {
                "creature": creature.name,
                "task": task_spec.name,
                "timesteps": result.timesteps,
                "eval_episodes": result.eval_episodes,
                "baseline_mean_return": result.baseline_mean_return,
                "trained_mean_return": result.trained_mean_return,
                "out": str(out),
            }
        )
        return

    ratio = (
        f"{result.trained_mean_return / result.baseline_mean_return:.2f}x"
        if result.baseline_mean_return > 0
        else "n/a"
    )
    console.print(
        f"[green]trained[/green] {creature.name!r}: random baseline mean return "
        f"{result.baseline_mean_return:.4f} -> trained {result.trained_mean_return:.4f} "
        f"({ratio}) -> {out}"
    )


@app.command(rich_help_panel="Run And Improve")
def bench(
    zoo: Annotated[bool, typer.Option("--zoo", help="Benchmark packaged zoo creatures.")] = False,
    task: Annotated[
        str | None,
        typer.Option(help="Only run zoo creatures that include this task name."),
    ] = None,
    attempts: Annotated[int, typer.Option(help="Runs per creature/task pair.")] = 1,
    seed: Annotated[int, typer.Option(help="Base seed recorded in each trace.")] = 0,
    backend: Annotated[
        str, typer.Option(help="Physics backend: 'pybullet' or 'mujoco'.")
    ] = "pybullet",
    controller: Annotated[
        str,
        typer.Option(
            help="Controller: 'sinusoid', 'cpg', 'target_seek' (needs a task with a target), "
            "'posture' (PD balance), or a path to a controller.json."
        ),
    ] = "sinusoid",
    runs_dir: Annotated[
        Path, typer.Option(help="Directory to save benchmark runs under.")
    ] = DEFAULT_RUNS_DIR,
    out: Annotated[
        Path | None, typer.Option("--out", "-o", help="Write benchmark JSON here.")
    ] = None,
    json_output: Annotated[
        bool, typer.Option("--json", help="Print benchmark JSON instead of a table.")
    ] = False,
) -> None:
    """Run a reproducible local benchmark over the packaged zoo."""
    if not zoo:
        console.print("[red]error:[/red] use --zoo to benchmark packaged creatures")
        raise typer.Exit(code=2)
    if attempts < 1:
        console.print("[red]error:[/red] --attempts must be at least 1")
        raise typer.Exit(code=2)

    from creature_lab.zoo import (
        default_task_name,
        list_zoo_creatures,
        zoo_baseline,
        zoo_creature,
        zoo_tasks,
    )

    pairs: list[tuple[str, str]] = []
    for name in list_zoo_creatures():
        task_name = task or default_task_name(name)
        if task_name in zoo_tasks(name):
            pairs.append((name, task_name))
    if not pairs:
        console.print(f"[red]error:[/red] no zoo creatures include task {task!r}")
        raise typer.Exit(code=1)

    results: list[dict[str, Any]] = []
    for name, task_name in pairs:
        creature, task_spec = zoo_creature(name, task_name)
        _check_inputs(creature, task_spec)
        scores: list[float] = []
        run_dirs: list[str] = []
        for index in range(attempts):
            trace = _simulate(
                creature,
                task_spec,
                seed=seed + index,
                controller=controller,
                backend=backend,
            )
            run_dir = save_run(creature, trace, runs_dir=runs_dir, task=task_spec)
            scores.append(trace.score)
            run_dirs.append(str(run_dir))

        baseline = zoo_baseline(name, task_name, backend=backend)
        baseline_score = baseline.get("best_score") if baseline else None
        threshold = None
        passed = None
        best_score = max(scores)
        if isinstance(baseline_score, int | float):
            threshold = baseline_score * 0.9 if baseline_score > 0 else baseline_score
            passed = best_score >= threshold
        results.append(
            {
                "creature": name,
                "task": task_name,
                "backend": backend,
                "controller": controller,
                "seed": seed,
                "attempts": attempts,
                "scores": scores,
                "best_score": best_score,
                "mean_score": sum(scores) / len(scores),
                "baseline_score": baseline_score,
                "pass_threshold": threshold,
                "passed": passed,
                "runs": run_dirs,
            }
        )

    payload = {
        "kind": "zoo_benchmark",
        "backend": backend,
        "controller": controller,
        "seed": seed,
        "attempts": attempts,
        "results": results,
    }
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2))

    if json_output:
        _print_json(payload)
        return

    table = Table(title=f"zoo benchmark ({len(results)} pair(s), {attempts} attempt(s))")
    table.add_column("creature")
    table.add_column("task")
    table.add_column("best", justify="right")
    table.add_column("baseline", justify="right")
    table.add_column("pass")
    for result in results:
        passed_value = result["passed"]
        if passed_value is None:
            status = "-"
        else:
            status = "[green]yes[/green]" if passed_value else "[red]no[/red]"
        baseline_value = result["baseline_score"]
        table.add_row(
            result["creature"],
            result["task"],
            f"{result['best_score']:.4f}",
            "-" if baseline_value is None else f"{baseline_value:.4f}",
            status,
        )
    console.print(table)
    if out is not None:
        console.print(f"[green]wrote[/green] benchmark JSON -> {out}")


@app.command(rich_help_panel="Advanced")
def lineage(
    path: Annotated[
        Path, typer.Argument(help="Path to an evolve run directory (or lineage.json).")
    ],
    best: Annotated[
        int | None, typer.Option(help="Instead of the tree, list the top-N scoring candidates.")
    ] = None,
) -> None:
    """Print the ancestral lineage of an evolve run as a tree (or its top candidates)."""
    lineage_path = path / "lineage.json" if path.is_dir() else path
    if not lineage_path.exists():
        console.print(f"[red]error:[/red] no lineage.json at {lineage_path}")
        raise typer.Exit(code=2)
    data = json.loads(lineage_path.read_text())
    nodes = data["nodes"]

    if best is not None:
        ranked = sorted(nodes, key=lambda n: n["score"], reverse=True)[: max(0, best)]
        table = Table(title=f"top {best} candidates ({data.get('strategy', '?')})")
        table.add_column("rank", justify="right")
        table.add_column("attempt", justify="right")
        table.add_column("score", justify="right")
        for rank, node in enumerate(ranked, start=1):
            table.add_row(str(rank), str(node["index"]), f"{node['score']:.4f}")
        console.print(table)
        return

    children: dict[int | None, list[dict]] = {}
    for node in nodes:
        children.setdefault(node["parent"], []).append(node)

    console.print(f"[bold]lineage[/bold] ({data.get('strategy', '?')}) - {len(nodes)} candidate(s)")

    def render(parent: int | None, depth: int) -> None:
        for node in sorted(children.get(parent, []), key=lambda n: n["index"]):
            mark = "[green]*[/green]" if node["accepted"] else " "
            indent = "  " * depth
            suffix = f" - {node['note']}" if node.get("note") else ""
            console.print(f"{indent}{mark} #{node['index']} score={node['score']:.4f}{suffix}")
            render(node["index"], depth + 1)

    render(None, 0)


archive_app = typer.Typer(help="Inspect and export cells from a MAP-Elites archive.")
app.add_typer(archive_app, name="archive", rich_help_panel="Advanced")


def _load_archive(path: Path) -> dict[str, Any]:
    archive_path = path / "archive.json" if path.is_dir() else path
    if not archive_path.exists():
        console.print(f"[red]error:[/red] no archive.json at {archive_path}")
        raise typer.Exit(code=2)
    return json.loads(archive_path.read_text())


@archive_app.command("show")
def archive_show(
    path: Annotated[
        Path, typer.Argument(help="Path to a map_elites evolve run directory (or archive.json).")
    ],
    html_out: Annotated[
        Path | None,
        typer.Option("--html", help="Write a visual heatmap instead of printing a table."),
    ] = None,
    task: Annotated[
        Path | None,
        typer.Option(help="TaskSpec JSON to render a replay GIF per cell (needs --html)."),
    ] = None,
    width: Annotated[int, typer.Option(help="Per-cell GIF width in pixels.")] = 160,
    height: Annotated[int, typer.Option(help="Per-cell GIF height in pixels.")] = 120,
) -> None:
    """Show a MAP-Elites archive: a ranked table, or --html for a scored heatmap."""
    archive = _load_archive(path)

    if html_out is not None:
        from creature_lab.reports_html import archive_to_html

        cell_gifs: dict[str, str] = {}
        if task is not None:
            import base64
            import tempfile

            try:
                from creature_lab.backends.pybullet_backend import render_trace
                from creature_lab.viewers.video_exporter import write_animation
            except ImportError as exc:
                console.print(
                    "[red]error:[/red] --task GIFs need `uv sync --extra sim --extra export`."
                )
                raise typer.Exit(code=2) from exc
            task_spec = _load_spec(task, TaskSpec)
            # Embed as data: URIs (like the run report's GIF) so the page stays a single
            # self-contained file instead of depending on a sibling directory of images.
            with tempfile.TemporaryDirectory() as tmp:
                for cell_key, entry in archive.items():
                    cell_creature = CreatureSpec.model_validate(entry["spec"])
                    trace = _simulate(cell_creature, task_spec)
                    gif_path = Path(tmp) / f"{cell_key.replace(',', '_')}.gif"
                    frames = render_trace(
                        cell_creature, trace, task=task_spec, width=width, height=height
                    )
                    write_animation(frames, gif_path)
                    encoded = base64.b64encode(gif_path.read_bytes()).decode("ascii")
                    cell_gifs[cell_key] = f"data:image/gif;base64,{encoded}"

        html_out.parent.mkdir(parents=True, exist_ok=True)
        html_out.write_text(archive_to_html(archive, cell_gifs=cell_gifs))
        console.print(f"[green]wrote[/green] archive heatmap -> {html_out}")
        return

    table = Table(title=f"archive: {len(archive)} filled cell(s)")
    table.add_column("cell")
    table.add_column("score", justify="right")
    table.add_column("features")
    for cell_key, entry in sorted(archive.items(), key=lambda kv: -kv[1]["score"]):
        features = ", ".join(f"{f:.3f}" for f in entry["features"])
        table.add_row(cell_key, f"{entry['score']:.4f}", features)
    console.print(table)


@archive_app.command("export")
def archive_export(
    path: Annotated[
        Path, typer.Argument(help="Path to a map_elites evolve run directory (or archive.json).")
    ],
    cell: Annotated[
        str, typer.Option(help="Cell key as 'row,col' (see `archive show`), e.g. '3,2'.")
    ],
    out: Annotated[Path, typer.Option("--out", "-o", help="Output CreatureSpec JSON path.")],
) -> None:
    """Export one MAP-Elites archive cell as a standalone, editable CreatureSpec JSON."""
    archive = _load_archive(path)
    entry = archive.get(cell)
    if entry is None:
        available = ", ".join(sorted(archive)) or "(none)"
        console.print(f"[red]error:[/red] unknown cell {cell!r}; choose one of: {available}")
        raise typer.Exit(code=2)
    if "spec" not in entry:
        console.print(
            "[red]error:[/red] this archive.json has no stored spec "
            "(from before `archive export` support); re-run `evolve --strategy map_elites`."
        )
        raise typer.Exit(code=2)

    creature = CreatureSpec.model_validate(entry["spec"])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(creature.model_dump_json(indent=2))
    console.print(f"[green]exported[/green] cell {cell!r} (score={entry['score']:.4f}) -> {out}")


@app.command(rich_help_panel="Run And Improve")
def ask(
    goal: Annotated[str, typer.Argument(help="Plain-language design goal.")],
    creature_path: Annotated[Path, typer.Argument(help="Path to a CreatureSpec JSON file.")],
    task: Annotated[Path, typer.Option(help="Path to a TaskSpec JSON file.")],
    attempts: Annotated[int, typer.Option(help="Number of design attempts.")] = 5,
    offline: Annotated[
        bool, typer.Option(help="Use the built-in no-LLM tool policy instead of a model.")
    ] = False,
    model: Annotated[str, typer.Option(help="LiteLLM model id (online mode).")] = "gpt-4o-mini",
    seed: Annotated[int, typer.Option(help="Seed for the offline policy.")] = 0,
    runs_dir: Annotated[
        Path, typer.Option(help="Directory to save the best creature and traces under.")
    ] = DEFAULT_RUNS_DIR,
    json_output: Annotated[
        bool, typer.Option("--json", help="Print machine-readable best-run metadata.")
    ] = False,
) -> None:
    """Iteratively improve a creature toward a goal using validated design tools.

    Online mode asks an LLM (via LiteLLM, the `llm` extra) for each tool call;
    `--offline` uses a deterministic no-provider policy so it runs anywhere.
    """
    from creature_lab.agents.loop import Policy, design_loop

    creature = _load_spec(creature_path, CreatureSpec)
    task_spec = _load_spec(task, TaskSpec)
    _check_inputs(creature, task_spec)

    policy: Policy
    if offline:
        from creature_lab.agents.baseline import RandomToolPolicy

        policy = RandomToolPolicy(seed)
    else:
        try:
            import litellm  # noqa: F401

            from creature_lab.agents.llm import LLMPolicy
        except ImportError as exc:
            console.print(
                "[red]error:[/red] litellm is not installed. Use --offline or "
                "`uv sync --extra llm`."
            )
            raise typer.Exit(code=2) from exc
        policy = LLMPolicy(model=model)

    def diagnose_fn(candidate: CreatureSpec) -> str:
        from creature_lab.diagnosis import diagnose as run_diagnosis

        result = run_diagnosis(_simulate(candidate, task_spec), candidate, task_spec)
        if not result.patterns:
            return ""
        return "; ".join(
            f"{pattern} ({suggestion})" if suggestion else pattern
            for pattern, suggestion in zip(result.patterns, result.suggestions, strict=True)
        )

    result = design_loop(
        creature,
        lambda candidate: _simulate(candidate, task_spec).score,
        policy,
        attempts=attempts,
        goal=goal,
        task_name=task_spec.name,
        diagnose=diagnose_fn,
    )

    best_trace = _simulate(result.best, task_spec, seed=seed)
    run_dir = save_run(result.best, best_trace, runs_dir=runs_dir, task=task_spec)
    (run_dir / "agent.json").write_text(result.trace.model_dump_json(indent=2))
    if json_output:
        payload = _saved_run_payload(result.best, task_spec, best_trace, run_dir)
        payload["goal"] = goal
        payload["attempts"] = attempts
        payload["best_score"] = result.best_score
        payload["accepted_edits"] = len(
            [step for step in result.trace.steps if step.accepted and step.attempt > 0]
        )
        _print_json(payload)
        return

    table = Table(title=f"ask {goal!r} ({attempts} attempts)")
    table.add_column("attempt", justify="right")
    table.add_column("action")
    table.add_column("score", justify="right")
    table.add_column("result")
    for step in result.trace.steps:
        if step.attempt == 0:
            label, style = "seed", "green"
        elif not step.valid:
            label, style = "invalid", "red"
        elif step.accepted:
            label, style = "kept", "green"
        else:
            label, style = "rejected", "dim"
        score = f"{step.score:.4f}" if step.score is not None else "-"
        table.add_row(str(step.attempt), step.action, score, f"[{style}]{label}[/{style}]")
    console.print(table)

    console.print(
        f"[green]best[/green] score={result.best_score:.4f} "
        f"(seed score={result.trace.steps[0].score:.4f}) -> {run_dir}"
    )


@app.command(rich_help_panel="Replay And Debug")
def inspect(
    path: Annotated[Path, typer.Argument(help="Path to a run directory (or trace.json).")],
    runs_dir: Annotated[
        Path, typer.Option(help="Directory used when resolving the `latest` alias.")
    ] = DEFAULT_RUNS_DIR,
    json_output: Annotated[
        bool, typer.Option("--json", help="Print machine-readable inspection data.")
    ] = False,
) -> None:
    """Print a detailed diagnostic summary of a saved run."""
    from creature_lab.terrain import describe_terrain

    trace = _load_spec(_resolve_trace_path(path, runs_dir), EpisodeTrace)
    task = _load_task_for_trace(path, None, runs_dir)
    # Best-effort: creature.json may not exist next to an arbitrary trace.json path,
    # unlike `diagnose` (which requires it). When present it gives an accurate,
    # reward-independent `fell` instead of one that depends on reward.fall_penalty.
    creature_candidate = _run_dir_for(path, runs_dir=runs_dir) / "creature.json"
    creature = _load_spec(creature_candidate, CreatureSpec) if creature_candidate.exists() else None
    summary = summarize_episode(trace, task, creature)
    meta = trace.meta
    if json_output:
        _print_json(
            {
                "run_id": trace.run_id,
                "creature": trace.creature_name,
                "task": trace.task_name,
                "backend": trace.backend,
                "score": trace.score,
                "terrain": describe_terrain(task.terrain) if task is not None else None,
                "summary": summary.model_dump(),
                "meta": meta.model_dump() if meta else None,
            }
        )
        return

    table = Table(title=f"run {trace.run_id!r}: {trace.creature_name!r} on {trace.task_name!r}")
    table.add_column("field")
    table.add_column("value")

    def row(field: str, value: object) -> None:
        table.add_row(field, str(value))

    if meta is not None:
        row("schema / lab version", f"{meta.schema_version} / {meta.lab_version}")
        row("backend", meta.backend_version or "-")
        row("controller", meta.controller or "-")
        row("creature hash", meta.creature_hash or "-")
        row("task hash", meta.task_hash or "-")
        row("timestep / seed", f"{meta.timestep} / {meta.seed}")
    else:
        row("metadata", "[yellow]none (legacy trace)[/yellow]")
    if task is not None:
        row("terrain", describe_terrain(task.terrain))
    row("frames / duration (s)", f"{summary.frame_count} / {summary.duration:.2f}")
    row("final score", f"{summary.final_score:.4f}")
    if summary.component_scores:
        breakdown = ", ".join(f"{k}={v:.4f}" for k, v in summary.component_scores.items())
        row("score breakdown", breakdown)
    row(
        "net displacement / forward Δx",
        f"{summary.net_displacement:.4f} / {summary.forward_displacement:.4f}",
    )
    if summary.target_progress is not None:
        row("target progress", f"{summary.target_progress:.4f}")
    row("joint motion (Σ|Δrad|)", f"{summary.total_joint_motion:.4f}")
    row("fell", "-" if summary.fell is None else summary.fell)
    row("damage events", ", ".join(summary.damage_events) or "none")
    row(
        "contacts by part",
        ", ".join(f"{part}={count}" for part, count in summary.contacts_by_part.items()) or "none",
    )
    console.print(table)
    for warning in summary.warnings:
        console.print(f"[yellow]warning:[/yellow] {warning}")


@app.command(rich_help_panel="Replay And Debug")
def report(
    path: Annotated[Path, typer.Argument(help="Path to a run directory, trace.json, or `latest`.")],
    out: Annotated[
        Path | None, typer.Option("--out", "-o", help="Write the report here instead of stdout.")
    ] = None,
    html_out: Annotated[
        Path | None,
        typer.Option("--html", help="Also write a self-contained HTML run report here."),
    ] = None,
    runs_dir: Annotated[
        Path, typer.Option(help="Directory used when resolving the `latest` alias.")
    ] = DEFAULT_RUNS_DIR,
    json_output: Annotated[
        bool, typer.Option("--json", help="Render the report as JSON instead of Markdown.")
    ] = False,
) -> None:
    """Generate a concise run report with score, diagnostics, and artifact paths."""
    from creature_lab.reports import build_report, build_report_bundle, report_to_markdown

    try:
        if html_out is not None:
            data, trace, creature, task_spec = build_report_bundle(path, runs_dir=runs_dir)
        else:
            data = build_report(path, runs_dir=runs_dir)
    except FileNotFoundError as exc:
        console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=2) from exc

    if html_out is not None:
        from creature_lab.reports_html import report_to_html

        html_out.parent.mkdir(parents=True, exist_ok=True)
        html_out.write_text(report_to_html(data, trace, creature, task_spec))
        console.print(f"[green]wrote[/green] HTML report -> {html_out}")

    rendered = (
        json.dumps(data, indent=2, sort_keys=True) if json_output else report_to_markdown(data)
    )
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(rendered)
        console.print(f"[green]wrote[/green] report -> {out}")
        return
    if html_out is not None:
        return
    _write_stdout(rendered)


@app.command(rich_help_panel="Replay And Debug")
def diagnose(
    path: Annotated[Path, typer.Argument(help="Path to a run directory (or trace.json).")],
    creature_path: Annotated[
        Path | None,
        typer.Option(
            "--creature", help="CreatureSpec JSON (defaults to creature.json in the run dir)."
        ),
    ] = None,
    task: Annotated[
        Path | None, typer.Option(help="TaskSpec JSON (defaults to task.json in the run dir).")
    ] = None,
    runs_dir: Annotated[
        Path, typer.Option(help="Directory used when resolving the `latest` alias.")
    ] = DEFAULT_RUNS_DIR,
    json_output: Annotated[
        bool, typer.Option("--json", help="Print machine-readable diagnosis data.")
    ] = False,
) -> None:
    """Explain *why* a creature failed: locomotion signals + matched failure patterns."""
    from creature_lab.diagnosis import diagnose as run_diagnosis

    trace = _load_spec(_resolve_trace_path(path, runs_dir), EpisodeTrace)
    creature = _load_creature_for_trace(path, creature_path, runs_dir)
    task_spec = _load_task_for_trace(path, task, runs_dir)
    result = run_diagnosis(trace, creature, task_spec)
    if json_output:
        _print_json(
            {
                "run_id": trace.run_id,
                "creature": trace.creature_name,
                "task": trace.task_name,
                "metrics": result.metrics,
                "patterns": result.patterns,
                "explanations": result.explanations,
                "suggestions": result.suggestions,
            }
        )
        return

    table = Table(title=f"diagnosis: {trace.run_id!r} ({trace.creature_name!r})")
    table.add_column("signal")
    table.add_column("value", justify="right")
    m = result.metrics
    table.add_row("forward displacement (m)", f"{m['forward_displacement']:+.3f}")
    table.add_row("lateral displacement (m)", f"{m['lateral_displacement']:.3f}")
    table.add_row("net horizontal travel (m)", f"{m['net_displacement']:.3f}")
    table.add_row("total joint motion (rad)", f"{m['total_joint_motion']:.1f}")
    fall = m["fall_time"]
    table.add_row("fall", "no" if fall < 0 else f"yes at t={fall:.2f}s")
    table.add_row("CoM height std (m)", f"{m['com_height_std']:.3f}")
    table.add_row("frames in ground contact", f"{m['contact_frames_fraction']:.0%}")
    console.print(table)

    if not result.patterns:
        console.print("[green]no failure patterns detected[/green] - this run looks healthy.")
        return

    console.print("\n[bold]Root-cause patterns detected:[/bold]")
    for pattern, explanation in zip(result.patterns, result.explanations, strict=True):
        console.print(f"  [yellow]! {pattern}[/yellow] - {explanation}")
    console.print("\n[bold]Suggested edits:[/bold]")
    for index, suggestion in enumerate(result.suggestions, start=1):
        console.print(f"  {index}. {suggestion}")


@app.command(rich_help_panel="Replay And Debug")
def view(
    path: Annotated[Path, typer.Argument(help="Path to a trace.json file or run directory.")],
    creature_path: Annotated[
        Path | None,
        typer.Option(
            "--creature", help="CreatureSpec JSON (defaults to creature.json in the run dir)."
        ),
    ] = None,
    task: Annotated[
        Path | None, typer.Option(help="Optional TaskSpec JSON to draw the target marker.")
    ] = None,
    runs_dir: Annotated[
        Path, typer.Option(help="Directory used when resolving the `latest` alias.")
    ] = DEFAULT_RUNS_DIR,
    fps: Annotated[float, typer.Option(help="Playback frames per second.")] = 30.0,
    host: HostOption = DEFAULT_HOST,
    port: Annotated[int, typer.Option(help="Port for the Viser server.")] = 8080,
    open_browser: Annotated[
        bool,
        typer.Option(
            "--open-browser/--no-open-browser",
            help="Open the local viewer URL in the default browser.",
        ),
    ] = False,
    debug: Annotated[bool, typer.Option(help="Overlay CoM/root trails and a fall marker.")] = False,
) -> None:
    """Replay a saved trace in a Viser browser viewer (renders poses, no physics)."""
    trace = _load_spec(_resolve_trace_path(path, runs_dir), EpisodeTrace)
    creature = _load_creature_for_trace(path, creature_path, runs_dir)
    task_spec = _load_task_for_trace(path, task, runs_dir)

    try:
        from creature_lab.viewers.viser_viewer import play_trace
    except ImportError as exc:
        console.print(
            "[red]error:[/red] viser is not installed. Install it with `uv sync --extra viz`."
        )
        raise typer.Exit(code=2) from exc

    _warn_if_network_exposed(host)
    console.print(
        f"[green]serving[/green] {trace.run_id!r} on http://localhost:{port} (Ctrl+C to stop)"
    )
    play_trace(
        creature,
        trace,
        task=task_spec,
        fps=fps,
        host=host,
        port=port,
        debug=debug,
        open_browser=open_browser,
    )


@app.command(rich_help_panel="Advanced")
def compare(
    run_a: Annotated[Path, typer.Argument(help="First run directory (or trace.json).")],
    run_b: Annotated[Path, typer.Argument(help="Second run directory (or trace.json).")],
    gap: Annotated[float, typer.Option(help="Sideways spacing between the two creatures.")] = 1.0,
    fps: Annotated[float, typer.Option(help="Playback frames per second.")] = 30.0,
    host: HostOption = DEFAULT_HOST,
    port: Annotated[int, typer.Option(help="Port for the Viser server.")] = 8080,
    open_browser: Annotated[
        bool,
        typer.Option(
            "--open-browser/--no-open-browser",
            help="Open the local viewer URL in the default browser.",
        ),
    ] = False,
    html_out: Annotated[
        Path | None,
        typer.Option(
            "--html", help="Write a before/after comparison report instead of opening Viser."
        ),
    ] = None,
    runs_dir: Annotated[
        Path, typer.Option(help="Directory used when resolving bare run ids or `latest`.")
    ] = DEFAULT_RUNS_DIR,
) -> None:
    """Replay two saved runs side by side in one Viser scene, or diff their reports."""
    if html_out is not None:
        from creature_lab.reports import build_comparison, build_report_bundle
        from creature_lab.reports_html import comparison_to_html

        try:
            report_a, trace_a, creature_a, _task_a = build_report_bundle(run_a, runs_dir=runs_dir)
            report_b, trace_b, creature_b, _task_b = build_report_bundle(run_b, runs_dir=runs_dir)
        except FileNotFoundError as exc:
            console.print(f"[red]error:[/red] {exc}")
            raise typer.Exit(code=2) from exc
        comparison = build_comparison(report_a, report_b)
        html_out.parent.mkdir(parents=True, exist_ok=True)
        html_out.write_text(
            comparison_to_html(
                report_a,
                report_b,
                comparison,
                creature_a=creature_a,
                trace_a=trace_a,
                creature_b=creature_b,
                trace_b=trace_b,
            )
        )
        console.print(f"[green]wrote[/green] comparison report -> {html_out}")
        return

    trace_a = _load_spec(_resolve_trace_path(run_a, runs_dir), EpisodeTrace)
    trace_b = _load_spec(_resolve_trace_path(run_b, runs_dir), EpisodeTrace)
    creature_a = _load_creature_for_trace(run_a, None, runs_dir)
    creature_b = _load_creature_for_trace(run_b, None, runs_dir)

    try:
        from creature_lab.viewers.viser_viewer import compare_traces
    except ImportError as exc:
        console.print(
            "[red]error:[/red] viser is not installed. Install it with `uv sync --extra viz`."
        )
        raise typer.Exit(code=2) from exc

    _warn_if_network_exposed(host)
    console.print(
        f"[green]serving[/green] {trace_a.run_id!r} vs {trace_b.run_id!r} "
        f"on http://localhost:{port} (Ctrl+C to stop)"
    )
    compare_traces(
        creature_a,
        trace_a,
        creature_b,
        trace_b,
        task_a=_load_task_for_trace(run_a, None, runs_dir),
        task_b=_load_task_for_trace(run_b, None, runs_dir),
        gap=gap,
        fps=fps,
        host=host,
        port=port,
        open_browser=open_browser,
    )


@app.command(rich_help_panel="Advanced")
def robustness(
    path: Annotated[
        Path,
        typer.Argument(help="Path to a run directory or `latest` (needs creature.json+task.json)."),
    ],
    trials: Annotated[int, typer.Option(help="Number of perturbed re-simulations.")] = 10,
    seed: Annotated[int, typer.Option(help="Base seed; trial i uses seed + i.")] = 0,
    mass_jitter: Annotated[
        float, typer.Option(help="Max fractional per-part mass perturbation.")
    ] = 0.05,
    friction_jitter: Annotated[
        float, typer.Option(help="Max fractional terrain-friction perturbation.")
    ] = 0.05,
    backend: Annotated[str, typer.Option(help="Physics backend: 'pybullet' or 'mujoco'.")] = (
        "pybullet"
    ),
    controller: Annotated[
        str,
        typer.Option(
            help="Controller: 'sinusoid', 'cpg', 'target_seek' (needs a task with a target), "
            "'posture' (PD balance), or a path to a controller.json."
        ),
    ] = "sinusoid",
    save: Annotated[
        bool,
        typer.Option(help="Save a new run (trace.json + robustness.json) under --runs-dir."),
    ] = False,
    runs_dir: Annotated[
        Path, typer.Option(help="Directory used when resolving `latest`, and to save --save runs.")
    ] = DEFAULT_RUNS_DIR,
    json_output: Annotated[
        bool, typer.Option("--json", help="Print machine-readable results.")
    ] = False,
) -> None:
    """Re-simulate a creature/task under small seeded mass/friction perturbations.

    Reveals gaits that only work for the exact recorded body/terrain parameters: a wide
    score spread or a high fail rate means the result is fragile, not robust.
    """
    from creature_lab.robustness import run_trials

    creature = _load_creature_for_trace(path, None, runs_dir)
    task_spec = _load_task_for_trace(path, None, runs_dir)
    if task_spec is None:
        console.print("[red]error:[/red] no task.json found for this run")
        raise typer.Exit(code=2)

    def evaluate(trial_creature: CreatureSpec, trial_task: TaskSpec) -> tuple[float, bool]:
        trace = _simulate(trial_creature, trial_task, backend=backend, controller=controller)
        return trace.score, bool(summarize_episode(trace, trial_task, trial_creature).fell)

    result = run_trials(
        creature,
        task_spec,
        evaluate,
        trials=trials,
        seed=seed,
        mass_jitter=mass_jitter,
        friction_jitter=friction_jitter,
    )

    payload = {
        "creature": creature.name,
        "task": task_spec.name,
        "trials": [
            {
                "seed": t.seed,
                "score": t.score,
                "fell": t.fell,
                "mass_scale": t.mass_scale,
                "friction_scale": t.friction_scale,
            }
            for t in result.trials
        ],
        "mean_score": result.mean_score,
        "std_score": result.std_score,
        "min_score": result.min_score,
        "max_score": result.max_score,
        "fail_rate": result.fail_rate,
    }

    if save:
        baseline_trace = _simulate(creature, task_spec, backend=backend, controller=controller)
        run_dir = save_run(creature, baseline_trace, runs_dir=runs_dir, task=task_spec)
        (run_dir / "robustness.json").write_text(json.dumps(payload, indent=2))
        console.print(f"[green]saved[/green] robustness run -> {run_dir}")

    if json_output:
        _print_json(payload)
        return

    table = Table(title=f"robustness: {creature.name!r} on {task_spec.name!r} ({trials} trial(s))")
    table.add_column("seed", justify="right")
    table.add_column("score", justify="right")
    table.add_column("fell")
    for t in result.trials:
        table.add_row(str(t.seed), f"{t.score:.4f}", "yes" if t.fell else "no")
    console.print(table)
    console.print(
        f"mean={result.mean_score:.4f} std={result.std_score:.4f} "
        f"min={result.min_score:.4f} max={result.max_score:.4f} "
        f"fail_rate={result.fail_rate:.0%}"
    )


@app.command(rich_help_panel="Advanced")
def sim2sim(
    path: Annotated[
        Path,
        typer.Argument(help="Path to a run directory or `latest` (needs creature.json+task.json)."),
    ],
    controller: Annotated[
        str,
        typer.Option(
            help="Controller: 'sinusoid', 'cpg', 'target_seek' (needs a task with a target), "
            "'posture' (PD balance), or a path to a controller.json."
        ),
    ] = "sinusoid",
    save: Annotated[
        bool, typer.Option(help="Save a new run (trace.json + sim2sim.json) under --runs-dir.")
    ] = False,
    runs_dir: Annotated[
        Path, typer.Option(help="Directory used when resolving `latest`, and to save --save runs.")
    ] = DEFAULT_RUNS_DIR,
    json_output: Annotated[
        bool, typer.Option("--json", help="Print machine-readable results.")
    ] = False,
) -> None:
    """Run the same creature/task on PyBullet and MuJoCo and report the score/trajectory gap.

    Specs and traces are portable; exact physics is backend-dependent (see the README).
    This measures how big that gap actually is for one creature/task.
    """
    import math

    from creature_lab.viewers.overlays import root_path

    creature = _load_creature_for_trace(path, None, runs_dir)
    task_spec = _load_task_for_trace(path, None, runs_dir)
    if task_spec is None:
        console.print("[red]error:[/red] no task.json found for this run")
        raise typer.Exit(code=2)

    trace_pybullet = _simulate(creature, task_spec, backend="pybullet", controller=controller)
    trace_mujoco = _simulate(creature, task_spec, backend="mujoco", controller=controller)

    path_a = root_path(creature, trace_pybullet)
    path_b = root_path(creature, trace_mujoco)
    n = min(len(path_a), len(path_b))
    divergence = sum(math.dist(path_a[i], path_b[i]) for i in range(n)) / n if n else 0.0
    score_gap = abs(trace_pybullet.score - trace_mujoco.score)

    payload = {
        "creature": creature.name,
        "task": task_spec.name,
        "pybullet": {
            "score": trace_pybullet.score,
            "backend_version": trace_pybullet.meta.backend_version if trace_pybullet.meta else None,
        },
        "mujoco": {
            "score": trace_mujoco.score,
            "backend_version": trace_mujoco.meta.backend_version if trace_mujoco.meta else None,
        },
        "score_gap": score_gap,
        "mean_root_divergence": divergence,
    }

    if save:
        run_dir = save_run(creature, trace_pybullet, runs_dir=runs_dir, task=task_spec)
        (run_dir / "sim2sim.json").write_text(json.dumps(payload, indent=2))
        console.print(f"[green]saved[/green] sim2sim run -> {run_dir}")

    if json_output:
        _print_json(payload)
        return

    table = Table(title=f"sim2sim: {creature.name!r} on {task_spec.name!r}")
    table.add_column("backend")
    table.add_column("score", justify="right")
    table.add_row("pybullet", f"{trace_pybullet.score:.4f}")
    table.add_row("mujoco", f"{trace_mujoco.score:.4f}")
    console.print(table)
    console.print(f"score gap: {score_gap:.4f}")
    console.print(f"mean root-position divergence: {divergence:.4f} m (top-down path, per frame)")


@app.command(rich_help_panel="Run And Improve")
def qualify(
    creature_path: Annotated[Path, typer.Argument(help="Path to a CreatureSpec JSON file.")],
    task: Annotated[Path, typer.Option(help="Path to a TaskSpec JSON file.")],
    profile: Annotated[
        str,
        typer.Option(
            help="Qualification profile: " + ", ".join(qualification.BUILTIN_PROFILES) + "."
        ),
    ] = "basic-locomotion",
    controller: Annotated[
        str,
        typer.Option(
            help="Controller: 'sinusoid', 'cpg', 'target_seek' (needs a task with a target), "
            "'posture' (PD balance), or a path to a controller.json."
        ),
    ] = "sinusoid",
    backend: Annotated[str, typer.Option(help="Physics backend: 'pybullet' or 'mujoco'.")] = (
        "pybullet"
    ),
    check_portability: Annotated[
        bool,
        typer.Option(
            help="Also run the baseline on the other backend for a portability check, even "
            "if the profile doesn't require one (slower: one extra full episode)."
        ),
    ] = False,
    seed: Annotated[int, typer.Option(help="Base seed for the robustness sweep.")] = 0,
    json_output: Annotated[
        bool, typer.Option("--json", help="Print machine-readable results.")
    ] = False,
) -> None:
    """Combine a baseline run, a robustness sweep, and (optionally) a cross-backend
    comparison into one pass/fail result with a named primary blocker.

    Qualification composes existing capabilities rather than being a new isolated
    check - see `robustness` and `sim2sim` for the pieces run standalone.
    """
    if profile not in qualification.BUILTIN_PROFILES:
        available = ", ".join(qualification.BUILTIN_PROFILES)
        console.print(f"[red]error:[/red] unknown profile {profile!r}; choose one of: {available}")
        raise typer.Exit(code=2)
    profile_spec = qualification.BUILTIN_PROFILES[profile]

    creature = _load_spec(creature_path, CreatureSpec)
    task_spec = _load_spec(task, TaskSpec)
    _check_inputs(creature, task_spec)

    def simulate(c: CreatureSpec, t: TaskSpec) -> EpisodeTrace:
        return _simulate(c, t, seed=seed, controller=controller, backend=backend)

    simulate_other_backend = None
    if profile_spec.max_sim2sim_gap is not None or check_portability:
        other_backend = "mujoco" if backend == "pybullet" else "pybullet"

        def simulate_other_backend(c: CreatureSpec, t: TaskSpec) -> EpisodeTrace:
            return _simulate(c, t, seed=seed, controller=controller, backend=other_backend)

    result = qualification.qualify(
        creature,
        task_spec,
        profile_spec,
        simulate=simulate,
        simulate_other_backend=simulate_other_backend,
    )

    if json_output:
        _print_json(
            {
                "creature": creature.name,
                "task": task_spec.name,
                "profile": result.profile,
                "passed": result.passed,
                "checks": [
                    {"name": c.name, "passed": c.passed, "detail": c.detail} for c in result.checks
                ],
                "primary_blocker": result.primary_blocker,
                "recommended_next_test": result.recommended_next_test,
            }
        )
        return

    verdict = "[green]PASS[/green]" if result.passed else "[red]FAIL[/red]"
    console.print(f"QUALIFICATION: {verdict}  (profile: {profile_spec.name})")
    console.print(f"[dim]{profile_spec.description}[/dim]")
    console.print()
    table = Table(show_header=False)
    table.add_column("status", width=6)
    table.add_column("check")
    table.add_column("detail")
    for check in result.checks:
        status = "[green]PASS[/green]" if check.passed else "[red]FAIL[/red]"
        table.add_row(status, check.name, check.detail)
    console.print(table)
    if result.primary_blocker is not None:
        console.print()
        console.print(f"[yellow]Primary blocker:[/yellow] {result.primary_blocker}")
        console.print(f"[yellow]Recommended next test:[/yellow] {result.recommended_next_test}")


@app.command("autopsy", rich_help_panel="Run And Improve")
def autopsy_cmd(
    creature_path: Annotated[Path, typer.Argument(help="Path to a CreatureSpec JSON file.")],
    task: Annotated[Path, typer.Option(help="Path to a TaskSpec JSON file.")],
    controller: Annotated[
        str,
        typer.Option(
            help="Controller under investigation; compare it against the curated controller."
        ),
    ] = "sinusoid",
    backend: Annotated[str, typer.Option(help="Primary backend: pybullet or mujoco.")] = "pybullet",
    profile: Annotated[
        str, typer.Option(help="Qualification profile, or 'auto' to infer it from the task.")
    ] = "auto",
    robustness_trials: Annotated[
        int, typer.Option(help="Seeded mass/friction counterfactual trials.")
    ] = 5,
    check_portability: Annotated[
        bool, typer.Option(help="Also compare the baseline on the other physics backend.")
    ] = False,
    out: Annotated[
        Path | None,
        typer.Option("--out", "-o", help="Report directory (default: outputs/autopsy_<run>)."),
    ] = None,
    runs_dir: Annotated[Path, typer.Option(help="Directory used to save the baseline run.")] = (
        DEFAULT_RUNS_DIR
    ),
    overwrite: Annotated[
        bool, typer.Option(help="Replace an existing report directory and pack.")
    ] = False,
    json_output: Annotated[
        bool, typer.Option("--json", help="Print the autopsy result as JSON.")
    ] = False,
) -> None:
    """Explain whether a failure most likely comes from control, body/task, fragility,
    or backend sensitivity, then emit a verified reproducible experiment pack.
    """
    from creature_lab.autopsy import (
        autopsy_to_html,
        autopsy_to_markdown,
        distinct_curated_reference,
        infer_profile,
        run_autopsy,
        write_autopsy_evidence,
    )
    from creature_lab.io_utils import atomic_write_text

    if robustness_trials < 1:
        console.print("[red]error:[/red] --robustness-trials must be at least 1")
        raise typer.Exit(code=2)
    if out is not None and out.exists() and any(out.iterdir()) and not overwrite:
        console.print(f"[red]error:[/red] report directory already exists: {out}")
        raise typer.Exit(code=2)
    creature = _load_spec(creature_path, CreatureSpec)
    task_spec = _load_spec(task, TaskSpec)
    _check_inputs(creature, task_spec)
    if profile == "auto":
        profile_spec = infer_profile(task_spec)
    elif profile in qualification.BUILTIN_PROFILES:
        profile_spec = qualification.BUILTIN_PROFILES[profile]
    else:
        console.print(
            f"[red]error:[/red] unknown profile {profile!r}; choose auto or "
            f"{', '.join(qualification.BUILTIN_PROFILES)}"
        )
        raise typer.Exit(code=2)

    def simulate_selected(c: CreatureSpec, t: TaskSpec) -> EpisodeTrace:
        return _simulate(c, t, controller=controller, backend=backend)

    def simulate_reference(c: CreatureSpec, t: TaskSpec) -> EpisodeTrace:
        return _simulate(c, t, controller="curated", backend=backend)

    simulate_other = None
    if check_portability:
        other_backend = "mujoco" if backend == "pybullet" else "pybullet"

        def simulate_other(c: CreatureSpec, t: TaskSpec) -> EpisodeTrace:
            return _simulate(c, t, controller=controller, backend=other_backend)

    result = run_autopsy(
        creature,
        task_spec,
        simulate=simulate_selected,
        simulate_reference=(
            simulate_reference if distinct_curated_reference(creature, controller) else None
        ),
        profile=profile_spec,
        simulate_other_backend=simulate_other,
        robustness_trials=robustness_trials,
    )
    run_dir = save_run(creature, result.baseline_trace, runs_dir=runs_dir, task=task_spec)
    out_dir = out or Path("outputs") / f"autopsy_{result.baseline_trace.run_id}"
    if out_dir.exists() and any(out_dir.iterdir()) and not overwrite:
        console.print(f"[red]error:[/red] report directory already exists: {out_dir}")
        raise typer.Exit(code=2)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = result.to_json_dict()
    payload["run_dir"] = str(run_dir)
    payload["pack_dir"] = str(out_dir / "experiment_pack")
    atomic_write_text(out_dir / "autopsy.json", json.dumps(payload, indent=2, sort_keys=True))
    atomic_write_text(out_dir / "autopsy.md", autopsy_to_markdown(result))
    atomic_write_text(out_dir / "autopsy.html", autopsy_to_html(result))
    export_design_pack(
        creature,
        task_spec,
        result.baseline_trace,
        out_dir=out_dir / "experiment_pack",
        source_dir=run_dir,
        overwrite=overwrite,
    )
    write_autopsy_evidence(result, creature, task_spec, out_dir, overwrite=overwrite)

    if json_output:
        _print_json(payload)
        return
    console.print(
        f"[bold]AUTOPSY:[/bold] {result.primary_cause} "
        f"([cyan]{result.confidence} heuristic evidence strength[/cyan])"
    )
    console.print(result.summary)
    for item in result.evidence:
        status = (
            "[dim]SKIPPED[/dim]"
            if item.passed is None
            else "[green]PASS[/green]"
            if item.passed
            else "[red]FAIL[/red]"
        )
        console.print(f"  {status} {item.name}: {item.detail}")
    console.print(f"[green]wrote[/green] report + verified experiment pack -> {out_dir}")


@app.command(rich_help_panel="Advanced")
def plot(
    path: Annotated[Path, typer.Argument(help="Path to a run directory (or trace.json).")],
    metric: Annotated[
        str, typer.Option(help="Metric: joint_energy, score, com_height, forward_x.")
    ] = "joint_energy",
    out: Annotated[
        Path | None, typer.Option("--out", "-o", help="Save a PNG here (else open a window).")
    ] = None,
    runs_dir: Annotated[
        Path, typer.Option(help="Directory used when resolving the `latest` alias.")
    ] = DEFAULT_RUNS_DIR,
) -> None:
    """Plot a per-frame metric for a saved run."""
    trace = _load_spec(_resolve_trace_path(path, runs_dir), EpisodeTrace)
    creature = _load_creature_for_trace(path, None, runs_dir)

    try:
        from creature_lab.viewers.plotting import plot_metric
    except ImportError as exc:
        console.print(
            "[red]error:[/red] matplotlib is not installed. Install it with `uv sync --extra viz`."
        )
        raise typer.Exit(code=2) from exc

    try:
        result = plot_metric(creature, trace, metric, out=out)
    except ValueError as exc:
        console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    if result is not None:
        console.print(f"[green]saved[/green] {metric} plot -> {result}")


@app.command(rich_help_panel="Replay And Debug")
def export(
    path: Annotated[Path, typer.Argument(help="Path to a trace.json file or run directory.")],
    out: Annotated[
        Path | None, typer.Option("--out", "-o", help="Output .gif or .mp4 path.")
    ] = None,
    gif: Annotated[
        Path | None, typer.Option("--gif", help="Output GIF path (alias for --out).")
    ] = None,
    creature_path: Annotated[
        Path | None,
        typer.Option(
            "--creature", help="CreatureSpec JSON (defaults to creature.json in the run dir)."
        ),
    ] = None,
    runs_dir: Annotated[
        Path, typer.Option(help="Directory used when resolving the `latest` alias.")
    ] = DEFAULT_RUNS_DIR,
    fps: Annotated[float, typer.Option(help="Frames per second in the output.")] = 30.0,
    width: Annotated[int, typer.Option(help="Render width in pixels.")] = 640,
    height: Annotated[int, typer.Option(help="Render height in pixels.")] = 480,
) -> None:
    """Render a saved trace to a shareable GIF or MP4 (replays poses, no physics)."""
    out_path = gif or out
    if out_path is None:
        console.print("[red]error:[/red] provide --out or --gif")
        raise typer.Exit(code=2)
    trace = _load_spec(_resolve_trace_path(path, runs_dir), EpisodeTrace)
    creature = _load_creature_for_trace(path, creature_path, runs_dir)
    task_spec = _load_task_for_trace(path, None, runs_dir)

    try:
        from creature_lab.backends.pybullet_backend import render_trace
    except ImportError as exc:
        console.print(
            "[red]error:[/red] pybullet is not installed. Install it with `uv sync --extra sim`."
        )
        raise typer.Exit(code=2) from exc

    try:
        from creature_lab.viewers.video_exporter import write_animation
    except ImportError as exc:
        console.print(
            "[red]error:[/red] imageio is not installed. Install it with `uv sync --extra export`."
        )
        raise typer.Exit(code=2) from exc

    frames = render_trace(creature, trace, task=task_spec, width=width, height=height)
    saved_path = write_animation(frames, out_path, fps=fps)
    console.print(f"[green]exported[/green] {len(frames)} frame(s) -> {saved_path}")


@app.command("export-pack", rich_help_panel="Replay And Debug")
def export_pack_cmd(
    path: Annotated[Path, typer.Argument(help="Run directory, 'latest', or a bare run id.")],
    out: Annotated[
        Path | None,
        typer.Option("--out", "-o", help="Output directory (default: outputs/<run_id>_pack)."),
    ] = None,
    runs_dir: Annotated[
        Path, typer.Option(help="Directory used when resolving the `latest` alias.")
    ] = DEFAULT_RUNS_DIR,
    json_output: Annotated[
        bool, typer.Option("--json", help="Print machine-readable pack metadata.")
    ] = False,
    overwrite: Annotated[
        bool, typer.Option(help="Replace an existing output pack directory.")
    ] = False,
) -> None:
    """Bundle a run's creature, task, controller, and trace into a shareable directory.

    The result is self-contained: `creature.json`, `task.json` (if the run has one),
    `controller.json`, `trace.json`, and a `manifest.json` with reproducibility hashes.
    Hand the directory to someone else, or replay it later, without depending on
    `runs/` or anything else on this machine.
    """
    run_dir = _run_dir_for(path, runs_dir=runs_dir)
    if not (run_dir / "trace.json").exists():
        console.print(f"[red]error:[/red] no trace.json found under {run_dir}")
        raise typer.Exit(code=2)
    trace = _load_spec(run_dir / "trace.json", EpisodeTrace)
    creature = _load_creature_for_trace(path, None, runs_dir)
    task_spec = _load_task_for_trace(path, None, runs_dir)

    out_dir = out if out is not None else Path("outputs") / f"{trace.run_id}_pack"
    try:
        manifest = export_design_pack(
            creature,
            task_spec,
            trace,
            out_dir=out_dir,
            source_dir=run_dir,
            overwrite=overwrite,
        )
    except (FileExistsError, OSError, ValueError) as exc:
        console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=2) from exc

    if json_output:
        _print_json({"out_dir": str(out_dir), **manifest.to_json_dict()})
        return

    console.print(f"[green]exported[/green] design pack -> {out_dir}")
    console.print(f"  controller.json: {manifest.controller_note}")
    for warning in manifest.warnings:
        console.print(f"  [yellow]warning:[/yellow] {warning}")


@app.command("verify-pack", rich_help_panel="Replay And Debug")
def verify_pack_cmd(
    path: Annotated[Path, typer.Argument(help="Directory containing a design pack.")],
    json_output: Annotated[
        bool, typer.Option("--json", help="Print machine-readable verification results.")
    ] = False,
) -> None:
    """Verify every artifact hash and schema in a design pack before using it."""
    result = verify_design_pack(path)
    if json_output:
        _print_json(
            {
                "path": str(path),
                "valid": result.valid,
                "checks": result.checks,
                "errors": result.errors,
            }
        )
    else:
        for check in result.checks:
            console.print(f"[green]ok[/green] {check}")
        for error in result.errors:
            console.print(f"[red]error:[/red] {error}")
        console.print(
            "[green]valid design pack[/green]" if result.valid else "[red]invalid design pack[/red]"
        )
    if not result.valid:
        raise typer.Exit(code=1)


def _write_creature(creature: CreatureSpec, out: Path) -> None:
    """Serialize a creature to JSON and report part/joint/motor counts."""
    out.write_text(creature.model_dump_json(indent=2, exclude_none=True))
    console.print(
        f"[green]wrote[/green] {creature.name!r} -> {out} "
        f"({len(creature.parts)} part(s), {len(creature.joints)} joint(s), "
        f"{len(creature.motors)} motor(s))"
    )


schema_app = typer.Typer(help="Export Creature Lab JSON Schemas.")
app.add_typer(schema_app, name="schema", rich_help_panel="Advanced")


def _write_schema(model: type[BaseModel], out: Path | None) -> None:
    rendered = json.dumps(model.model_json_schema(), indent=2, sort_keys=True)
    if out is None:
        _write_stdout(rendered)
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(rendered)
    console.print(f"[green]wrote[/green] {model.__name__} schema -> {out}")


@schema_app.command("creature")
def schema_creature(
    out: Annotated[Path | None, typer.Option("--out", "-o", help="Write schema JSON here.")] = None,
) -> None:
    """Export the CreatureSpec JSON Schema."""
    _write_schema(CreatureSpec, out)


@schema_app.command("task")
def schema_task(
    out: Annotated[Path | None, typer.Option("--out", "-o", help="Write schema JSON here.")] = None,
) -> None:
    """Export the TaskSpec JSON Schema."""
    _write_schema(TaskSpec, out)


@schema_app.command("trace")
def schema_trace(
    out: Annotated[Path | None, typer.Option("--out", "-o", help="Write schema JSON here.")] = None,
) -> None:
    """Export the EpisodeTrace JSON Schema."""
    _write_schema(EpisodeTrace, out)


@schema_app.command("controller")
def schema_controller(
    out: Annotated[Path | None, typer.Option("--out", "-o", help="Write schema JSON here.")] = None,
) -> None:
    """Export the ControllerSpec JSON Schema."""
    _write_schema(ControllerSpec, out)


controller_app = typer.Typer(help="Author and validate portable controller.json files.")
app.add_typer(controller_app, name="controller", rich_help_panel="Run And Improve")

#: Default field values for a scaffolded controller.json, matching CPGController's,
#: TargetSeekController's, and PostureController's own constructor defaults - so a
#: scaffolded file behaves identically to the bare `--controller cpg`/`target_seek`/
#: `posture` name until edited.
_CONTROLLER_DEFAULTS: dict[str, dict[str, float]] = {
    "cpg": {"amplitude": 0.8, "frequency": 1.5, "phase_lag": 2.0, "coupling": 6.0},
    "target_seek": {"turn_gain": 1.2, "max_turn_scale": 0.8, "slow_radius": 1.0},
    "posture": {"kp": 40.0, "kd": 0.0},
}


@controller_app.command("scaffold")
def controller_scaffold(
    controller_type: Annotated[
        str,
        typer.Argument(
            help="Controller type: 'cpg', 'target_seek', or 'posture' "
            "(see 'controller extract' for sinusoid)."
        ),
    ],
    out: Annotated[
        Path | None,
        typer.Option("--out", "-o", help="Write the controller.json here (else stdout)."),
    ] = None,
    name: Annotated[str, typer.Option(help="Name recorded in the controller.json.")] = "controller",
) -> None:
    """Write a starter controller.json with the type's built-in default values.

    A scaffolded file behaves identically to the bare `--controller cpg`/
    `target_seek` name until you edit its fields - it exists to give you something
    concrete to tune instead of guessing field names from documentation.
    """
    from creature_lab.schema import ControllerSpec

    if controller_type not in _CONTROLLER_DEFAULTS:
        console.print(
            f"[red]error:[/red] unknown controller type {controller_type!r}; choose one of: "
            f"{', '.join(_CONTROLLER_DEFAULTS)} (sinusoid has no fixed defaults - "
            "see `controller extract`)"
        )
        raise typer.Exit(code=2)
    spec = ControllerSpec.model_validate(
        {"name": name, "type": controller_type, **_CONTROLLER_DEFAULTS[controller_type]}
    )
    rendered = spec.model_dump_json(indent=2, exclude_none=True)
    if out is None:
        _write_stdout(rendered)
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(rendered)
    console.print(f"[green]wrote[/green] {controller_type} controller -> {out}")


@controller_app.command("extract")
def controller_extract(
    creature_path: Annotated[Path, typer.Argument(help="Path to a CreatureSpec JSON file.")],
    out: Annotated[
        Path | None,
        typer.Option("--out", "-o", help="Write the controller.json here (else stdout)."),
    ] = None,
    name: Annotated[str, typer.Option(help="Name recorded in the controller.json.")] = "controller",
) -> None:
    """Migrate a creature's own MotorSpec gait into an explicit sinusoid controller.json.

    The result reproduces exactly what `--controller sinusoid` already does for this
    creature - now as a standalone, shareable artifact instead of implicit behavior.
    """
    from creature_lab.controllers.factory import extract_sinusoid_spec

    creature = _load_spec(creature_path, CreatureSpec)
    try:
        spec = extract_sinusoid_spec(creature, name=name)
    except ValueError as exc:
        console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    rendered = spec.model_dump_json(indent=2, exclude_none=True)
    if out is None:
        _write_stdout(rendered)
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(rendered)
    console.print(
        f"[green]wrote[/green] sinusoid controller extracted from {creature.name!r} -> {out}"
    )


@controller_app.command("validate")
def controller_validate(
    controller_path: Annotated[Path, typer.Argument(help="Path to a controller.json.")],
    creature_path: Annotated[
        Path, typer.Option("--creature", help="CreatureSpec JSON to check compatibility against.")
    ],
    task_path: Annotated[
        Path | None,
        typer.Option(
            "--task", help="TaskSpec JSON (required to validate a target_seek controller)."
        ),
    ] = None,
) -> None:
    """Validate a controller.json's schema, and that it can actually drive this creature/task."""
    from creature_lab.controllers.factory import build_controller
    from creature_lab.schema import ControllerSpec, ControllerType

    spec = _load_spec(controller_path, ControllerSpec)
    creature = _load_spec(creature_path, CreatureSpec)
    task_spec = _load_spec(task_path, TaskSpec) if task_path is not None else None

    if spec.type == ControllerType.SINUSOID:
        if spec.motors is None:
            console.print("[red]error:[/red] sinusoid controller has no motor gait")
            raise typer.Exit(code=1)
        hinge_joints = {joint.id for joint in creature.joints if joint.type.value == "hinge"}
        spec_joints = {motor.joint for motor in spec.motors}
        missing = spec_joints - hinge_joints
        if missing:
            console.print(
                f"[red]error:[/red] controller joints are not hinges on {creature.name!r}: "
                f"{', '.join(sorted(missing))}"
            )
            raise typer.Exit(code=1)

    try:
        build_controller(spec, creature, task_spec, base_dir=controller_path.resolve().parent)
    except ValueError as exc:
        console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    if spec.type == ControllerType.POLICY:
        console.print(
            "[yellow]security:[/yellow] policy payloads may deserialize Python objects; "
            "load only files you trust"
        )
        if spec.observation is None or spec.action is None:
            console.print(
                "[yellow]warning:[/yellow] legacy policy has no explicit observation/action ABI"
            )

    console.print(
        f"[green]valid[/green] controller {spec.name!r} ({spec.type.value}) "
        f"for creature {creature.name!r}"
    )


gallery_app = typer.Typer(help="Build static zoo gallery files.")
app.add_typer(gallery_app, name="gallery", rich_help_panel="Start Here")


def _gallery_failure_note(name: str, task_name: str) -> str:
    if "humanoid" in name:
        return "Balance and early falls are the first things to inspect."
    if "damaged" in name or "recover" in task_name:
        return "Compare pre-damage and post-damage movement in the report."
    if task_name == "reach_target":
        return "Check target progress and wasted joint motion."
    return "Check forward displacement, contact balance, and motor limits."


def _gallery_card(
    name: str, task_name: str, baseline: dict[str, Any] | None, gif: str | None
) -> str:
    expected = baseline.get("best_score") if baseline else None
    lines = [
        f"# {name}",
        "",
        f"- Default task: `{task_name}`",
        f"- Expected score: {'-' if expected is None else f'{expected:.4f}'}",
        f"- Common failure mode: {_gallery_failure_note(name, task_name)}",
        f"- Run: `uv run creature-lab zoo run {name}`",
    ]
    if gif is not None:
        lines.append(f"- GIF: `{gif}`")
    lines.append("")
    return "\n".join(lines)


@gallery_app.command("build")
def gallery_build(
    zoo: Annotated[
        bool, typer.Option("--zoo", help="Build cards for packaged zoo creatures.")
    ] = False,
    out: Annotated[
        Path, typer.Option("--out", "-o", help="Output directory for gallery files.")
    ] = Path("docs/assets/zoo"),
    media: Annotated[
        bool, typer.Option("--media/--no-media", help="Also render one GIF per zoo creature.")
    ] = True,
    runs_dir: Annotated[
        Path, typer.Option(help="Directory to save gallery render runs under.")
    ] = DEFAULT_RUNS_DIR,
    width: Annotated[int, typer.Option(help="GIF render width in pixels.")] = 320,
    height: Annotated[int, typer.Option(help="GIF render height in pixels.")] = 240,
) -> None:
    """Build local static cards, and optionally GIFs, for the Creature Zoo."""
    if not zoo:
        console.print("[red]error:[/red] use --zoo to build the packaged zoo gallery")
        raise typer.Exit(code=2)

    from creature_lab.reports_html import gallery_card_html, gallery_index_html
    from creature_lab.zoo import default_task_name, list_zoo_creatures, zoo_baseline, zoo_creature

    out.mkdir(parents=True, exist_ok=True)
    cards: list[str] = []
    html_cards: list[str] = []
    for name in list_zoo_creatures():
        task_name = default_task_name(name)
        creature, task_spec = zoo_creature(name, task_name)
        baseline = zoo_baseline(name, task_name)
        gif_name: str | None = None
        current_score: float | None = None
        if media:
            try:
                from creature_lab.backends.pybullet_backend import render_trace
                from creature_lab.viewers.video_exporter import write_animation
            except ImportError as exc:
                console.print(
                    "[red]error:[/red] gallery media needs `uv sync --extra sim --extra export`."
                )
                raise typer.Exit(code=2) from exc
            trace = _simulate(creature, task_spec)
            save_run(creature, trace, runs_dir=runs_dir, task=task_spec)
            current_score = trace.score
            gif_path = out / f"{name}.gif"
            frames = render_trace(creature, trace, task=task_spec, width=width, height=height)
            write_animation(frames, gif_path)
            gif_name = gif_path.name
        card = _gallery_card(name, task_name, baseline, gif_name)
        card_path = out / f"{name}.md"
        card_path.write_text(card)
        cards.append(f"- [{name}]({card_path.name})")
        html_cards.append(
            gallery_card_html(
                name,
                task_name,
                baseline,
                current_score,
                gif_name,
                _gallery_failure_note(name, task_name),
            )
        )

    (out / "index.md").write_text("# Creature Zoo Gallery\n\n" + "\n".join(cards) + "\n")
    (out / "index.html").write_text(gallery_index_html(html_cards))
    console.print(f"[green]built[/green] {len(cards)} zoo gallery card(s) -> {out}")


scaffold_app = typer.Typer(help="Generate creatures procedurally (no URDF/MJCF by hand).")
app.add_typer(scaffold_app, name="scaffold", rich_help_panel="Advanced")


@scaffold_app.command("worm")
def scaffold_worm(
    out: Annotated[Path, typer.Option("--out", "-o", help="Output CreatureSpec path.")],
    segments: Annotated[int, typer.Option(help="Number of body segments.")] = 5,
) -> None:
    """Scaffold a multi-segment worm that crawls forward."""
    from creature_lab.scaffold import generate_worm

    _write_creature(generate_worm(segments), out)


@scaffold_app.command("quadruped")
def scaffold_quadruped(
    out: Annotated[Path, typer.Option("--out", "-o", help="Output CreatureSpec path.")],
    leg_length: Annotated[float, typer.Option(help="Leg capsule length (m).")] = 0.22,
) -> None:
    """Scaffold a four-legged walker."""
    from creature_lab.scaffold import generate_quadruped

    _write_creature(generate_quadruped(leg_length=leg_length), out)


@scaffold_app.command("hexapod")
def scaffold_hexapod(
    out: Annotated[Path, typer.Option("--out", "-o", help="Output CreatureSpec path.")],
) -> None:
    """Scaffold a six-legged walker."""
    from creature_lab.scaffold import generate_hexapod

    _write_creature(generate_hexapod(), out)


@scaffold_app.command("humanoid")
def scaffold_humanoid(
    out: Annotated[Path, typer.Option("--out", "-o", help="Output CreatureSpec path.")],
    dof: Annotated[int, typer.Option(help="Actuated hinges: 8 or 12.")] = 12,
    height: Annotated[float, typer.Option(help="Approximate standing height (m).")] = 1.6,
) -> None:
    """Scaffold a bipedal humanoid skeleton."""
    from creature_lab.scaffold import generate_humanoid

    if dof not in (8, 12):
        console.print("[red]error:[/red] --dof must be 8 or 12")
        raise typer.Exit(code=2)
    _write_creature(generate_humanoid(height=height, dof=dof), out)  # type: ignore[arg-type]


@app.command("mirror-limb", rich_help_panel="Advanced")
def mirror_limb_cmd(
    creature_path: Annotated[Path, typer.Argument(help="Path to a CreatureSpec JSON file.")],
    out: Annotated[Path, typer.Option("--out", "-o", help="Output CreatureSpec path.")],
    side: Annotated[
        str, typer.Option(help="Side to mirror from: 'left' (Y>0) or 'right' (Y<0).")
    ] = "left",
) -> None:
    """Mirror a creature's limbs from one side to the other for symmetry."""
    from creature_lab.scaffold import mirror_limb

    creature = _load_spec(creature_path, CreatureSpec)
    try:
        mirrored = mirror_limb(creature, side=side)
    except ValueError as exc:
        console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    _write_creature(mirrored, out)


zoo_app = typer.Typer(help="Browse and run the curated Creature Zoo.")
app.add_typer(zoo_app, name="zoo", rich_help_panel="Start Here")

failure_app = typer.Typer(
    help="Explore intentionally broken experiments and their expected causes."
)
app.add_typer(failure_app, name="failure", rich_help_panel="Start Here")


@failure_app.command("list")
def failure_list(
    json_output: Annotated[
        bool, typer.Option("--json", help="Print machine-readable Failure Zoo metadata.")
    ] = False,
) -> None:
    """List curated failures used for learning and diagnostic regression."""
    from creature_lab.failure_zoo import list_failure_cases

    cases = list_failure_cases()
    if json_output:
        _print_json([case.__dict__ for case in cases])
        return
    table = Table(title="Creature Lab Failure Zoo")
    table.add_column("id")
    table.add_column("expected cause")
    table.add_column("lesson")
    for case in cases:
        table.add_row(case.id, case.expected_cause, case.description)
    console.print(table)


@failure_app.command("export")
def failure_export(
    case_id: Annotated[str, typer.Argument(help="Failure case id (see `failure list`).")],
    out: Annotated[Path, typer.Option("--out", "-o", help="Output experiment directory.")],
    overwrite: Annotated[
        bool, typer.Option(help="Replace known files in the output directory.")
    ] = (False),
) -> None:
    """Export an intentionally broken creature/task/controller experiment."""
    from creature_lab.failure_zoo import build_failure_case
    from creature_lab.io_utils import atomic_write_text

    try:
        creature, task_spec, controller_spec, case = build_failure_case(case_id)
    except KeyError as exc:
        console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=2) from exc
    if out.exists() and any(out.iterdir()) and not overwrite:
        console.print(f"[red]error:[/red] output directory already exists: {out}")
        raise typer.Exit(code=2)
    out.mkdir(parents=True, exist_ok=True)
    atomic_write_text(out / "creature.json", creature.model_dump_json(indent=2))
    atomic_write_text(out / "task.json", task_spec.model_dump_json(indent=2))
    atomic_write_text(
        out / "controller.json", controller_spec.model_dump_json(indent=2, exclude_none=True)
    )
    expected = {
        "id": case.id,
        "title": case.title,
        "expected_cause": case.expected_cause,
        "description": case.description,
        "next_command": (
            "creature-lab autopsy creature.json --task task.json --controller controller.json"
        ),
    }
    atomic_write_text(out / "expected.json", json.dumps(expected, indent=2, sort_keys=True))
    atomic_write_text(
        out / "README.md",
        f"# {case.title}\n\n{case.description}\n\nExpected autopsy cause: "
        f"`{case.expected_cause}`.\n\n```bash\n{expected['next_command']}\n```\n",
    )
    console.print(f"[green]exported[/green] failure case {case.id!r} -> {out}")


@zoo_app.command("list")
def zoo_list(
    json_output: Annotated[
        bool, typer.Option("--json", help="Print machine-readable zoo metadata.")
    ] = False,
) -> None:
    """List the built-in zoo creatures and their tasks."""
    from creature_lab.zoo import (
        default_task_name,
        list_zoo_creatures,
        zoo_optimized_controller,
        zoo_showcase,
        zoo_tasks,
    )

    if json_output:
        _print_json(
            [
                {
                    "creature": name,
                    "tasks": zoo_tasks(name),
                    "default_task": default_task_name(name),
                    "has_optimized_controller": zoo_optimized_controller(name) is not None,
                    "status": (
                        zoo_showcase(name).status if zoo_showcase(name) is not None else "unrated"
                    ),
                }
                for name in list_zoo_creatures()
            ]
        )
        return

    table = Table(title="Creature Zoo")
    table.add_column("creature")
    table.add_column("tasks")
    table.add_column("default task")
    table.add_column("optimized gait")
    table.add_column("status")
    for name in list_zoo_creatures():
        tasks = zoo_tasks(name)
        optimized = "[green]yes[/green]" if zoo_optimized_controller(name) else "-"
        showcase = zoo_showcase(name)
        status = showcase.status if showcase is not None else "unrated"
        table.add_row(name, ", ".join(tasks), default_task_name(name), optimized, status)
    console.print(table)
    console.print(
        "[dim]'optimized gait' creatures also ship a CMA-ES-tuned controller.json - "
        "the curated default automatically uses them; `sinusoid` remains the raw baseline.[/dim]"
    )


@zoo_app.command("run")
def zoo_run(
    name: Annotated[str, typer.Argument(help="Zoo creature name (see `zoo list`).")],
    task: Annotated[
        str | None, typer.Option(help="Task name for this creature (default: its crawl task).")
    ] = None,
    controller: Annotated[
        str,
        typer.Option(
            help="Controller: 'curated' (default), 'sinusoid', 'cpg', 'target_seek', a path to a "
            "controller.json, or 'optimized' for this creature's packaged CMA-ES-tuned "
            "gait if one is shipped (see `zoo list`)."
        ),
    ] = "curated",
    gui: Annotated[bool, typer.Option(help="Open a PyBullet GUI window.")] = False,
    seed: Annotated[int | None, typer.Option(help="Seed recorded in the trace metadata.")] = None,
    runs_dir: Annotated[
        Path, typer.Option(help="Directory to save the episode trace under.")
    ] = DEFAULT_RUNS_DIR,
    json_output: Annotated[
        bool, typer.Option("--json", help="Print machine-readable run metadata.")
    ] = False,
) -> None:
    """Run a zoo creature on one of its tasks and save the trace."""
    from creature_lab.zoo import zoo_creature, zoo_optimized_controller

    try:
        creature, task_spec = zoo_creature(name, task)
    except KeyError as exc:
        console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=2) from exc

    if controller == "optimized":
        optimized_path = zoo_optimized_controller(name)
        if optimized_path is None:
            console.print(
                f"[red]error:[/red] no optimized controller packaged for {name!r} "
                "(see `zoo list` for which creatures have one)"
            )
            raise typer.Exit(code=2)
        controller = str(optimized_path)

    _check_inputs(creature, task_spec)
    trace = _simulate(creature, task_spec, gui=gui, seed=seed, controller=controller)
    run_dir = save_run(creature, trace, runs_dir=runs_dir, task=task_spec)
    if json_output:
        _print_json(_saved_run_payload(creature, task_spec, trace, run_dir))
        return
    console.print(
        f"[green]done[/green] {creature.name!r} on {task_spec.name!r}: "
        f"score={trace.score:.4f} ({len(trace.frames)} step(s)) -> {run_dir}"
    )


@zoo_app.command("validate-all")
def zoo_validate_all() -> None:
    """Cross-validate every creature/task pair in the zoo."""
    from creature_lab.validation import EpisodeInputError
    from creature_lab.zoo import validate_all

    try:
        pairs = validate_all()
    except EpisodeInputError as exc:
        console.print(f"[red]error:[/red] zoo has an invalid creature/task: {exc}")
        raise typer.Exit(code=1) from exc
    for creature_name, task_name in pairs:
        console.print(f"[green]ok[/green] {creature_name} / {task_name}")
    console.print(f"[green]valid[/green] all {len(pairs)} zoo creature/task pair(s)")


@zoo_app.command("check-showcases")
def zoo_check_showcases(
    backend: Annotated[str, typer.Option(help="Physics backend to verify.")] = "pybullet",
    json_output: Annotated[
        bool, typer.Option("--json", help="Print machine-readable acceptance results.")
    ] = False,
) -> None:
    """Run every promoted Zoo example against its measured behavioral contract."""
    from creature_lab.diagnostics import summarize_episode
    from creature_lab.zoo import ZOO_SHOWCASES, zoo_creature

    rows: list[dict[str, object]] = []
    for name, expectation in ZOO_SHOWCASES.items():
        if expectation.status != "showcase":
            continue
        creature, task_spec = zoo_creature(name, expectation.task)
        trace = _simulate(creature, task_spec, controller="curated", backend=backend)
        summary = summarize_episode(trace, task_spec, creature)
        score_ok = expectation.min_score is None or trace.score >= expectation.min_score
        fall_ok = not expectation.require_no_fall or not bool(summary.fell)
        rows.append(
            {
                "creature": name,
                "task": expectation.task,
                "passed": score_ok and fall_ok,
                "score": trace.score,
                "min_score": expectation.min_score,
                "fell": bool(summary.fell),
            }
        )
    passed = all(bool(row["passed"]) for row in rows)
    if json_output:
        _print_json({"backend": backend, "passed": passed, "showcases": rows})
    else:
        table = Table(title=f"Zoo showcase acceptance ({backend})")
        for heading in ("creature", "task", "score", "threshold", "fell", "result"):
            table.add_column(heading)
        for row in rows:
            table.add_row(
                str(row["creature"]),
                str(row["task"]),
                f"{float(row['score']):.4f}",
                str(row["min_score"]),
                str(row["fell"]),
                "PASS" if row["passed"] else "FAIL",
            )
        console.print(table)
    if not passed:
        raise typer.Exit(code=1)


@app.command("export-urdf", rich_help_panel="Advanced")
def export_urdf_cmd(
    creature_path: Annotated[Path, typer.Argument(help="Path to a CreatureSpec JSON file.")],
    out: Annotated[Path, typer.Option("--out", "-o", help="Output .urdf path.")],
) -> None:
    """Export a creature to a URDF robot description (capsules become cylinders)."""
    from creature_lab.export import export_urdf

    creature = _load_spec(creature_path, CreatureSpec)
    out.write_text(export_urdf(creature))
    console.print(f"[green]exported[/green] {creature.name!r} URDF -> {out}")


@app.command("export-mjcf", rich_help_panel="Advanced")
def export_mjcf_cmd(
    creature_path: Annotated[Path, typer.Argument(help="Path to a CreatureSpec JSON file.")],
    out: Annotated[Path, typer.Option("--out", "-o", help="Output .xml path.")],
) -> None:
    """Export a creature to a MuJoCo MJCF model."""
    from creature_lab.export import export_mjcf

    creature = _load_spec(creature_path, CreatureSpec)
    out.write_text(export_mjcf(creature))
    console.print(f"[green]exported[/green] {creature.name!r} MJCF -> {out}")


@app.command("import-urdf", rich_help_panel="Advanced")
def import_urdf_cmd(
    urdf_path: Annotated[Path, typer.Argument(help="Path to a .urdf file.")],
    out: Annotated[Path, typer.Option("--out", "-o", help="Output CreatureSpec path.")],
) -> None:
    """Best-effort import of a simple URDF into a CreatureSpec (skips meshes/sensors)."""
    from creature_lab.export import import_urdf

    if not urdf_path.exists():
        console.print(f"[red]error:[/red] file not found: {urdf_path}")
        raise typer.Exit(code=2)
    try:
        result = import_urdf(urdf_path.read_text())
    except (ValueError, ET_PARSE_ERROR) as exc:
        console.print(f"[red]error:[/red] could not import URDF: {exc}")
        raise typer.Exit(code=1) from exc

    out.write_text(result.creature.model_dump_json(indent=2, exclude_none=True))
    console.print(
        f"[green]imported[/green] {result.creature.name!r} -> {out} "
        f"({len(result.creature.parts)} part(s), {len(result.creature.joints)} joint(s))"
    )
    for warning in result.warnings:
        console.print(f"[yellow]warning:[/yellow] {warning}")


if __name__ == "__main__":
    app()
