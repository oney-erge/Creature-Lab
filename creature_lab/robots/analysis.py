"""Explain a robot run: did it fall, when, and what the recorded evidence says about why."""

from __future__ import annotations

import math
from typing import Literal

import numpy as np
from pydantic import Field

from creature_lab.robots.catalog import robot_info
from creature_lab.robots.types import CONTROL_HZ, RobotRun
from creature_lab.schema.base import StrictModel

#: Trunk tilt past 60 degrees (``upright`` below 0.5) counts as a fall.
FALL_UPRIGHT = 0.5
#: Upright above this for half a second counts as back on its feet.
RECOVERED_UPRIGHT = 0.9
_RECOVERED_HOLD_S = 0.5
#: Look-back window before a fall used for the cause evidence.
_LOOKBACK_S = 0.8
#: Median contact-point slide (m/s) in the look-back window above which feet were slipping.
SLIP_MEDIAN_MPS = 0.05
#: A servo at this fraction of its torque limit is saturated.
SATURATED_LOAD = 0.95
_GRAVITY = 9.81

Cause = Literal["slipped", "pushed", "servos_saturated", "unclear"]


class Evidence(StrictModel):
    label: str
    value: str
    detail: str


class RunAnalysis(StrictModel):
    """The plain-language verdict for one run, with the numbers behind it."""

    outcome: Literal["walked", "fell_and_got_up", "fell"]
    verdict: str
    fall_time_s: float | None = None
    tilt_start_s: float | None = None
    recovered_time_s: float | None = None
    distance_m: float
    peak_tilt_deg: float
    cause: Cause | None = None
    cause_text: str | None = None
    #: Smallest gap (cm) between the extrapolated balance point and the feet; negative = outside.
    min_balance_margin_cm: float | None = None
    min_balance_margin_s: float | None = None
    slide_median_mps: float | None = None
    saturated_fraction: float | None = None
    evidence: list[Evidence] = Field(default_factory=list)

    @property
    def fell(self) -> bool:
        return self.outcome != "walked"


def _signed_distance_to_hull(point: np.ndarray, hull: np.ndarray) -> float:
    """Metres from ``point`` to a convex outline: positive inside, negative outside."""
    count = len(hull)
    if count == 0:
        return math.nan
    if count == 1:
        return -float(np.hypot(*(point - hull[0])))
    closest = math.inf
    for index in range(count):
        a, b = hull[index], hull[(index + 1) % count]
        edge = b - a
        length2 = float(edge @ edge)
        t = 0.0 if length2 == 0 else float(np.clip(((point - a) @ edge) / length2, 0.0, 1.0))
        closest = min(closest, float(np.hypot(*(point - (a + t * edge)))))
    if count == 2:
        return -closest
    inside = all(
        (hull[(i + 1) % count][0] - hull[i][0]) * (point[1] - hull[i][1])
        - (hull[(i + 1) % count][1] - hull[i][1]) * (point[0] - hull[i][0])
        >= 0
        for i in range(count)
    )
    return closest if inside else -closest


def extrapolated_com(run: RobotRun) -> np.ndarray:
    """Per frame: (x, y) of the extrapolated centre of mass, ``x + v / sqrt(g / h)`` (Hof 2005)."""
    height = np.maximum(run.com[:, 2], 0.05)
    omega = np.sqrt(_GRAVITY / height)
    return run.com[:, :2] + run.com_vel[:, :2] / omega[:, None]


def balance_margin_cm(run: RobotRun) -> np.ndarray:
    """Per frame: gap (cm) between the extrapolated centre of mass and the feet.

    The extrapolated centre of mass (Hof 2005) is where the body is heading if it keeps
    moving as it is: ``x + v / sqrt(g / h)``. While it stays over the feet the robot can
    keep standing; once it passes the edge, the next step has to catch it. NaN while no foot
    touches the floor.
    """
    margin = np.full(len(run), np.nan)
    heading = extrapolated_com(run)
    for frame in range(len(run)):
        outline = run.support[frame]
        outline = outline[~np.isnan(outline[:, 0])]
        if len(outline) == 0:
            continue
        margin[frame] = 100.0 * _signed_distance_to_hull(heading[frame], outline)
    return margin


