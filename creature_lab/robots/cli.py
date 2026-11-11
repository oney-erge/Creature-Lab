"""``creature-lab robots``: fetch published robots and check them up."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from creature_lab.robots.catalog import all_robots, robot_info
from creature_lab.robots.fetch import (
    FetchError,
    cache_root,
    ensure_robot,
    is_installed,
    missing_extra,
    robot_dir,
)
from creature_lab.robots.pack import (
    PackError,
    register_pack,
    registry_status,
    unregister_pack,
)

robots_app = typer.Typer(
    help="Check up real published robots: shoves, slippery floors and weak batteries, "
    "with an explanation of every fall."
)
console = Console()


def _require_extra() -> None:
    missing = missing_extra()
    if missing:
        console.print(
            f"[red]Missing {', '.join(missing)}.[/red] Install the robots extra: "
            "[bold]uv sync --inexact --extra robots[/bold]"
        )
        raise typer.Exit(code=2)


def _ensure_downloaded(robot: str, accept: bool) -> None:
    if is_installed(robot):
        return
    info = robot_info(robot)
    if info.folder is not None:
        console.print(
            f"[red]{info.title}'s files are missing from {info.folder}.[/red] Put the folder "
            f"back, or run: creature-lab robots remove {robot}"
        )
        raise typer.Exit(code=1)
    console.print(Panel(info.license_notice, title=f"{info.title}: before you download"))
    if not accept and not (sys.stdin.isatty() and typer.confirm("Download it now?", default=True)):
        console.print(
            "Not downloaded. Re-run with [bold]--yes[/bold] to accept, or: "
            f"creature-lab robots fetch {robot}"
        )
        raise typer.Exit(code=1)
    try:
        folder = ensure_robot(robot, progress=lambda message: console.print(f"  {message}"))
    except FetchError as error:
        console.print(f"[red]{error}[/red]")
        raise typer.Exit(code=1) from error
    console.print(f"Saved to {folder}")


def _robot_arg(robot: str) -> str:
    key = robot.replace("-", "_")
    known = all_robots()
    if key not in known:
        raise typer.BadParameter(f"choose one of: {', '.join(known)}")
    return key


@robots_app.command("list")
def list_robots() -> None:
    """Show the robots Creature Lab can check up and whether they are downloaded."""
    table = Table(title=f"Robots (downloads go to {cache_root()})")
    for column in ("Robot", "Maker", "Height", "Policies", "Downloaded"):
        table.add_column(column)
    for info in all_robots().values():
        if info.folder is not None:
            ready = "yours" if is_installed(info.key) else "[red]files missing[/red]"
        else:
            ready = "yes" if is_installed(info.key) else "no"
        table.add_row(
            info.key.replace("_", "-"),
            info.maker,
            f"{info.height_cm} cm",
            ", ".join(p.key for p in info.policies),
            ready,
        )
    console.print(table)
    for key, (folder, info, problem) in registry_status().items():
        if info is None:
            console.print(f"[red]{key}[/red] ({folder}) cannot be read: {problem}")


@robots_app.command("fetch")
def fetch(
    robot: Annotated[str, typer.Argument(help="microduck or unitree-g1")],
    yes: Annotated[bool, typer.Option("--yes", help="Accept the license notice.")] = False,
) -> None:
    """Download a robot's model files, verified against pinned hashes."""
    key = _robot_arg(robot)
    if robot_info(key).folder is not None:
        console.print(f"{robot_info(key).title} is your own robot; nothing to download.")
        return
    _ensure_downloaded(key, yes)
    console.print(f"{robot_info(key).title} is ready in {robot_dir(key)}")


def _show_report(report) -> None:
    for problem in report.errors:
        console.print(f"[red]error[/red]   {problem}", highlight=False)
    for warning in report.warnings:
        console.print(f"[yellow]warning[/yellow] {warning}", highlight=False)
    for name, value in report.facts.items():
        console.print(f"[dim]{name}[/dim]  {value}", highlight=False)


