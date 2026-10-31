"""A self-contained HTML report for one or more robot check-ups."""

from __future__ import annotations

import html
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from creature_lab.io_utils import atomic_write_text
from creature_lab.robots.analysis import FALL_UPRIGHT, analyze
from creature_lab.robots.catalog import robot_info
from creature_lab.robots.checkup import Checkup, ConditionResult, ShoveRow
from creature_lab.robots.types import RobotRun

_CSS = """
:root{--bg:#f6f7fb;--card:#fff;--ink:#101828;--muted:#5b667a;--line:#e3e7ef;--up:#1aa38b;
--got:#f2b705;--down:#e5484d;--accent:#f26a1b;--soft:#eef1f7}
@media (prefers-color-scheme:dark){:root{--bg:#0b1020;--card:#121a2f;--ink:#eef2fa;--muted:#9aa8c4;
--line:#223055;--soft:#18223c}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:16px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1040px;margin:0 auto;padding:32px 20px 72px}
h1{font-size:clamp(1.9rem,4vw,2.7rem);line-height:1.15;margin:.2em 0 .3em}
h2{font-size:1.35rem;margin:2.2em 0 .6em}h3{font-size:1.05rem;margin:0 0 .3em}
.kicker{color:var(--accent);font-weight:700;letter-spacing:.08em;text-transform:uppercase;font-size:.8rem}
.lede{font-size:1.15rem;color:var(--muted);max-width:46em}
.grid{display:grid;gap:14px;grid-template-columns:repeat(auto-fit,minmax(220px,1fr))}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:18px 20px}
.big{font-size:2rem;font-weight:800;line-height:1.1}.muted{color:var(--muted)}
.pass{color:var(--up);font-weight:700}.fail{color:var(--down);font-weight:700}
table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:10px 8px;
border-bottom:1px solid var(--line);vertical-align:top}th{font-size:.82rem;color:var(--muted);
text-transform:uppercase;letter-spacing:.05em}
.dots{display:flex;gap:4px;align-items:center}.dot{width:15px;height:15px;border-radius:4px}
.up{background:var(--up)}.got{background:var(--got)}.down{background:var(--down)}
.legend{display:flex;gap:18px;flex-wrap:wrap;margin:.4em 0 1em;color:var(--muted);font-size:.9rem}
.legend span{display:inline-flex;align-items:center;gap:6px}
.chips{display:flex;flex-wrap:wrap;gap:8px;margin:.6em 0}
.chip{background:var(--soft);border-radius:999px;padding:4px 12px;font-size:.88rem}
.chip.bad{background:rgba(229,72,77,.15);color:var(--down);font-weight:600}
.chip.ok{background:rgba(26,163,139,.15);color:var(--up);font-weight:600}
video,svg{max-width:100%}video{border-radius:16px;width:100%;background:#000}
code,pre{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:.9rem}
pre{background:var(--soft);border-radius:12px;padding:14px;overflow:auto}
footer{margin-top:3em;color:var(--muted);font-size:.88rem}
.cols{display:grid;gap:14px;grid-template-columns:repeat(auto-fit,minmax(300px,1fr))}
"""


@dataclass
class PolicyResult:
    checkup: Checkup
    folder: Path


def _e(value) -> str:
    return html.escape(str(value))


def limit_text(limit: float | None, checkup: Checkup) -> str:
    """A shove limit in words: 'none', '2 N', or 'all tested' when no strength broke it."""
    tested = checkup.shoves[-1].force_n
    if limit is None:
        return f"none (even {checkup.shoves[0].force_n:g} N)"
    if limit == tested:
        return f"all tested (to {tested:g} N)"
    return f"up to {limit:g} N"


def _dots(row: ShoveRow) -> str:
    cells = ["up"] * row.stayed_up + ["got"] * row.got_up + ["down"] * row.stayed_down
    label = (
        f"{row.stayed_up} stayed up, {row.got_up} fell and got up, {row.stayed_down} stayed down"
    )
    dots = "".join(f'<span class="dot {kind}"></span>' for kind in cells)
    return f'<div class="dots" role="img" aria-label="{_e(label)}">{dots}</div>'


