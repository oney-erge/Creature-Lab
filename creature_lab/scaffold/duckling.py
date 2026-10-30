"""An original, editable biped with a duck-like silhouette."""

from __future__ import annotations

from creature_lab.scaffold.humanoid import generate_humanoid
from creature_lab.schema import CreatureSpec


def generate_duckling(*, height: float = 0.8, mass: float = 8.0) -> CreatureSpec:
    """Build a small biped with pitch and roll hips and independently driven feet.

    The visible face is a viewer decoration; these primitive parts define physics.
    """
    data = generate_humanoid(height=height, mass=mass, dof=12).model_dump(mode="json")
    data["name"] = "duckling"
    data["metadata"]["appearance"] = "duckling"
    removed = {
        f"{name}_{side}" for side in ("l", "r") for name in ("upper_arm", "lower_arm", "hand")
    }
    data["parts"] = [part for part in data["parts"] if part["id"] not in removed]
    data["joints"] = [joint for joint in data["joints"] if joint["child"] not in removed]
    hinges = {joint["id"] for joint in data["joints"] if joint["type"] == "hinge"}
    data["motors"] = [motor for motor in data["motors"] if motor["joint"] in hinges]
    for part in data["parts"]:
        if part["id"] == "torso":
            part["size"] = [0.25 * height, 0.28 * height, 0.25 * height]
            part["color"] = [0.97, 0.79, 0.28]
        elif part["id"] == "head":
            part["radius"] = 0.14 * height
            part["color"] = [1.0, 0.88, 0.46]
        elif part["id"].startswith("foot_"):
            part["color"] = [0.94, 0.42, 0.16]
        else:
            part["color"] = [0.29, 0.34, 0.40]
    for side in ("l", "r"):
        hip = next(joint for joint in data["joints"] if joint["id"] == f"hip_{side}")
        anchor = hip["anchor"]
        data["parts"].append(
            {
                "id": f"roll_link_{side}",
                "shape": "sphere",
                "radius": 0.025 * height,
                "mass": 0.02 * mass,
                "color": [0.29, 0.34, 0.40],
            }
        )
        data["joints"].append(
            {
                "id": f"hip_roll_{side}",
                "parent": "torso",
                "child": f"roll_link_{side}",
                "type": "hinge",
                "anchor": anchor,
                "axis": [1, 0, 0],
                "limit": [-0.5, 0.5],
            }
        )
        hip["parent"] = f"roll_link_{side}"
        hip["anchor"] = [0.0, 0.0, 0.0]
        data["motors"].append(
            {
                "joint": f"hip_roll_{side}",
                "type": "sinusoid",
                "amplitude": 0.0,
                "frequency": 1.0,
                "phase": 0.0,
                "max_force": 160.0 * mass / 60.0,
            }
        )
    scale = mass / sum(part["mass"] for part in data["parts"])
    for part in data["parts"]:
        part["mass"] *= scale
    return CreatureSpec.model_validate(data)