@robots_app.command("init")
def init(
    folder: Annotated[Path, typer.Argument(help="A folder holding your model and policies.")],
    model: Annotated[
        Path | None, typer.Option("--model", help="The MuJoCo file (default: the only .xml).")
    ] = None,
    policy: Annotated[
        list[Path] | None,
        typer.Option("--policy", help="A policy file (repeatable; default: every .onnx/.npz)."),
    ] = None,
    key: Annotated[
        str | None, typer.Option(help="The robot's key (default: the folder name).")
    ] = None,
    title: Annotated[
        str | None, typer.Option(help="The robot's name (default: the folder name).")
    ] = None,
    force: Annotated[bool, typer.Option("--force", help="Replace an existing robot.toml.")] = False,
) -> None:
    """Draft robot.toml from your model and policies, reading what they already say.

    Joint order, gains, default pose, action scales and the observation layout come from an ONNX
    policy's metadata (mjlab writes it) and from the model; what only you know is left as TODO.
    """
    from creature_lab.robots.packinit import draft_pack, write_draft

    folder = folder.expanduser().resolve()
    if not folder.is_dir():
        console.print(f"[red]{folder} is not a folder.[/red]")
        raise typer.Exit(code=1)
    models = (
        [model.expanduser()]
        if model
        else [p for p in sorted(folder.glob("*.xml")) if p.name != "checkup_scene.xml"]
    )
    if len(models) != 1:
        console.print(
            "[red]Say which MuJoCo file to use with --model[/red] "
            f"({len(models)} .xml files in {folder})."
        )
        raise typer.Exit(code=1)
    policies = (
        [p.expanduser() for p in policy]
        if policy
        else sorted([*folder.glob("*.onnx"), *folder.glob("*.npz")])
    )
    if not policies:
        console.print(
            "[red]No policy found.[/red] Put an .onnx or .npz file in the folder, or use --policy."
        )
        raise typer.Exit(code=1)
    try:
        model_path = models[0] if models[0].is_absolute() else folder / models[0]
        policy_paths = [p if p.is_absolute() else folder / p for p in policies]
        for path in (model_path, *policy_paths):
            path.resolve().relative_to(folder)
        text = draft_pack(
            model_path.resolve(), [p.resolve() for p in policy_paths], key=key, title=title
        )
        target = write_draft(folder, text, force=force)
    except ValueError as error:  # a path outside the folder, or a PackError
        console.print(f"[red]{error}[/red]", highlight=False)
        raise typer.Exit(code=1) from error
    console.print(f"Wrote [bold]{target}[/bold]. Fix the lines that say TODO, then run:")
    console.print(f"  creature-lab robots validate {folder}")


@robots_app.command("validate")
def validate(
    folder: Annotated[Path, typer.Argument(help="A folder holding robot.toml (or the file).")],
    trial: Annotated[
        bool, typer.Option("--trial/--no-trial", help="Also walk the robot for two seconds.")
    ] = True,
) -> None:
    """Check your own robot pack: every likely mistake in plain words, then a short trial walk."""
    from creature_lab.robots.packcheck import validate_pack

    report = validate_pack(folder, simulate=trial)
    _show_report(report)
    if not report.ok:
        console.print("[red]Not usable yet.[/red] Fix the errors above and run this again.")
        raise typer.Exit(code=1)
    console.print("[green]Ready to add:[/green] creature-lab robots add " + str(folder))


@robots_app.command("add")
def add(
    folder: Annotated[Path, typer.Argument(help="A folder holding robot.toml.")],
) -> None:
    """Add your own robot and policy, so check-ups, the report and the app can use them.

    The folder stays where it is (nothing is copied), so edits to robot.toml or the policy are
    picked up. Only add folders you trust: Creature Lab opens the model and policy files in it.
    """
    from creature_lab.robots.packcheck import validate_pack

    report = validate_pack(folder)
    _show_report(report)
    if not report.ok:
        console.print("[red]Not added.[/red] Fix the errors above and run this again.")
        raise typer.Exit(code=1)
    try:
        info = register_pack(folder)
    except PackError as error:
        console.print(f"[red]Not added.[/red] {error}")
        raise typer.Exit(code=1) from error
    key = info.key.replace("_", "-")
    console.print(
        f"[green]Added {info.title}.[/green] Check it up with: creature-lab robots checkup {key}"
    )


