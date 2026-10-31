"""The check-up films: scripts that turn saved runs and their analyses into a story."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PIL import Image

from creature_lab.robots import overlay
from creature_lab.robots.analysis import RunAnalysis, analyze
from creature_lab.robots.api import run_scenario
from creature_lab.robots.catalog import robot_info
from creature_lab.robots.checkup import SHOVE_PHASES, Checkup, read_checkup
from creature_lab.robots.render import Shot, Studio
from creature_lab.robots.types import RobotRun, Scenario
from creature_lab.robots.video import Card, Clip, SplitClip

_W, _H = 1920, 1080
_HALF_W = 960
_DISCLAIMER = "Simulation, not hardware: these results describe the simulated robot only."
_STORY_FORCE_N = 3.0
#: Pushes the robot right of centre in the opening shot, clear of the headline.
_HERO_SHIFT = 0.16
#: Wider framing for the half-width panels of a split screen.
_HALF_SHOT = Shot(distance=0.95, look_height=0.11)


def _credit(robot: str) -> str:
    return f"{robot_info(robot).credit} · simulation"


def _evidence_items(analysis: RunAnalysis) -> list[tuple[str, str, tuple]]:
    """The panel rows: red where the evidence blames something, teal where it clears it."""
    by_label = {item.label: item for item in analysis.evidence}
    rows = []
    margin = by_label.get("Balance point vs feet")
    if margin is not None:
        outside = "outside" in margin.value
        rows.append(
            ("Balance point vs feet", margin.value, overlay.RED if outside else overlay.TEAL)
        )
    slide = by_label["Feet slide on the floor"]
    rows.append(
        (slide.label, slide.value, overlay.RED if analysis.cause == "slipped" else overlay.TEAL)
    )
    load = by_label["Servos at their torque limit"]
    rows.append(
        (
            load.label,
            load.value,
            overlay.RED if analysis.cause == "servos_saturated" else overlay.TEAL,
        )
    )
    return rows


def find_pair(
    robot: str,
    policy_a: str,
    policy_b: str,
    force_n: float,
    progress: Callable[[str], None] | None = None,
) -> tuple[RobotRun, RobotRun]:
    """The same shove, at the same moment, for two policies: A stays down, B gets back up."""
    info = robot_info(robot)
    fallback = None
    for phase in range(SHOVE_PHASES):
        changes = {
            "push_n": force_n,
            "push_side": "left" if phase % 2 == 0 else "right",
            "push_at_s": 4.0 + phase * info.gait_period_s / SHOVE_PHASES,
            "command": info.walk_command,
        }
        run_a = run_scenario(Scenario(robot=robot, policy=policy_a, **changes))
        run_b = run_scenario(Scenario(robot=robot, policy=policy_b, **changes))
        outcome_a, outcome_b = analyze(run_a).outcome, analyze(run_b).outcome
        if outcome_a == "fell" and outcome_b == "fell_and_got_up":
            return run_a, run_b
        if outcome_a == "fell" and fallback is None:
            fallback = (run_a, run_b)
    if fallback is None:
        raise RuntimeError(f"no {force_n:g} N shove makes {policy_a} fall; pick another strength")
    return fallback


def _chart_card(title: str, subtitle: str, groups, series, top: float, footer=()) -> Card:
    return Card(
        7.0,
        lambda progress: overlay.bar_chart(
            (_W, _H), title, subtitle, groups, series, top, min(progress * 1.7, 1.0), footer=footer
        ),
        key=lambda progress: round(min(progress * 1.7, 1.0), 3),
    )


def _end_card(headline: str, command: str, credits: list[str]) -> Card:
    def draw(progress: float) -> Image.Image:
        base = overlay.title_card(_W, _H, headline, "", "Creature Lab")
        over, draw_ = overlay.layer(_W, _H)
        left = _W * 0.08
        overlay.panel(draw_, (left, 590, left + 980, 668), 16, alpha=255, outline=overlay.GRID)
        overlay.text(draw_, (left + 28, 606), command, 36, overlay.AMBER, "bold")
        y = 720
        for line in credits:
            overlay.text(draw_, (left, y), line, 24, overlay.MUTED)
            y += 36
        overlay.text(draw_, (left, y + 10), _DISCLAIMER, 24, overlay.TEXT, "bold")
        return overlay.composite(base, over)

    return Card(7.0, draw, key=lambda progress: 0)


def _shove_label(run: RobotRun) -> str:
    return f"{run.scenario.push_n:g} N SHOVE"


def comparison_story(
    walk_only: Path, with_getup: Path, out_dir: Path, progress: Callable[[str], None] | None = None
) -> list:
    """Scenes of the film from two saved check-ups: one policy that stays down, one that gets up."""
    say = progress or (lambda message: None)
    a, b = read_checkup(walk_only), read_checkup(with_getup)
    robot = a.robot
    info = robot_info(robot)
    credit = _credit(robot)
    title_a, title_b = (info.policy(a.policy).title, info.policy(b.policy).title)
    base_a = RobotRun.read(walk_only / "runs" / a.baseline_run)

    say("finding a shove both policies react to differently")
    pair_a, pair_b = find_pair(robot, a.policy, b.policy, _STORY_FORCE_N)
    for name, run in (("story_a", pair_a), ("story_b", pair_b)):
        run.save(Path(out_dir) / "runs" / name)
    an_a, an_b = analyze(pair_a), analyze(pair_b)
    push_at = pair_a.scenario.push_at_s
    fall_a = an_a.fall_time_s or push_at + 0.6

    studio = Studio(robot, _W, _H)
    scenes: list = []

    scenes.append(
        Clip(
            studio,
            base_a,
            1.0,
            6.0,
            info.title,
            title_a,
            credit,
            timeline=False,
            markers=False,
            shift=_HERO_SHIFT,
            hero=(
                "Creature Lab robot check-up",
                "Will your robot's walk survive a shove?",
                "Real robot model, real trained policy, one simulated shove.",
            ),
        )
    )
    scenes.append(
        Clip(
            studio,
            base_a,
            5.0,
            9.0,
            info.title,
            title_a,
            credit,
            timeline=False,
            markers=True,
            captions=[
                (5.0, 7.0, [f"{info.title}: {info.height_cm} cm tall"]),
                (7.0, 9.0, [f"Made by {info.maker}"]),
            ],
        )
    )
    scenes.append(
        Clip(
            studio,
            pair_a,
            push_at - 1.4,
            min(push_at + 4.4, 9.9),
            info.title,
            title_a,
            credit,
            slow=[(push_at - 0.05, fall_a + 0.5, 0.3)],
            captions=[
                (push_at - 1.4, push_at - 0.05, [f"Test: a {_STORY_FORCE_N:g} N sideways shove"]),
                (fall_a + 1.6, fall_a + 4.0, ["It falls, and it never gets back up."]),
            ],
            tags=[(push_at, _shove_label(pair_a), overlay.ORANGE), (fall_a, "FELL", overlay.RED)],
            evidence=(
                fall_a + 0.9,
                "Why it fell",
                [*_evidence_items(an_a), ("Verdict", "Pushed off balance", overlay.ORANGE)],
            ),
        )
    )

    top = float(a.shoves[0].total)
    groups = [f"{row.force_n:g} N" for row in a.shoves]
    scenes.append(
        _chart_card(
            "Shoves that leave the robot on the floor",
            f"{title_a} · {SHOVE_PHASES} shoves per strength, each at a different moment in the "
            "stride",
            groups,
            [(title_a, overlay.ORANGE, [float(r.stayed_down) for r in a.shoves])],
            top,
        )
    )

    left = Clip(
        Studio(robot, _HALF_W, _H, shot=_HALF_SHOT),
        pair_a,
        push_at - 0.9,
        push_at + 4.4,
        info.title,
        title_a,
        credit,
        slow=[(push_at - 0.05, push_at + 1.3, 0.3)],
        timeline=False,
        tags=[(push_at, _shove_label(pair_a), overlay.ORANGE), (fall_a, "STAYS DOWN", overlay.RED)],
    )
    fall_b = an_b.fall_time_s or fall_a
    got_up = an_b.recovered_time_s or fall_b + 1.0
    right = Clip(
        Studio(robot, _HALF_W, _H, shot=_HALF_SHOT),
        pair_b,
        push_at - 0.9,
        push_at + 4.4,
        info.title,
        title_b,
        credit,
        slow=[(push_at - 0.05, push_at + 1.3, 0.3)],
        timeline=False,
        tags=[
            (push_at, _shove_label(pair_b), overlay.ORANGE),
            (fall_b, "FELL", overlay.RED),
            (got_up, "BACK ON ITS FEET", overlay.TEAL),
        ],
        captions=[(push_at - 0.9, push_at - 0.1, ["Same shove, same moment"])],
    )
    scenes.append(SplitClip(left, right))

    falls_a = sum(r.total - r.stayed_up for r in a.shoves)
    falls_b = sum(r.total - r.stayed_up for r in b.shoves)
    total = sum(r.total for r in a.shoves)
    down_a = sum(r.stayed_down for r in a.shoves)
    down_b = sum(r.stayed_down for r in b.shoves)
    scenes.append(
        _chart_card(
            "One change: Pollen's newer policy",
            f"Shoves that leave the robot on the floor · {SHOVE_PHASES} per strength",
            groups,
            [
                (title_a, overlay.ORANGE, [float(r.stayed_down) for r in a.shoves]),
                (title_b, overlay.TEAL, [float(r.stayed_down) for r in b.shoves]),
            ],
            top,
            footer=[
                f"Left on the floor: {down_a} of {total} with {title_a.lower()}, {down_b} of "
                f"{total} with {title_b.lower()}.",
                f"It falls slightly more often ({falls_b} vs {falls_a} falls of {total}), but "
                "gets back up every time.",
            ],
        )
    )

    ice = next((c for c in b.conditions if c.key == "grip_0.15"), None)
    if ice is not None:
        ice_run = RobotRun.read(with_getup / "runs" / ice.run)
        fall_ice = ice.analysis.fall_time_s or 4.0
        scenes.append(
            Clip(
                studio,
                ice_run,
                max(fall_ice - 3.0, 0.5),
                min(fall_ice + 4.0, 9.9),
                info.title,
                title_b,
                credit,
                slow=[(fall_ice - 0.8, fall_ice + 0.4, 0.35)],
                captions=[
                    (
                        max(fall_ice - 3.0, 0.5),
                        fall_ice - 0.8,
                        ["What is left: a very slippery floor (0.15× normal grip)"],
                    )
                ],
                tags=[(0.0, "0.15× GRIP", overlay.AMBER), (fall_ice, "FELL", overlay.RED)],
                evidence=(
                    fall_ice + 0.8,
                    "Why it fell",
                    [
                        *_evidence_items(ice.analysis),
                        ("Verdict", "No policy swap fixes ice", overlay.ORANGE),
                    ],
                ),
            )
        )
    scenes.append(
        _end_card(
            "Check your own robot",
            f"creature-lab robots checkup {robot.replace('_', '-')}",
            [info.credit, *info.film_credits],
        )
    )
    return scenes


def single_story(checkup_dir: Path, robot: str, out_dir: Path) -> list:
    """Scenes for a one-policy film (the G1): the shove limit, one fall, and what it carries."""
    checkup: Checkup = read_checkup(checkup_dir)
    info = robot_info(robot)
    policy = info.policy(checkup.policy)
    credit = _credit(robot)
    base = RobotRun.read(checkup_dir / "runs" / checkup.baseline_run)
    studio = Studio(robot, _W, _H)
    scenes: list = [
        Clip(
            studio,
            base,
            1.5,
            6.5,
            info.title,
            policy.title,
            credit,
            timeline=False,
            markers=False,
            shift=_HERO_SHIFT,
            hero=(
                "Creature Lab robot check-up",
                f"How hard can a {info.title} be shoved?",
                "Unitree's own walking policy, a real robot model, one simulated shove.",
            ),
        )
    ]
    fall_row = next((r for r in checkup.shoves if r.example_fall_run), None)
    if fall_row is not None:
        run = RobotRun.read(checkup_dir / "runs" / fall_row.example_fall_run)
        analysis = analyze(run)
        push_at = run.scenario.push_at_s
        fall = analysis.fall_time_s or push_at + 0.6
        scenes.append(
            Clip(
                studio,
                run,
                push_at - 1.6,
                min(push_at + 4.4, 9.9),
                info.title,
                policy.title,
                credit,
                slow=[(push_at - 0.05, fall + 0.6, 0.3)],
                captions=[
                    (
                        push_at - 1.6,
                        push_at - 0.05,
                        [f"Test: a {fall_row.force_n:g} N sideways shove"],
                    ),
                    (fall + 1.4, fall + 3.5, ["It falls, and it never gets back up."]),
                ],
                tags=[(push_at, _shove_label(run), overlay.ORANGE), (fall, "FELL", overlay.RED)],
                evidence=(
                    fall + 0.9,
                    "Why it fell",
                    [*_evidence_items(analysis), ("Verdict", "Pushed off balance", overlay.ORANGE)],
                ),
            )
        )
    top = float(checkup.shoves[0].total)
    scenes.append(
        _chart_card(
            "How many of the shoves does it stay up for?",
            f"{policy.title} · {SHOVE_PHASES} shoves per strength, each at a different moment in "
            "the stride",
            [f"{r.force_n:g} N" for r in checkup.shoves],
            [(info.title, overlay.TEAL, [float(r.stayed_up) for r in checkup.shoves])],
            top,
            footer=[
                f"Never falls up to {checkup.never_falls_up_to_n:g} N."
                if checkup.never_falls_up_to_n
                else "Falls even at the lightest shove tested.",
                "Every fall is final: this policy has no get-up behaviour.",
            ],
        )
    )
    load = next((c for c in reversed(checkup.conditions) if c.key.startswith("payload")), None)
    if load is not None:
        run = RobotRun.read(checkup_dir / "runs" / load.run)
        scenes.append(
            Clip(
                studio,
                run,
                1.0,
                7.0,
                info.title,
                policy.title,
                credit,
                timeline=False,
                captions=[
                    (
                        1.0,
                        7.0,
                        [
                            f"Carrying {run.scenario.payload_kg:g} kg: "
                            f"still walking ({load.relative_distance:.0%} of the distance)"
                        ],
                    )
                ],
                tags=[(0.0, f"+{run.scenario.payload_kg:g} KG", overlay.AMBER)],
            )
        )
    scenes.append(
        _end_card(
            "Check your own robot",
            f"creature-lab robots checkup {robot.replace('_', '-')}",
            [info.credit, *info.film_credits],
        )
    )
    return scenes


def readme_loop(pair_a: RobotRun, pair_b: RobotRun, robot: str = "microduck") -> SplitClip:
    """A short side-by-side loop for the README: same shove, one stays down, one gets up."""
    info = robot_info(robot)
    push_at = pair_a.scenario.push_at_s
    an_a, an_b = analyze(pair_a), analyze(pair_b)
    fall_a = an_a.fall_time_s or push_at + 0.6
    fall_b = an_b.fall_time_s or fall_a
    got_up = an_b.recovered_time_s or fall_b + 1.0
    credit = _credit(robot)
    window = (push_at - 0.7, push_at + 3.4)
    slow = [(push_at - 0.05, push_at + 1.0, 0.3)]
    left = Clip(
        Studio(robot, 640, 720, shot=_HALF_SHOT),
        pair_a,
        *window,
        info.title,
        info.policy(pair_a.scenario.policy).title,
        credit,
        slow=slow,
        timeline=False,
        tags=[(push_at, _shove_label(pair_a), overlay.ORANGE), (fall_a, "STAYS DOWN", overlay.RED)],
    )
    right = Clip(
        Studio(robot, 640, 720, shot=_HALF_SHOT),
        pair_b,
        *window,
        info.title,
        info.policy(pair_b.scenario.policy).title,
        credit,
        slow=slow,
        timeline=False,
        tags=[
            (push_at, _shove_label(pair_b), overlay.ORANGE),
            (fall_b, "FELL", overlay.RED),
            (got_up, "BACK ON ITS FEET", overlay.TEAL),
        ],
    )
    return SplitClip(left, right)
