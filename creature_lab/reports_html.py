"""Self-contained HTML rendering for run reports (Phase R1/R2).

Every function here returns a single string with inline CSS/SVG and no external
requests, so the result opens offline in a browser. No new dependencies: sparklines
and the root-path plot are hand-drawn SVG from the same pure series already produced
by ``viewers/overlays.py``; the optional GIF preview reuses the existing
``render_trace`` / ``write_animation`` path and embeds it as a ``data:`` URI.
"""

from __future__ import annotations

import base64
import html
import tempfile
from pathlib import Path
from typing import Any

from creature_lab.schema import CreatureSpec, EpisodeTrace, TaskSpec

_STYLE = """
:root { color-scheme: light dark; }
body {
  font-family: -apple-system, Segoe UI, Helvetica, Arial, sans-serif;
  max-width: 960px; margin: 2rem auto; padding: 0 1rem;
  line-height: 1.55; color: #172033; background: #f5f7fb;
}
@media (prefers-color-scheme: dark) {
  body { color: #e6e6e6; background: #14161a; }
  .card { background: #1d2026; border-color: #2c313a; }
  .bar-track { background: #2c313a; }
  th, td { border-color: #2c313a; }
}
h1 { font-size: 1.4rem; margin-bottom: 0.25rem; }
h2 {
  font-size: 1.05rem; margin-top: 2rem;
  border-bottom: 1px solid currentColor; padding-bottom: 0.25rem;
}
.card { background: #fff; border: 1px solid #d6deea; border-radius: 14px;
  padding: 1.2rem; margin: 0.75rem 0; }
.hero { background: #203a65; color: white; border-radius: 18px; padding: 1.4rem; }
.replays { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 1rem; }
.replays img, .card img { max-width: 100%; height: auto; border-radius: 8px; }
.meta { opacity: 0.75; font-size: 0.9rem; }
.bar-row { display: flex; align-items: center; gap: 0.5rem; margin: 0.3rem 0; }
.bar-label { width: 11rem; font-size: 0.85rem; flex-shrink: 0; }
.bar-track { flex: 1; background: #eee; border-radius: 4px; height: 0.9rem; overflow: hidden; }
.bar-fill { height: 100%; background: #3b82f6; }
.bar-fill.neg { background: #ef4444; }
.bar-value {
  width: 4.5rem; text-align: right; font-size: 0.85rem; font-variant-numeric: tabular-nums;
}
.sparkline-row { margin: 0.6rem 0; }
.sparkline-row .bar-label { display: block; margin-bottom: 0.2rem; }
table { border-collapse: collapse; width: 100%; font-size: 0.9rem; }
th, td { border: 1px solid #d0d0d0; padding: 0.35rem 0.6rem; text-align: right; }
th:first-child, td:first-child { text-align: left; }
code { font-size: 0.85rem; }
.warn { color: #b45309; }
.pattern { color: #b91c1c; }
.ok { color: #15803d; }
@media (prefers-color-scheme: dark) {
  .card { background: #1d2026; border-color: #445167; }
  .bar-track { background: #394352; }
  .warn { color: #f5c46f; }
  .pattern { color: #ff9b9b; }
  .ok { color: #86dba1; }
}
"""


def _escape(value: Any) -> str:
    return html.escape("-" if value is None else str(value))


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _svg_sparkline(values: list[float], *, width: int = 320, height: int = 56) -> str:
    if len(values) < 2:
        return "<p class='meta'>not enough samples</p>"
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1.0
    step = width / (len(values) - 1)
    points = " ".join(
        f"{i * step:.1f},{height - ((v - lo) / span) * (height - 4) - 2:.1f}"
        for i, v in enumerate(values)
    )
    return (
        f'<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="img">'
        f'<polyline points="{points}" fill="none" stroke="#3b82f6" stroke-width="1.6"/>'
        "</svg>"
    )