@robots_app.command("remove")
def remove(
    robot: Annotated[str, typer.Argument(help="The key of a robot you added.")],
) -> None:
    """Forget a robot you added. Its folder and files are left exactly as they are."""
    key = robot.replace("-", "_")
    try:
        folder = unregister_pack(key)
    except KeyError:
        console.print(f"[red]{robot} is not one of your added robots.[/red]")
        raise typer.Exit(code=1) from None
    console.print(f"Removed {robot}. Its files are still in {folder}.")


@robots_app.command("checkup")
def checkup(
    robot: Annotated[str, typer.Argument(help="microduck, unitree-g1 or a robot you added")],
    policy: Annotated[
        list[str] | None, typer.Option("--policy", help="Policy to test (repeatable).")
    ] = None,
    out: Annotated[Path | None, typer.Option("--out", help="Output folder.")] = None,
    film: Annotated[bool, typer.Option("--film", help="Also encode the 1080p film.")] = False,
    yes: Annotated[bool, typer.Option("--yes", help="Accept the license notice.")] = False,
) -> None:
    """Run the full check-up and write an HTML report (and optionally a film)."""
    key = _robot_arg(robot)
    info = robot_info(key)
    _require_extra()
    from creature_lab.robots.checkup import run_checkup
    from creature_lab.robots.film import film_name, make_film
    from creature_lab.robots.report import PolicyResult, limit_text, write_report

    _ensure_downloaded(key, yes)
    keys = policy or [p.key for p in info.policies]
    for name in keys:
        info.policy(name)
    keys = sorted(keys, key=lambda name: info.policy(name).gets_up)  # "before" first
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = out or Path("outputs") / "checkup" / f"{robot}-{stamp}"
    results = []
    for name in keys:
        console.print(f"[bold]{info.title} · {info.policy(name).title}[/bold]")
        folder = out_dir / name
        result = run_checkup(key, name, folder, progress=lambda m: console.print(f"  {m}"))
        results.append(PolicyResult(result, folder))
    table = Table(title=f"{info.title} check-up")
    for column in ("Policy", "Baseline", "Never falls up to", "Never stays down up to"):
        table.add_column(column)
    for item in results:
        c = item.checkup
        table.add_row(
            info.policy(c.policy).title,
            c.baseline.verdict,
            limit_text(c.never_falls_up_to_n, c),
            limit_text(c.never_stays_down_up_to_n, c),
        )
    console.print(table)
    film_file = None
    if film:
        console.print("Encoding the film (about 5 minutes)...")
        film_file = make_film(out_dir, progress=lambda m: console.print(f"  {m}")).name
    elif (out_dir / film_name(key)).exists():
        film_file = film_name(key)
    report = write_report(out_dir, results, film=film_file)
    console.print(f"Report: [bold]{report}[/bold]")


@robots_app.command("film")
def film_command(
    results: Annotated[Path, typer.Argument(help="A folder written by `robots checkup`.")],
) -> None:
    """Encode the 1080p film for existing check-up results."""
    _require_extra()
    from creature_lab.robots.checkup import read_checkup
    from creature_lab.robots.film import make_film, output_robot
    from creature_lab.robots.report import PolicyResult, write_report

    robot, folders = output_robot(results)
    _ensure_downloaded(robot, accept=False)
    path = make_film(results, progress=lambda m: console.print(f"  {m}"))
    items = [PolicyResult(read_checkup(folder), folder) for folder in folders.values()]
    write_report(results, items, film=path.name)
    console.print(f"Film: [bold]{path}[/bold]")


