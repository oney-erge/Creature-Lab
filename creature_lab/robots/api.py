"""Front door for robot check-ups: build the right robot for a scenario and run it."""

from __future__ import annotations

from pathlib import Path

from creature_lab.robots.catalog import robot_info
from creature_lab.robots.rollout import MujocoRobot, run_robot
from creature_lab.robots.types import RobotRun, Scenario


def make_robot(scenario: Scenario) -> MujocoRobot:
    info = robot_info(scenario.robot)
    info.policy(scenario.policy)  # fails early with the valid choices
    if info.folder is not None:
        from creature_lab.robots.pack import load_pack
        from creature_lab.robots.packbot import PackRobot

        return PackRobot(scenario, load_pack(info.folder))
    if scenario.robot == "microduck":
        from creature_lab.robots.microduck import Microduck

        return Microduck(scenario)
    if scenario.robot == "unitree_g1":
        from creature_lab.robots.g1 import UnitreeG1

        return UnitreeG1(scenario)
    raise KeyError(f"no simulator for robot {scenario.robot!r}")


def run_scenario(scenario: Scenario, save_to: Path | None = None) -> RobotRun:
    """Run one scenario; optionally save it (``robot_run.json`` + ``states.npz``)."""
    run = run_robot(make_robot(scenario))
    if save_to is not None:
        run.save(save_to)
    return run