def _lean_svg(run: RobotRun, width: int = 460, height: int = 150) -> str:
    """Lean angle over time with the shove band and the fall line."""
    pad_l, pad_r, pad_t, pad_b = 36, 8, 10, 24
    plot_w, plot_h = width - pad_l - pad_r, height - pad_t - pad_b
    tilt = np.degrees(np.arccos(np.clip(run.upright, -1, 1)))
    duration = float(run.time[-1])

    def px(t):
        return pad_l + plot_w * t / duration

    def py(deg):
        return pad_t + plot_h * (1 - min(deg, 100) / 100)

    points = " ".join(f"{px(t):.1f},{py(d):.1f}" for t, d in zip(run.time, tilt, strict=True))
    fall_y = py(np.degrees(np.arccos(FALL_UPRIGHT)))
    parts = [
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Lean angle over time">',
        f'<line x1="{pad_l}" y1="{fall_y:.1f}" x2="{width - pad_r}" y2="{fall_y:.1f}" '
        'stroke="var(--down)" stroke-dasharray="4 4" opacity=".7"/>',
        f'<text x="{width - pad_r}" y="{fall_y - 4:.1f}" text-anchor="end" font-size="11" '
        'fill="var(--down)">fall (60°)</text>',
    ]
    scenario = run.scenario
    if scenario.push_n > 0:
        x0, x1 = px(scenario.push_at_s), px(scenario.push_at_s + scenario.push_for_s)
        parts.append(
            f'<rect x="{x0:.1f}" y="{pad_t}" width="{max(x1 - x0, 3):.1f}" height="{plot_h}" '
            'fill="var(--accent)" opacity=".35"/>'
            f'<text x="{x0 + 4:.1f}" y="{pad_t + 12}" font-size="11" fill="var(--accent)">'
            f"shove</text>"
        )
    parts.append(
        f'<polyline points="{points}" fill="none" stroke="var(--up)" stroke-width="2.2" '
        'stroke-linejoin="round"/>'
    )
    for deg in (0, 50, 100):
        parts.append(
            f'<text x="{pad_l - 6}" y="{py(deg) + 4:.1f}" text-anchor="end" font-size="11" '
            f'fill="var(--muted)">{deg}°</text>'
        )
    for sec in range(0, int(duration) + 1, 2):
        parts.append(
            f'<text x="{px(sec):.1f}" y="{height - 6}" text-anchor="middle" font-size="11" '
            f'fill="var(--muted)">{sec} s</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def _headline(results: list[PolicyResult]) -> tuple[str, str]:
    info = robot_info(results[0].checkup.robot)
    if len(results) == 2:
        first, second = results[0].checkup, results[1].checkup
        total = sum(r.total for r in first.shoves)
        down_first = sum(r.stayed_down for r in first.shoves)
        down_second = sum(r.stayed_down for r in second.shoves)
        title_first = info.policy(first.policy).title.lower()
        title_second = info.policy(second.policy).title.lower()
        return (
            f"{info.title}: {down_first} of {total} shoves leave it on the floor with the "
            f"{title_first}, {down_second} with the {title_second}.",
            "Each shove is a sideways push at a different moment of the stride. Falling is not "
            "the failure; staying down is.",
        )
    only = results[0].checkup
    limit = only.never_falls_up_to_n
    sentence = (
        f"{info.title} never falls up to a {limit:g} N shove."
        if limit
        else f"{info.title} falls even at the lightest shove tested."
    )
    return sentence, "Each shove is a sideways push at a different moment of the stride."


def _shove_section(results: list[PolicyResult]) -> str:
    info = robot_info(results[0].checkup.robot)
    head = "".join(f"<th>{_e(info.policy(r.checkup.policy).title)}</th>" for r in results)
    rows = []
    for index, row in enumerate(results[0].checkup.shoves):
        cells = "".join(f"<td>{_dots(r.checkup.shoves[index])}</td>" for r in results)
        rows.append(f"<tr><td><strong>{row.force_n:g} N</strong></td>{cells}</tr>")
    return f"""
<h2>How hard a shove can it take?</h2>
<p class="muted">{results[0].checkup.shoves[0].total} shoves per strength, each at a different
moment of the stride, alternating sides.</p>
<div class="legend"><span><i class="dot up"></i> stayed up</span>
<span><i class="dot got"></i> fell, then got back up</span>
<span><i class="dot down"></i> fell and stayed down</span></div>
<div class="card"><table><thead><tr><th>Shove</th>{head}</tr></thead>
<tbody>{"".join(rows)}</tbody></table></div>"""


def _fall_card(result: PolicyResult, row: ShoveRow) -> str:
    info = robot_info(result.checkup.robot)
    policy = info.policy(result.checkup.policy)
    run = RobotRun.read(result.folder / "runs" / row.example_fall_run)
    analysis = analyze(run)
    chips = "".join(
        f'<span class="chip {"bad" if _blames(analysis.cause, item.label) else "ok"}">'
        f"{_e(item.label)}: {_e(item.value)}</span>"
        for item in analysis.evidence[1:]
    )
    return f"""<div class="card"><h3>{_e(policy.title)} at {row.force_n:g} N</h3>
<p><strong>{_e(analysis.verdict)}</strong></p>
<p class="muted">{_e(analysis.cause_text or "")}</p>
<div class="chips">{chips}</div>{_lean_svg(run)}</div>"""


def _blames(cause: str | None, label: str) -> bool:
    return (
        (cause == "pushed" and label == "Balance point vs feet")
        or (cause == "slipped" and label == "Feet slide on the floor")
        or (cause == "servos_saturated" and label == "Servos at their torque limit")
    )


def _fall_section(results: list[PolicyResult], story_force: float | None) -> str:
    cards = []
    for result in results:
        rows = [r for r in result.checkup.shoves if r.example_fall_run]
        if not rows:
            continue
        chosen = next((r for r in rows if r.force_n == story_force), rows[0])
        cards.append(_fall_card(result, chosen))
    if not cards:
        return ""
    return (
        "<h2>Why it fell</h2><p class='muted'>The first fall at each strength, with the "
        "recorded evidence. Red marks the signal that explains it.</p>"
        f"<div class='cols'>{''.join(cards)}</div>"
    )


def _condition_row(condition: ConditionResult) -> str:
    status = (
        '<span class="pass">pass</span>' if condition.passed else '<span class="fail">fail</span>'
    )
    return (
        f"<tr><td>{_e(condition.label)}</td><td>{status}</td>"
        f"<td>{condition.relative_distance:.0%}</td><td>{_e(condition.analysis.verdict)}</td></tr>"
    )


def _condition_section(results: list[PolicyResult]) -> str:
    info = robot_info(results[0].checkup.robot)
    blocks = []
    for result in results:
        if not result.checkup.conditions:
            continue
        rows = "".join(_condition_row(c) for c in result.checkup.conditions)
        title = info.policy(result.checkup.policy).title
        blocks.append(
            f"<div class='card'><h3>{_e(title)}</h3><table><thead><tr><th>Condition</th>"
            f"<th>Result</th><th>Distance vs normal</th><th>What happened</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></div>"
        )
    return "<h2>Bad floors, weak batteries and heavy loads</h2>" + "".join(blocks)


def _provenance_section(results: list[PolicyResult]) -> str:
    rows = []
    for result in results:
        run = RobotRun.read(result.folder / "runs" / result.checkup.baseline_run)
        for key in ("creature_lab", "mujoco", "policy_sha256", "servo_model", "scenario_hash"):
            if key in run.provenance:
                rows.append(
                    f"<tr><td>{_e(result.checkup.policy)}</td><td>{_e(key)}</td>"
                    f"<td><code>{_e(run.provenance[key])}</code></td></tr>"
                )
    command = f"creature-lab robots checkup {results[0].checkup.robot.replace('_', '-')}"
    return f"""<h2>Reproduce it</h2>
<pre>{_e(command)}</pre>
<p class="muted">Runs are deterministic: the same files and versions give the same numbers.
Each saved run keeps its scenario, so any row above can be replayed.</p>
<div class="card"><table><thead><tr><th>Policy</th><th>Item</th><th>Value</th></tr></thead>
<tbody>{"".join(rows)}</tbody></table></div>"""


def write_report(
    out_dir: Path,
    results: list[PolicyResult],
    *,
    film: str | None = None,
    story_force: float | None = 3.0,
) -> Path:
    """Write ``report.html`` into ``out_dir`` and return its path."""
    info = robot_info(results[0].checkup.robot)
    # The policy that stays down comes first, so the page reads as before and after.
    results = sorted(results, key=lambda r: info.policy(r.checkup.policy).gets_up)
    headline, subline = _headline(results)
    kpis = []
    for result in results:
        checkup = result.checkup
        title = info.policy(checkup.policy).title
        kpis.append(
            f"""<div class="card"><div class="muted">{_e(title)}</div>
<div class="big">{limit_text(checkup.never_falls_up_to_n, checkup)}</div>
<div class="muted">shoves it never falls to</div>
<div class="big" style="margin-top:.5em">{
                limit_text(checkup.never_stays_down_up_to_n, checkup)
            }</div>
<div class="muted">shoves it always ends up standing after</div></div>"""
        )
    video = (
        f'<h2>The check-up in 60 seconds</h2><video controls preload="metadata" src="{_e(film)}">'
        "</video>"
        if film
        else ""
    )
    body = f"""<main>
<div class="kicker">Creature Lab robot check-up</div>
<h1>{_e(headline)}</h1><p class="lede">{_e(subline)}</p>
<div class="grid" style="margin-top:1.2em">{"".join(kpis)}</div>
{video}{_shove_section(results)}{_fall_section(results, story_force)}
{_condition_section(results)}{_provenance_section(results)}
<footer><p>{_e(info.credit)}.</p><p>{_e(info.license_notice)}</p>
<p><strong>Simulation, not hardware.</strong> These results describe the simulated robot and
policy only.</p></footer></main>"""
    page = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{_e(info.title)} check-up</title><style>{_CSS}</style></head>"
        f"<body>{body}</body></html>"
    )
    path = Path(out_dir) / "report.html"
    atomic_write_text(path, page)
    return path