@robots_app.command("loop")
def loop_command(
    results: Annotated[Path, typer.Argument(help="A folder written by `robots checkup`.")],
    output: Annotated[
        Path | None,
        typer.Option("--output", help="Animated .webp or .gif to write."),
    ] = None,
) -> None:
    """Write the short README loop (animated WebP or GIF)."""
    _require_extra()
    from creature_lab.robots.film import make_loop, output_robot

    if output is None:
        robot, _ = output_robot(results)
        output = Path("docs/assets") / f"checkup-{robot.replace('_', '-')}.webp"
    console.print(f"Loop: [bold]{make_loop(results, output)}[/bold]")


@robots_app.command("compare")
def compare_command(
    before: Annotated[Path, typer.Argument(help="Results of the earlier policy or release.")],
    after: Annotated[Path, typer.Argument(help="Results of the new policy or release.")],
    policy: Annotated[
        str | None,
        typer.Option("--policy", help="Policy to read when a folder holds several."),
    ] = None,
    fail_on_regression: Annotated[
        bool,
        typer.Option(
            "--fail-on-regression", help="Exit with status 1 if any test got worse (for CI)."
        ),
    ] = False,
    tolerance: Annotated[
        int,
        typer.Option(
            help="How much a shove strength may get worse before it counts: a shove that leaves "
            "the robot on the floor costs 2, one it recovers from costs 1."
        ),
    ] = 0,
    json_out: Annotated[
        Path | None, typer.Option("--json", help="Also write the comparison as JSON.")
    ] = None,
    markdown_out: Annotated[
        Path | None,
        typer.Option("--markdown", help="Also write a table for a pull-request comment."),
    ] = None,
) -> None:
    """Did a change make the robot more or less robust? Compare two check-ups.

    Reads saved results only, so it needs no simulator. Each argument is a folder holding
    checkup.json, or a results folder with one policy folder inside (or pick with --policy).
    """
    from creature_lab.robots.compare import CompareError, compare_folders, write_json

    try:
        comparison = compare_folders(before, after, policy=policy, tolerance=tolerance)
    except (CompareError, FileNotFoundError) as exc:
        console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=2) from exc

    table = Table(
        title=f"{comparison.robot.replace('_', ' ')}: "
        f"{comparison.before_policy} → {comparison.after_policy}"
    )
    for column in ("Test", "Before", "After", ""):
        table.add_column(column)
    style = {"better": "[green]better[/green]", "worse": "[red]worse[/red]", "same": ""}
    for change in comparison.changes:
        table.add_row(change.label, change.before, change.after, style[change.verdict])
    console.print(table)
    if comparison.skipped:
        console.print(f"Not compared (only one side ran them): {', '.join(comparison.skipped)}")
    console.print(comparison.summary())
    if json_out is not None:
        console.print(f"JSON: {write_json(comparison, json_out)}")
    if markdown_out is not None:
        markdown_out.parent.mkdir(parents=True, exist_ok=True)
        markdown_out.write_text(comparison.to_markdown(), encoding="utf-8")
        console.print(f"Markdown: {markdown_out}")
    if fail_on_regression and comparison.regressed:
        raise typer.Exit(code=1)


@robots_app.command("card")
def card_command(
    results: Annotated[
        Path, typer.Argument(help="A folder holding checkup.json, or one holding policy folders.")
    ],
    policy: Annotated[
        str | None, typer.Option("--policy", help="Policy to use when the folder holds several.")
    ] = None,
    out: Annotated[Path, typer.Option("--out", help="Where to write the SVG card.")] = Path(
        "robustness-card.svg"
    ),
) -> None:
    """Write a robustness card (SVG) and a one-line claim for a README or model card."""
    from creature_lab.robots.card import markdown, write_card
    from creature_lab.robots.checkup import read_checkup
    from creature_lab.robots.compare import CompareError, find_checkup

    try:
        checkup = read_checkup(find_checkup(results, policy))
    except (CompareError, FileNotFoundError) as exc:
        console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=2) from exc
    path = write_card(checkup, out)
    console.print(f"Card: [bold]{path}[/bold]\n")
    console.print("Paste this into your README or model card:\n")
    console.print(markdown(checkup, path.name), markup=False, highlight=False)