def _svg_top_down_paths(
    named_points: list[tuple[str, list[tuple[float, float, float]], str]],
    *,
    size: int = 360,
) -> str:
    """Overhead (X/Y) SVG plot of one or more root-path polylines."""
    all_xy = [(p[0], p[1]) for _, points, _ in named_points for p in points]
    if len(all_xy) < 2:
        return "<p class='meta'>not enough samples</p>"
    xs, ys = [p[0] for p in all_xy], [p[1] for p in all_xy]
    lo_x, hi_x = min(xs), max(xs)
    lo_y, hi_y = min(ys), max(ys)
    span = max(hi_x - lo_x, hi_y - lo_y) or 1.0
    margin = 10

    def project(x: float, y: float) -> tuple[float, float]:
        px = margin + (x - lo_x) / span * (size - 2 * margin)
        py = margin + (y - lo_y) / span * (size - 2 * margin)
        return px, py

    polylines = []
    legend = []
    for name, points, color in named_points:
        coords = " ".join(f"{px:.1f},{py:.1f}" for px, py in (project(p[0], p[1]) for p in points))
        polylines.append(
            f'<polyline points="{coords}" fill="none" stroke="{color}" stroke-width="2"/>'
        )
        start_px, start_py = project(points[0][0], points[0][1])
        polylines.append(f'<circle cx="{start_px:.1f}" cy="{start_py:.1f}" r="4" fill="{color}"/>')
        legend.append(f'<span style="color:{color}">&#9632;</span> {_escape(name)}')
    return (
        f'<svg viewBox="0 0 {size} {size}" width="{size}" height="{size}" role="img">'
        + "".join(polylines)
        + "</svg>"
        + f"<div class='meta'>{' &nbsp; '.join(legend)} "
        "(start marked with a dot; top-down X/Y)</div>"
    )


def _score_bar_html(component_scores: dict[str, float]) -> str:
    if not component_scores:
        return "<p class='meta'>No component score metadata recorded.</p>"
    peak = max(abs(v) for v in component_scores.values()) or 1.0
    rows = []
    for name, value in component_scores.items():
        width = min(abs(value) / peak, 1.0) * 100
        cls = "neg" if value < 0 else ""
        rows.append(
            "<div class='bar-row'>"
            f"<span class='bar-label'>{_escape(name)}</span>"
            f"<span class='bar-track'>"
            f"<span class='bar-fill {cls}' style='width:{width:.1f}%'></span></span>"
            f"<span class='bar-value'>{_fmt(value)}</span>"
            "</div>"
        )
    return "".join(rows)


def _gif_data_uri(
    creature: CreatureSpec,
    trace: EpisodeTrace,
    *,
    task: TaskSpec | None = None,
    width: int,
    height: int,
    camera_distance: float | None = None,
    camera_center_xy: tuple[float, float] | None = None,
) -> str | None:
    """Best-effort inline GIF preview; returns None if the sim/export extras are absent."""
    try:
        from creature_lab.backends.pybullet_backend import render_trace
        from creature_lab.viewers.video_exporter import write_animation
    except ImportError:
        return None
    frames = render_trace(
        creature,
        trace,
        task=task,
        width=width,
        height=height,
        fps=30.0,
        camera_distance=camera_distance,
        camera_center_xy=camera_center_xy,
    )
    with tempfile.TemporaryDirectory() as tmp:
        gif_path = write_animation(frames, Path(tmp) / "preview.gif")
        encoded = base64.b64encode(gif_path.read_bytes()).decode("ascii")
    return f"data:image/gif;base64,{encoded}"


def _diagnosis_html(diagnosis: dict[str, Any]) -> str:
    patterns = diagnosis.get("patterns") or []
    suggestions = diagnosis.get("suggestions") or []
    if not patterns:
        return "<p class='ok'>No failure patterns detected.</p>"
    items = []
    for index, pattern in enumerate(patterns):
        suggestion = suggestions[index] if index < len(suggestions) else ""
        suffix = f" &mdash; {_escape(suggestion)}" if suggestion else ""
        items.append(f"<li class='pattern'>{_escape(pattern)}{suffix}</li>")
    return "<ul>" + "".join(items) + "</ul>"


def _reproducibility_html(repro: dict[str, Any]) -> str:
    rows = [
        (
            "Schema / lab version",
            f"{_fmt(repro.get('schema_version'))} / {_fmt(repro.get('lab_version'))}",
        ),
        ("Backend", f"{_fmt(repro.get('backend'))} {_fmt(repro.get('backend_version'))}"),
        ("Timestep", _fmt(repro.get("timestep"))),
        ("Seed", _fmt(repro.get("seed"))),
        ("Creature hash", _fmt(repro.get("creature_hash"))),
        ("Task hash", _fmt(repro.get("task_hash"))),
    ]
    body = "".join(f"<tr><td>{_escape(k)}</td><td>{_escape(v)}</td></tr>" for k, v in rows)
    command = repro.get("command")
    command_html = f"<pre><code>{_escape(command)}</code></pre>" if command else ""
    return f"<table>{body}</table>{command_html}"


