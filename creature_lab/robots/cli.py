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

from creature_lab.robots.catalog import ROBOTS, robot_info
from creature_lab.robots.fetch import (
    FetchError,
    cache_root,
    ensure_robot,
    is_installed,
    missing_extra,
    robot_dir,
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
    if key not in ROBOTS:
        raise typer.BadParameter(f"choose one of: {', '.join(ROBOTS)}")
    return key


@robots_app.command("list")
def list_robots() -> None:
    """Show the robots Creature Lab can check up and whether they are downloaded."""
    table = Table(title=f"Robots (downloads go to {cache_root()})")
    for column in ("Robot", "Maker", "Height", "Policies", "Downloaded"):
        table.add_column(column)
    for info in ROBOTS.values():
        table.add_row(
            info.key.replace("_", "-"),
            info.maker,
            f"{info.height_cm} cm",
            ", ".join(p.key for p in info.policies),
            "yes" if is_installed(info.key) else "no",
        )
    console.print(table)


@robots_app.command("fetch")
def fetch(
    robot: Annotated[str, typer.Argument(help="microduck or unitree-g1")],
    yes: Annotated[bool, typer.Option("--yes", help="Accept the license notice.")] = False,
) -> None:
    """Download a robot's model files, verified against pinned hashes."""
    key = _robot_arg(robot)
    _ensure_downloaded(key, yes)
    console.print(f"{robot_info(key).title} is ready in {robot_dir(key)}")


@robots_app.command("checkup")
def checkup(
    robot: Annotated[str, typer.Argument(help="microduck or unitree-g1")],
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
    output: Annotated[Path, typer.Option("--output", help="Animated WebP to write.")] = Path(
        "docs/assets/checkup-microduck.webp"
    ),
) -> None:
    """Write the short side-by-side README loop (animated WebP)."""
    _require_extra()
    from creature_lab.robots.film import make_loop

    console.print(f"Loop: [bold]{make_loop(results, output)}[/bold]")