def analyze(run: RobotRun) -> RunAnalysis:
    scenario = run.scenario
    info = robot_info(scenario.robot)
    policy = info.policy(scenario.policy)
    time = run.time
    upright = run.upright
    tilt_deg = np.degrees(np.arccos(np.clip(upright, -1.0, 1.0)))
    distance = float(run.trunk_pos[-1, 0] - run.trunk_pos[0, 0])
    fallen = np.flatnonzero(upright < FALL_UPRIGHT)
    pushed = scenario.push_n > 0
    push_window = (scenario.push_at_s, scenario.push_at_s + scenario.push_for_s)

    if len(fallen) == 0:
        margin = balance_margin_cm(run)
        evidence = []
        verdict = f"Walked {distance:.1f} m without falling."
        if pushed:
            peak = float(tilt_deg[time >= push_window[0]].max())
            verdict = (
                f"Took a {scenario.push_n:g} N side shove at {scenario.push_at_s:.1f} s, leaned "
                f"{peak:.0f}° and kept walking ({distance:.1f} m)."
            )
            evidence.append(
                Evidence(
                    label="Peak lean after the shove",
                    value=f"{peak:.0f}°",
                    detail="Fall counts as past 60°.",
                )
            )
        return RunAnalysis(
            outcome="walked",
            verdict=verdict,
            distance_m=distance,
            peak_tilt_deg=float(tilt_deg.max()),
            min_balance_margin_cm=_nanmin(margin),
            min_balance_margin_s=_argnanmin_time(margin, time),
            evidence=evidence,
        )

    fall_index = int(fallen[0])
    fall_time = float(time[fall_index])
    upright_before = np.flatnonzero(upright[:fall_index] >= 0.95)
    tilt_start = float(time[upright_before[-1]]) if len(upright_before) else 0.0
    recovered_time = _recovered_time(run, fall_index)

    window = (time >= fall_time - _LOOKBACK_S) & (time <= fall_time)
    margin = balance_margin_cm(run)
    if pushed:
        # The shove's own effect: worst gap between the end of the shove and 0.3 s later.
        reach = np.flatnonzero((time >= push_window[0]) & (time <= push_window[1] + 0.3))
    else:
        reach = np.flatnonzero(window)
    min_margin = _nanmin(margin[reach])
    min_margin_time = _argnanmin_time(margin[reach], time[reach])
    slide = run.slide_speed[window]
    slide_median = float(np.median(slide)) if len(slide) else 0.0
    saturated = float(np.mean(np.abs(run.load[window]).max(axis=1) >= SATURATED_LOAD))
    push_near = pushed and (fall_time - 1.5) <= push_window[1] and fall_time >= push_window[0]

    evidence = [
        Evidence(
            label="Tilt passed 60°",
            value=f"{fall_time:.2f} s",
            detail=f"The trunk was last upright at {tilt_start:.2f} s.",
        ),
        Evidence(
            label="Feet slide on the floor",
            value=f"{slide_median:.2f} m/s",
            detail=f"Median speed of the touching points in the 0.8 s before the fall; "
            f"planted feet read under {SLIP_MEDIAN_MPS:.2f}.",
        ),
        Evidence(
            label="Servos at their torque limit",
            value=f"{100 * saturated:.0f}% of the time",
            detail="Share of the same 0.8 s with any servo at 95% or more of its limit.",
        ),
    ]
    if not math.isnan(min_margin):
        where = "outside" if min_margin < 0 else "inside"
        evidence.insert(
            1,
            Evidence(
                label="Balance point vs feet",
                value=f"{abs(min_margin):.1f} cm {where}",
                detail=(
                    f"Worst gap {'just after the shove' if pushed else 'before the fall'}, at "
                    f"{min_margin_time:.2f} s: where the body is heading if nothing changes, "
                    "measured against the outline of the feet."
                ),
            ),
        )

    if slide_median > SLIP_MEDIAN_MPS:
        cause: Cause = "slipped"
        cause_text = (
            f"The feet slid on the floor (median {slide_median:.2f} m/s while falling) at "
            f"{scenario.grip:g}× normal grip, so they could not push the body back under itself."
        )
    elif push_near:
        cause = "pushed"
        where = f"{abs(min_margin):.1f} cm outside" if min_margin < 0 else "to the edge of"
        cause_text = (
            f"A {scenario.push_n:g} N side shove at {scenario.push_at_s:.1f} s moved the balance "
            f"point {where} the feet, and no step caught it in time."
        )
    elif saturated >= 0.3:
        cause = "servos_saturated"
        cause_text = (
            f"The servos sat at their torque limit for {100 * saturated:.0f}% of the last "
            f"0.8 s ({scenario.battery_v:g} V battery), so they could not hold the pose."
        )
    else:
        cause = "unclear"
        cause_text = (
            "The recorded signals do not point to one cause: feet were planted, servos had "
            "headroom and nothing pushed the robot."
        )

    if recovered_time is not None:
        outcome: Literal["walked", "fell_and_got_up", "fell"] = "fell_and_got_up"
        verdict = f"Fell at {fall_time:.1f} s and was back on its feet at {recovered_time:.1f} s."
    else:
        outcome = "fell"
        if not policy.gets_up:
            stay = f" The {policy.in_sentence} has no get-up behaviour in our tests."
        elif cause == "slipped":
            stay = " This policy can get up on a normal floor, but the feet had no grip."
        else:
            stay = ""
        verdict = f"Fell at {fall_time:.1f} s and stayed down.{stay}"
    return RunAnalysis(
        outcome=outcome,
        verdict=verdict,
        fall_time_s=fall_time,
        tilt_start_s=tilt_start,
        recovered_time_s=recovered_time,
        distance_m=distance,
        peak_tilt_deg=float(tilt_deg.max()),
        cause=cause,
        cause_text=cause_text,
        min_balance_margin_cm=None if math.isnan(min_margin) else min_margin,
        min_balance_margin_s=min_margin_time,
        slide_median_mps=slide_median,
        saturated_fraction=saturated,
        evidence=evidence,
    )


def _recovered_time(run: RobotRun, fall_index: int) -> float | None:
    hold = int(_RECOVERED_HOLD_S * CONTROL_HZ)
    good = run.upright >= RECOVERED_UPRIGHT
    for index in range(fall_index, len(run) - hold + 1):
        if good[index : index + hold].all():
            return float(run.time[index])
    return None


def _nanmin(values: np.ndarray) -> float | None:
    if not np.isfinite(values).any():
        return None
    return float(np.nanmin(values))


def _argnanmin_time(values: np.ndarray, time: np.ndarray) -> float | None:
    if not np.isfinite(values).any():
        return None
    return float(time[int(np.nanargmin(values))])
