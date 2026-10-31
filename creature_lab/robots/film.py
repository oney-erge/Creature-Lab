"""Turn saved check-up folders into the finished media: the film and the README loop."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from creature_lab.robots.catalog import robot_info
from creature_lab.robots.checkup import read_checkup
from creature_lab.robots.story import (
    _STORY_FORCE_N,
    comparison_story,
    find_pair,
    readme_loop,
    single_story,
)


def policy_pair(robot: str) -> tuple[str, str] | None:
    """(stays down, gets up) policy keys for a robot, if it has one of each."""
    policies = robot_info(robot).policies
    down = [p.key for p in policies if not p.gets_up]
    up = [p.key for p in policies if p.gets_up]
    return (down[0], up[0]) if down and up else None


def checkup_folders(out_dir: Path) -> dict[str, Path]:
    """Policy key -> folder, for every ``checkup.json`` one level under ``out_dir``."""
    return {read_checkup(f.parent).policy: f.parent for f in Path(out_dir).glob("*/checkup.json")}


def output_robot(out_dir: Path) -> tuple[str, dict[str, Path]]:
    folders = checkup_folders(out_dir)
    if not folders:
        raise FileNotFoundError(f"no check-up results found under {out_dir}")
    return read_checkup(next(iter(folders.values()))).robot, folders


def film_name(robot: str) -> str:
    return f"{robot.replace('_', '-')}-checkup.mp4"


def make_film(out_dir: Path, progress: Callable[[str], None] | None = None) -> Path:
    """Encode the 1080p check-up film for the results in ``out_dir``."""
    from creature_lab.robots.video import frames, write_mp4

    out_dir = Path(out_dir)
    robot, folders = output_robot(out_dir)
    pair = policy_pair(robot)
    if pair and all(key in folders for key in pair):
        scenes = comparison_story(folders[pair[0]], folders[pair[1]], out_dir, progress)
    else:
        scenes = single_story(next(iter(folders.values())), robot, out_dir)
    return write_mp4(out_dir / film_name(robot), frames(scenes))


def make_loop(out_dir: Path, destination: Path) -> Path:
    """The short README loop (animated WebP): the same shove, one stays down, one gets up."""
    from creature_lab.robots.video import frames, write_webp

    robot, folders = output_robot(Path(out_dir))
    pair = policy_pair(robot)
    if not pair or not all(key in folders for key in pair):
        raise ValueError(f"{robot} needs check-ups for both {pair} to make the comparison loop")
    run_a, run_b = find_pair(robot, pair[0], pair[1], _STORY_FORCE_N)
    return write_webp(destination, frames([readme_loop(run_a, run_b, robot)]), width=960, step=2)
