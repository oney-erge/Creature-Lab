"""One-click "what if" runs: the same test with one thing changed.

A person looking at a run can ask what would have happened with the shove from the other side, a
harder shove, a slippery floor, a heavier load or a weak battery. The change is applied to the run's
own scenario, the robot is run again (about a second or two on a laptop), and the result is saved
next to the check-up as a run of its own. Runs are deterministic, so asking twice reuses the saved
one. The browser only ever names a change from a fixed menu; it never supplies numbers or paths.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: The what-if runs' folder-name prefix; the library lists them under "What if".
PREFIX = "whatif_"
_ICE_GRIP = 0.15
_FULL_BATTERY_V = 7.4


@dataclass(frozen=True)
class WhatIf:
    key: str
    #: The button: what you would be asking.
    label: str
    #: The same thing inside a sentence about the result ("on a very slippery floor").
    short: str
    #: ``Scenario`` fields to change.
    change: dict[str, Any]


def options(scenario: dict, robot: str) -> list[WhatIf]:
    """The changes that make sense for a run with this ``scenario`` (a saved ``scenario`` dict)."""
    from creature_lab.robots.checkup import tested_levels

    levels = tested_levels(robot)
    found: list[WhatIf] = []
    if scenario["push_n"] > 0:
        other = "right" if scenario["push_side"] == "left" else "left"
        found.append(
            WhatIf(
                "other_side",
                "Shoved from the other side",
                "shoved from the other side",
                {"push_side": other},
            )
        )
        harder = min(round(scenario["push_n"] * 1.5, 1), 2000.0)
        gentler = round(scenario["push_n"] * 2 / 3, 1)
        found.append(
            WhatIf(
                "harder",
                "A harder shove",
                f"harder than the {scenario['push_n']:g} N original",
                {"push_n": harder},
            )
        )
        if gentler >= 0.5:
            found.append(
                WhatIf(
                    "gentler",
                    "A gentler shove",
                    f"gentler than the {scenario['push_n']:g} N original",
                    {"push_n": gentler},
                )
            )
    if scenario["grip"] > _ICE_GRIP:
        found.append(
            WhatIf(
                "ice", "On a very slippery floor", "on a very slippery floor", {"grip": _ICE_GRIP}
            )
        )
    command = scenario["command"]
    if command > 0.1:
        slower = max(0.1, round(command * 0.5, 2))
        found.append(
            WhatIf("slower", "Walking at half speed", "walking at half speed", {"command": slower})
        )
    if command < 1.0:
        faster = min(1.0, round(command * 1.6, 2))
        found.append(WhatIf("faster", "Walking faster", "walking faster", {"command": faster}))
    if levels.payloads_kg and scenario["payload_kg"] == 0:
        kilos = levels.payloads_kg[len(levels.payloads_kg) // 2]
        found.append(
            WhatIf(
                "load", f"Carrying {kilos:g} kg", f"carrying {kilos:g} kg", {"payload_kg": kilos}
            )
        )
    if levels.batteries_v and scenario["battery_v"] >= _FULL_BATTERY_V:
        volts = min(levels.batteries_v)
        found.append(
            WhatIf(
                "weak_battery",
                f"On a weak {volts:g} V battery",
                f"on a weak {volts:g} V battery",
                {"battery_v": volts},
            )
        )
    return found


def is_what_if(name: str) -> bool:
    return name.startswith(PREFIX)


class WhatIfError(ValueError):
    """The named change does not apply to this run."""


_lock = threading.Lock()


def run_what_if(source_folder: Path, scenario: dict, robot: str, title: str, key: str) -> Path:
    """Run ``key`` on a saved run and save it beside the source; returns the new run's folder.

    One what-if runs at a time (they are CPU-bound and short), and a repeat reuses the saved run.
    """
    from creature_lab.robots.types import Scenario

    option = next((o for o in options(scenario, robot) if o.key == key), None)
    if option is None:
        raise WhatIfError(f"{key!r} does not apply to this run")
    out = source_folder.parent / f"{PREFIX}{key}_{source_folder.name}"
    with _lock:
        if (out / "robot_run.json").is_file():
            return out
        from creature_lab.robots.api import run_scenario

        # A run titled "150 N shove" that is now a 100 N shove must say so.
        if "push_n" in option.change:
            title = re.sub(r"^\d+(?:\.\d+)? N shove", f"{option.change['push_n']:g} N shove", title)
        changed = Scenario.model_validate(scenario).model_copy(
            update={**option.change, "title": f"{title}, {option.short}"}
        )
        run = run_scenario(changed)
        run.provenance = {
            **run.provenance,
            "what_if": {
                "from": source_folder.name,
                "change": option.key,
                "label": option.label,
                "short": option.short,
            },
        }
        run.save(out)
    return out
