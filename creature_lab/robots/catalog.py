"""The robots Creature Lab can check up, with their sources, licenses, and policies."""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources


@dataclass(frozen=True)
class PolicyInfo:
    key: str
    title: str
    summary: str
    #: Path inside the downloaded robot folder, or None for a policy bundled in the package.
    file: str | None = None
    #: True if, in our simulation, the policy stands back up after falling.
    gets_up: bool = False


@dataclass(frozen=True)
class RobotInfo:
    key: str
    title: str
    maker: str
    summary: str
    height_cm: int
    #: Name of the JSON manifest in ``creature_lab/robots/data``; None if nothing is downloaded.
    manifest: str | None
    #: Shown before the first download and printed on every report and video.
    license_notice: str
    #: Short credit line for videos and reports.
    credit: str
    #: True when the downloaded files may only be used non-commercially.
    non_commercial: bool
    policies: tuple[PolicyInfo, ...]
    default_policy: str
    #: Forward-speed command that gives a clear walking gait for this policy set.
    walk_command: float
    #: Seconds per stride, measured from the baseline run; shoves are spread across one stride.
    gait_period_s: float
    #: Extra credit lines for the end card of the film.
    film_credits: tuple[str, ...] = ()

    def policy(self, key: str) -> PolicyInfo:
        for policy in self.policies:
            if policy.key == key:
                return policy
        known = ", ".join(p.key for p in self.policies)
        raise KeyError(f"{self.key} has no policy {key!r} (choose from: {known})")


ROBOTS: dict[str, RobotInfo] = {
    "microduck": RobotInfo(
        key="microduck",
        title="Microduck",
        maker="Pollen Robotics and Hugging Face",
        summary="A 25 cm, 800 g two-legged desk robot with 14 servos. Shown by NVIDIA at GTC "
        "Berlin in October 2026.",
        height_cm=25,
        manifest="microduck.json",
        license_notice=(
            "Microduck's model and policies are published by Pollen Robotics at "
            "github.com/pollen-robotics/microduck_rl and huggingface.co/pollen-robotics/"
            "microduck-policies. The code, model XML and policies are Apache-2.0, but the 3D mesh "
            "files (*.stl) are licensed CC BY-NC-SA 4.0: non-commercial, share-alike, credit "
            "Pollen Robotics. Creature Lab downloads them to your machine and never bundles them. "
            "Pictures and videos that show them must carry the credit line and stay "
            "non-commercial."
        ),
        credit="Microduck model by Pollen Robotics, CC BY-NC-SA 4.0",
        non_commercial=True,
        policies=(
            PolicyInfo(
                "velstand",
                "Walk + get-up policy",
                "Pollen's current default: walks, stands still at zero command, and gets up "
                "after a fall.",
                "policies/velstand.onnx",
                gets_up=True,
            ),
            PolicyInfo(
                "alpha_walking",
                "Walk-only policy",
                "An earlier walking policy. In our tests it does not get up after a fall.",
                "policies/alpha_walking.onnx",
            ),
        ),
        default_policy="velstand",
        walk_command=0.5,
        gait_period_s=0.4,
        film_credits=(
            "Policies: Pollen Robotics (Apache-2.0) · Servo model: Rhoban BAM (Apache-2.0) · "
            "Physics: MuJoCo",
        ),
    ),
    "unitree_g1": RobotInfo(
        key="unitree_g1",
        title="Unitree G1",
        maker="Unitree Robotics",
        summary="A 1.3 m humanoid. Creature Lab runs its 12 leg joints with Unitree's own "
        "pretrained walking policy; the arms are held still.",
        height_cm=130,
        manifest="unitree_g1.json",
        license_notice=(
            "The G1 model and walking policy come from github.com/unitreerobotics/"
            "unitree_rl_gym (BSD 3-Clause, Copyright Unitree Robotics). Creature Lab downloads "
            "the model on first use; the policy weights are bundled in converted form with the "
            "license text beside them."
        ),
        credit="Unitree G1 model and policy: Unitree Robotics, BSD 3-Clause",
        non_commercial=False,
        policies=(
            PolicyInfo(
                "motion",
                "Unitree walking policy",
                "Unitree's pretrained forward-walking policy. It has no fall recovery.",
            ),
        ),
        default_policy="motion",
        walk_command=0.5,
        gait_period_s=0.8,
        film_credits=("Physics: MuJoCo",),
    ),
}


def robot_info(key: str) -> RobotInfo:
    try:
        return ROBOTS[key]
    except KeyError:
        raise KeyError(f"unknown robot {key!r} (choose from: {', '.join(ROBOTS)})") from None


def load_manifest(info: RobotInfo) -> dict:
    """The pinned download list: url, sha256 and size for every file."""
    if info.manifest is None:
        return {"files": []}
    text = resources.files("creature_lab.robots").joinpath("data", info.manifest).read_text("utf-8")
    return json.loads(text)