def report_to_html(
    report: dict[str, Any],
    trace: EpisodeTrace,
    creature: CreatureSpec | None = None,
    task: TaskSpec | None = None,
    *,
    embed_media: bool = True,
    media_width: int = 320,
    media_height: int = 240,
) -> str:
    """Render a ``build_report`` dict as a single self-contained HTML page.

    ``task`` (when its terrain is non-flat) makes the embedded GIF preview draw the
    actual terrain shape instead of a flat floor.
    """
    creature_info, task_info, backend = report["creature"], report["task"], report["backend"]
    summary, diagnosis = report["summary"], report["diagnosis"]

    gif_html = ""
    if embed_media and creature is not None:
        data_uri = _gif_data_uri(creature, trace, task=task, width=media_width, height=media_height)
        if data_uri:
            gif_html = f"<div class='card'><img src='{data_uri}' alt='episode replay' /></div>"

    sparklines = ""
    if creature is not None:
        from creature_lab.viewers.overlays import (
            center_of_mass_trail,
            joint_energy_series,
            root_path,
        )

        com_trail = center_of_mass_trail(creature, trace)
        heights = [point[2] for point in com_trail]
        energy = joint_energy_series(trace)
        scores = [frame.score for frame in trace.frames]
        sparklines = (
            "<div class='sparkline-row'><span class='bar-label'>CoM height (m)</span>"
            f"{_svg_sparkline(heights)}</div>"
            "<div class='sparkline-row'><span class='bar-label'>Score over time</span>"
            f"{_svg_sparkline(scores)}</div>"
            "<div class='sparkline-row'><span class='bar-label'>Joint energy (per-frame)</span>"
            f"{_svg_sparkline(energy)}</div>"
        )
        path_svg = _svg_top_down_paths(
            [(creature_info["name"], root_path(creature, trace), "#3b82f6")]
        )
    else:
        path_svg = "<p class='meta'>No creature.json available; root path not rendered.</p>"

    warnings_html = (
        "".join(f"<li class='warn'>{_escape(w)}</li>" for w in report.get("warnings") or [])
        or "<li class='ok'>none</li>"
    )

    improvement = report.get("improvement")
    improvement_html = "<p class='meta'>No evolve/ask lineage recorded for this run.</p>"
    if improvement:
        if improvement["kind"] == "evolve":
            improvement_html = (
                f"<p>Evolve: {_escape(improvement.get('strategy'))} strategy, "
                f"{_fmt(improvement.get('attempts'))} attempt(s), "
                f"best score {_fmt(improvement.get('best_score'))}.</p>"
            )
        else:
            improvement_html = (
                f"<p>Ask: {_fmt(improvement.get('attempts'))} attempt(s), "
                f"{_fmt(improvement.get('accepted'))} accepted, "
                f"{_fmt(improvement.get('invalid'))} invalid.</p>"
            )
            if improvement.get("goal"):
                improvement_html += f"<p class='meta'>Goal: {_escape(improvement['goal'])}</p>"

    robustness = report.get("robustness")
    robustness_section = ""
    if robustness:
        robustness_section = f"""<h2>Robustness</h2>
<p>{len(robustness["trials"])} seeded trial(s) with small mass/friction jitter around the
baseline spec.</p>
<p>
  Score: mean {_fmt(robustness["mean_score"])}, std {_fmt(robustness["std_score"])},
  range [{_fmt(robustness["min_score"])}, {_fmt(robustness["max_score"])}] &middot;
  Fail rate: {robustness["fail_rate"]:.0%}
</p>
"""

    sim2sim = report.get("sim2sim")
    sim2sim_section = ""
    if sim2sim:
        gap_class = "ok" if sim2sim["score_gap"] < 0.1 else "warn"
        sim2sim_section = f"""<h2>Sim2Sim</h2>
<p>
  PyBullet score: {_fmt(sim2sim["pybullet"]["score"])} &middot;
  MuJoCo score: {_fmt(sim2sim["mujoco"]["score"])} &middot;
  <span class="{gap_class}">gap: {_fmt(sim2sim["score_gap"])}</span>
</p>
<p>Mean root-position divergence: {_fmt(sim2sim["mean_root_divergence"])} m.</p>
"""

    artifacts_html = "".join(
        f"<li><code>{_escape(name)}</code>: <code>{_escape(value)}</code></li>"
        for name, value in report["artifacts"].items()
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>Creature Lab report: {_escape(report["run_id"])}</title>
<style>{_STYLE}</style>
</head>
<body>
<div class="hero"><h1>Creature Lab Run Report</h1>
<p class="meta">
  Creature <strong>{_escape(creature_info["name"])}</strong>
  (<code>{_escape(creature_info["hash"])}</code>) on task
  <strong>{_escape(task_info["name"])}</strong> (<code>{_escape(task_info["hash"])}</code>)
  &middot; terrain: {_escape(task_info.get("terrain"))}
  &middot; backend {_escape(backend["name"])} {_escape(backend["version"])}
</p>
</div>
<div class="card">
  <strong>Score: {_fmt(report["score"])}</strong>
  &middot; {summary["frame_count"]} frames over {_fmt(summary["duration"])}s
  <p>Forward: {_fmt(summary["forward_displacement"])} m &middot;
  Fell: {_fmt(summary.get("fell"))}</p>
</div>
{gif_html}
<h2>Score breakdown</h2>
{_score_bar_html(summary.get("component_scores") or {})}

<h2>Signals</h2>
{sparklines}
<p>
  Net displacement: {_fmt(summary["net_displacement"])} m &middot;
  Forward displacement: {_fmt(summary["forward_displacement"])} m &middot;
  Target progress: {_fmt(summary.get("target_progress"))} &middot;
  Fell: {_fmt(summary.get("fell"))}
</p>

<h2>Root path (top-down)</h2>
{path_svg}

<h2>Diagnostics</h2>
{_diagnosis_html(diagnosis)}

<h2>Warnings</h2>
<ul>{warnings_html}</ul>

<h2>Improvement</h2>
{improvement_html}

{robustness_section}
{sim2sim_section}
<h2>Reproducibility</h2>
{_reproducibility_html(report.get("reproducibility") or {})}

<h2>Artifacts</h2>
<ul>{artifacts_html}</ul>
</body>
</html>
"""


def gallery_card_html(
    name: str,
    task_name: str,
    baseline: dict[str, Any] | None,
    current_score: float | None,
    gif_name: str | None,
    failure_note: str,
) -> str:
    """One zoo creature's card: baseline vs. current score, and its replay GIF."""
    expected = baseline.get("best_score") if baseline else None
    delta_html = ""
    if expected is not None and current_score is not None:
        delta = current_score - expected
        cls = "ok" if delta >= 0 else "pattern"
        sign = "+" if delta >= 0 else ""
        delta_html = f"<span class='{cls}'>({sign}{delta:.4f} vs. baseline)</span>"
    media_html = (
        f"<img src='{_escape(gif_name)}' alt='{_escape(name)} replay' />" if gif_name else ""
    )
    return f"""<div class="card">
  <h2>{_escape(name)}</h2>
  {media_html}
  <p>Default task: <code>{_escape(task_name)}</code></p>
  <p>Baseline score: {_fmt(expected)} &middot; Current score: {_fmt(current_score)} {delta_html}</p>
  <p class="meta">{_escape(failure_note)}</p>
  <p><code>uv run creature-lab zoo run {_escape(name)}</code></p>
</div>"""


def gallery_index_html(cards: list[str]) -> str:
    """Wrap per-creature ``gallery_card_html`` fragments into one gallery page."""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>Creature Zoo Gallery</title>
<style>{_STYLE}</style>
</head>
<body>
<h1>Creature Zoo Gallery</h1>
{"".join(cards)}
</body>
</html>
"""


def comparison_to_html(
    report_a: dict[str, Any],
    report_b: dict[str, Any],
    comparison: dict[str, Any],
    *,
    creature_a: CreatureSpec | None = None,
    trace_a: EpisodeTrace | None = None,
    creature_b: CreatureSpec | None = None,
    trace_b: EpisodeTrace | None = None,
    task_a: TaskSpec | None = None,
    task_b: TaskSpec | None = None,
    embed_media: bool = True,
) -> str:
    """Render a before/after comparison between two reports built by ``build_report``."""
    path_svg = "<p class='meta'>No creature.json available for one or both runs.</p>"
    if (
        creature_a is not None
        and trace_a is not None
        and creature_b is not None
        and trace_b is not None
    ):
        from creature_lab.viewers.overlays import root_path

        path_svg = _svg_top_down_paths(
            [
                (report_a["run_id"], root_path(creature_a, trace_a), "#3b82f6"),
                (report_b["run_id"], root_path(creature_b, trace_b), "#ef4444"),
            ]
        )

    signal_rows = "".join(
        f"<tr><td>{_escape(key)}</td><td>{_fmt(v['a'])}</td><td>{_fmt(v['b'])}</td>"
        f"<td>{'+' if v['delta'] >= 0 else ''}{_fmt(v['delta'])}</td></tr>"
        for key, v in comparison["signals"].items()
    )
    delta = comparison["score_delta"]
    differences = comparison.get("conditions_changed_or_unknown", [])
    delta_class = "meta" if differences else "ok" if delta >= 0 else "pattern"
    conditions = _escape(", ".join(differences) if differences else "none detected")
    title = f"{comparison['run_a']} vs {comparison['run_b']}"
    changes_html = ""
    if creature_a is not None and creature_b is not None:
        motors_a = {motor.joint: motor for motor in creature_a.motors}
        motors_b = {motor.joint: motor for motor in creature_b.motors}
        rows = []
        for joint in sorted(motors_a.keys() & motors_b.keys()):
            left, right = motors_a[joint], motors_b[joint]
            if (left.amplitude, left.frequency, left.phase, left.offset) == (
                right.amplitude,
                right.frequency,
                right.phase,
                right.offset,
            ):
                continue
            rows.append(
                f"<tr><td>{_escape(joint)}</td><td>{_fmt(left.amplitude)} → "
                f"{_fmt(right.amplitude)}</td><td>{_fmt(left.frequency)} → "
                f"{_fmt(right.frequency)}</td><td>{_fmt(left.phase)} → {_fmt(right.phase)}</td>"
                f"<td>{_fmt(left.offset)} → {_fmt(right.offset)}</td></tr>"
            )
        if rows:
            changes_html = (
                "<h2>What changed in the body files</h2><p>Embedded motor settings are shown; "
                "an external controller may override them. Inspect the saved controller snapshots."
                "</p><table><tr><th>joint</th><th>range</th><th>frequency</th>"
                "<th>phase</th><th>offset</th></tr>" + "".join(rows) + "</table>"
            )
    trials = comparison.get("exploratory_trials") or []
    trials_html = ""
    if trials:
        trial_rows = "".join(
            f"<tr><td>{_escape(row['variant'])}</td>"
            f"<td>{_escape(row.get('purpose', 'additional'))}</td>"
            f"<td>{_fmt(row['mass_scale'])}</td>"
            f"<td>{_fmt(row['friction_scale'])}</td><td>{_fmt(row['forward_m'])}</td>"
            f"<td>{_fmt(row['fell'])}</td><td>{_escape(row['run_id'])}</td></tr>"
            for row in trials
        )
        trials_html = (
            "<h2>Additional conditions</h2><p>Exploratory reruns with changed mass and friction; "
            "these are not a statistical reliability estimate.</p><table>"
            "<tr><th>variant</th><th>condition</th><th>mass scale</th><th>friction scale</th>"
            "<th>forward (m)</th><th>fell</th><th>run</th></tr>"
            f"{trial_rows}</table>"
        )
    replay_html = ""
    if embed_media and creature_a and trace_a and creature_b and trace_b:
        from creature_lab.viewers.appearance import comparison_camera

        distance, center = comparison_camera(trace_a, trace_b)
        gif_a = _gif_data_uri(
            creature_a,
            trace_a,
            task=task_a,
            width=400,
            height=300,
            camera_distance=distance,
            camera_center_xy=center,
        )
        gif_b = _gif_data_uri(
            creature_b,
            trace_b,
            task=task_b,
            width=400,
            height=300,
            camera_distance=distance,
            camera_center_xy=center,
        )
        if gif_a and gif_b:
            replay_html = (
                "<h2>Watch the runs</h2><div class='replays'>"
                "<div class='card'><strong>A · Baseline</strong>"
                f"<img src='{gif_a}' alt='Run A replay'></div>"
                "<div class='card'><strong>B · Comparison</strong>"
                f"<img src='{gif_b}' alt='Run B replay'></div>"
                "</div><p class='meta'>Both use the same scale and horizontal camera; "
                "the camera follows height. These previews loop independently. "
                "Use the editor's side-by-side view for a synchronized timeline.</p>"
            )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>Creature Lab comparison: {_escape(title)}</title>
<style>{_STYLE}</style>
</head>
<body>
<div class="hero"><h1>Run Comparison</h1>
<p class="meta">
  <span style="color:#3b82f6">&#9632;</span> A: {_escape(comparison["run_a"])}
  (score {_fmt(comparison["score_a"])}) &nbsp;vs&nbsp;
  <span style="color:#ef4444">&#9632;</span> B: {_escape(comparison["run_b"])}
  (score {_fmt(comparison["score_b"])})
</p>
</div>
<div class="card">
  <strong class="{delta_class}">Score delta: {"+" if delta >= 0 else ""}{_fmt(delta)}</strong>
  <p>Changed or unknown: {conditions}. Compare scores only when task, backend, and evaluation
  conditions are compatible.</p>
</div>
{replay_html}
{changes_html}

<h2>Diagnosis</h2>
<p>These rule-based signals suggest what to inspect; they do not establish causation.</p>
<div class="replays">
  <div class="card"><strong>A · Baseline</strong>
    {_diagnosis_html(report_a.get("diagnosis") or {})}</div>
  <div class="card"><strong>B · Comparison</strong>
    {_diagnosis_html(report_b.get("diagnosis") or {})}</div>
</div>

<h2>Root path (top-down, overlaid)</h2>
{path_svg}

<h2>Signal deltas</h2>
<table>
<tr><th>signal</th><th>A</th><th>B</th><th>delta</th></tr>
{signal_rows}
</table>
{trials_html}
</body>
</html>
"""


_ARCHIVE_STYLE = """
.archive-grid { border-collapse: collapse; }
.archive-cell {
  text-align: center; padding: 6px; border-radius: 4px; color: #111;
  font-size: 0.8rem; min-width: 2.5rem;
}
.archive-cell img { display: block; max-width: 120px; margin: 0 auto 2px auto; }
.archive-empty { background: transparent; }
"""


def _archive_grid_html(archive: dict[str, dict], cell_gifs: dict[str, str]) -> str:
    """The heatmap ``<table>`` fragment only (used by ``archive_to_html``)."""
    if not archive:
        return "<p class='meta'>Archive is empty.</p>"

    cells: dict[tuple[int, int], dict] = {}
    max_row = max_col = 0
    for key, entry in archive.items():
        row_str, col_str = key.split(",")
        row, col = int(row_str), int(col_str)
        cells[(row, col)] = entry
        max_row, max_col = max(max_row, row), max(max_col, col)

    scores = [entry["score"] for entry in archive.values()]
    lo, hi = min(scores), max(scores)
    span = max(hi - lo, 1e-9)

    def cell_html(row: int, col: int) -> str:
        entry = cells.get((row, col))
        if entry is None:
            return "<td class='archive-empty'>&nbsp;</td>"
        hue = 120 * (entry["score"] - lo) / span  # red (low) -> green (high)
        key = f"{row},{col}"
        gif = cell_gifs.get(key)
        media = f"<img src='{_escape(gif)}' alt='cell {key}' />" if gif else ""
        return (
            f"<td class='archive-cell' style='background:hsl({hue:.0f}, 65%, 45%)' "
            f"title='cell {key}'>{media}<div>{entry['score']:.3f}</div></td>"
        )

    rows_html = "".join(
        f"<tr>{''.join(cell_html(row, col) for col in range(max_col + 1))}</tr>"
        for row in range(max_row + 1)
    )
    return f"<table class='archive-grid'><tbody>{rows_html}</tbody></table>"


def archive_to_html(archive: dict[str, dict], *, cell_gifs: dict[str, str] | None = None) -> str:
    """Render a MAP-Elites ``archive.json`` as a scored heatmap, one page.

    Each filled cell is colored by its score (red=low, green=high) and shows the score
    value; pass ``cell_gifs`` (cell key -> relative GIF path) to also show a per-cell
    replay thumbnail, e.g. from ``archive show --html --task``.
    """
    grid_html = _archive_grid_html(archive, cell_gifs or {})
    filled = len(archive)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>Creature Lab MAP-Elites archive</title>
<style>{_STYLE}{_ARCHIVE_STYLE}</style>
</head>
<body>
<h1>MAP-Elites Archive</h1>
<p class="meta">{filled} filled behaviour cell(s). Each cell is the best creature found
for its (forward displacement, gait symmetry) niche.</p>
{grid_html}
</body>
</html>
"""
