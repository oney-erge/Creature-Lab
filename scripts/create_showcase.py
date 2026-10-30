#!/usr/bin/env python3
"""Record the two guided experiments and build a local visual story package.

Requires the sim and export extras. Output goes into a new timestamped directory;
existing runs and media are never overwritten.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import imageio.v2 as imageio
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from creature_lab.backends.pybullet_backend import render_trace
from creature_lab.cli import _simulate
from creature_lab.diagnostics import summarize_episode
from creature_lab.editor.session import EditorSession
from creature_lab.reports import build_comparison, build_report_bundle
from creature_lab.reports_html import comparison_to_html
from creature_lab.runs import load_run, save_run
from creature_lab.schema import CreatureSpec, TaskSpec
from creature_lab.viewers.appearance import comparison_camera
from creature_lab.viewers.video_exporter import write_animation

FPS = 20
WIDTH, HEIGHT = 480, 360


def caption(frame: np.ndarray, text: str) -> np.ndarray:
    image = Image.fromarray(frame.copy()).convert("RGB")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, HEIGHT - 34, image.width, HEIGHT), fill=(20, 33, 52))
    try:
        font = ImageFont.truetype("arial.ttf", 16)
    except OSError:
        font = ImageFont.load_default()
    draw.text((10, HEIGHT - 28), text, fill=(255, 255, 255), font=font)
    return np.asarray(image)


def comparison_frames(before: list, after: list) -> list[np.ndarray]:
    count = max(len(before), len(after))
    return [
        np.concatenate(
            (
                caption(before[min(i, len(before) - 1)], "A: no-swing baseline (5 s loop)"),
                caption(after[min(i, len(after) - 1)], "B: packaged walking gait (5 s loop)"),
            ),
            axis=1,
        )
        for i in range(count)
    ]


def title_card(title: str, lines: list[str]) -> np.ndarray:
    image = Image.new("RGB", (WIDTH * 2, HEIGHT), (20, 33, 52))
    draw = ImageDraw.Draw(image)
    try:
        title_font = ImageFont.truetype("arial.ttf", 34)
        body_font = ImageFont.truetype("arial.ttf", 22)
    except OSError:
        title_font = body_font = ImageFont.load_default()
    draw.text((45, 45), title, font=title_font, fill=(255, 255, 255))
    for index, line in enumerate(lines):
        draw.text((48, 120 + index * 40), line, font=body_font, fill=(219, 230, 243))
    return np.asarray(image)


def write_walkthrough(path: Path, sequences: dict[str, list[np.ndarray]]) -> None:
    """Make a captioned walkthrough using recorded replays and instruction cards."""
    with imageio.get_writer(path, fps=FPS, macro_block_size=1) as writer:

        def card(title: str, lines: list[str], seconds: int = 8) -> None:
            frame = title_card(title, lines)
            for _ in range(seconds * FPS):
                writer.append_data(frame)

        def replay(name: str) -> None:
            for frame in sequences[name] * 2:
                writer.append_data(frame)

        card(
            "Creature Lab: a first investigation",
            [
                "A captioned guide with recorded simulation replays.",
                "The editor interface is described in text, not shown in this video.",
            ],
            seconds=10,
        )
        card(
            "1. Open Creature Lab",
            [
                "Use run.bat on Windows, run.command on macOS, or run.sh on Linux.",
                "The launcher prints the local editor address.",
            ],
        )
        card(
            "2. Run the humanoid",
            [
                "Choose Humanoid and Move forward.",
                "Click Run first simulation, then watch the replay and result.",
            ],
        )
        replay("humanoid")
        card(
            "3. Start an experiment",
            [
                "In Results, open Guided experiment and choose Humanoid.",
                "Click Run baseline experiment to save a no-swing run.",
            ],
        )
        card(
            "4. Read the result",
            [
                "Inspect forward progress and the detected failure patterns.",
                "Diagnosis suggestions are hypotheses to investigate.",
            ],
        )
        card(
            "5. Change the gait",
            [
                "Click Try walking gait and run again.",
                "The editor keeps the baseline for the comparison.",
            ],
        )
        replay("humanoid")
        card(
            "6. Compare the evidence",
            [
                "Click Compare with baseline for the synchronized 3D view.",
                "Check which settings and conditions changed.",
            ],
        )
        card(
            "7. Try Duckling",
            [
                "Choose Duckling in Guided experiment and repeat the two runs.",
                "Its walking gait is experimental and tuned for PyBullet.",
            ],
        )
        replay("duckling")
        card(
            "8. Try a gentle push",
            [
                "Click Try Duckling with a gentle push.",
                "It applies 10 N sideways for one physics step at two seconds.",
            ],
        )
        card(
            "9. Save and share",
            [
                "Download a comparison report, or export a GIF of a saved run.",
                "The report records conditions and reproducibility details.",
            ],
        )
        card(
            "Continue exploring",
            [
                "Return to Design, change one setting, and run again.",
                "Recorded examples are simulation evidence, not hardware qualification.",
            ],
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("outputs/showcase"))
    args = parser.parse_args()
    root = args.out / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    root.mkdir(parents=True, exist_ok=False)
    runs = root / "runs"
    session = EditorSession()
    results = {}
    sequences = {}
    for name in ("humanoid", "duckling"):
        session.load_guided_experiment(name)
        task = session.task
        variants = []
        for label in ("baseline", "walking"):
            if label == "walking":
                session.apply_guided_gait()
            creature = session.creature
            trace = _simulate(creature, task, controller="sinusoid", seed=0)
            summary = summarize_episode(trace, task, creature)
            run_dir = save_run(creature, trace, task=task, runs_dir=runs)
            variants.append((run_dir, creature, trace, summary))
            results[f"{name}_{label}"] = {
                "run": str(run_dir),
                "forward_m": summary.forward_displacement,
                "fell": summary.fell,
                "score": summary.final_score,
            }
        (path_a, creature_a, trace_a, summary_a), (path_b, creature_b, trace_b, summary_b) = (
            variants
        )
        distance, center = comparison_camera(trace_a, trace_b)
        frames_a = render_trace(
            creature_a,
            trace_a,
            task=task,
            width=WIDTH,
            height=HEIGHT,
            fps=FPS,
            camera_distance=distance,
            camera_center_xy=center,
        )
        frames_b = render_trace(
            creature_b,
            trace_b,
            task=task,
            width=WIDTH,
            height=HEIGHT,
            fps=FPS,
            camera_distance=distance,
            camera_center_xy=center,
        )
        comparison = comparison_frames(frames_a, frames_b)
        sequences[name] = comparison
        write_animation(comparison, root / f"{name}-comparison.gif", fps=FPS)
        a, ta, ca, task_a = build_report_bundle(path_a)
        b, tb, cb, task_b = build_report_bundle(path_b)
        comparison_data = build_comparison(a, b)
        trials = []
        for variant, original_path in (("baseline", path_a), ("walking", path_b)):
            original, original_task, _trace = load_run(original_path)
            if original_task is None:
                continue
            for mass_scale, friction_scale in ((0.95, 0.9), (1.05, 1.1), (0.9, 1.05), (1.1, 0.95)):
                creature_data = original.model_dump(mode="json")
                for part in creature_data["parts"]:
                    part["mass"] *= mass_scale
                task_data = original_task.model_dump(mode="json")
                task_data["terrain"]["friction"] *= friction_scale
                varied_creature = CreatureSpec.model_validate(creature_data)
                varied_task = TaskSpec.model_validate(task_data)
                varied_trace = _simulate(
                    varied_creature, varied_task, controller="sinusoid", seed=0
                )
                varied_summary = summarize_episode(varied_trace, varied_task, varied_creature)
                varied_run = save_run(
                    varied_creature, varied_trace, task=varied_task, runs_dir=runs
                )
                trials.append(
                    {
                        "variant": variant,
                        "purpose": (
                            "used to select Duckling gait"
                            if name == "duckling"
                            and (mass_scale, friction_scale) in ((0.95, 0.9), (1.05, 1.1))
                            else "additional condition"
                        ),
                        "mass_scale": mass_scale,
                        "friction_scale": friction_scale,
                        "forward_m": varied_summary.forward_displacement,
                        "fell": varied_summary.fell,
                        "run_id": varied_run.name,
                    }
                )
        comparison_data["exploratory_trials"] = trials
        results[f"{name}_trials"] = trials
        page = comparison_to_html(
            a,
            b,
            comparison_data,
            creature_a=ca,
            trace_a=ta,
            creature_b=cb,
            trace_b=tb,
            task_a=task_a,
            task_b=task_b,
        )
        (root / f"{name}-report.html").write_text(page, encoding="utf-8")
        print(
            f"{name}: {summary_a.forward_displacement:+.3f} m (fell={summary_a.fell}) -> "
            f"{summary_b.forward_displacement:+.3f} m (fell={summary_b.fell})",
            flush=True,
        )

    session.load_duckling_push_demo()
    push_trace = _simulate(session.creature, session.task, controller="sinusoid", seed=0)
    push_summary = summarize_episode(push_trace, session.task, session.creature)
    push_run = save_run(session.creature, push_trace, task=session.task, runs_dir=runs)
    push_frames = render_trace(
        session.creature, push_trace, task=session.task, width=WIDTH, height=HEIGHT, fps=FPS
    )
    push_frames = [caption(frame, "Duckling: 10 N push at 2 s, one step") for frame in push_frames]
    write_animation(push_frames, root / "duckling-push.gif", fps=FPS)
    with imageio.get_writer(root / "duckling-push.mp4", fps=FPS, macro_block_size=1) as writer:
        for frame in push_frames:
            writer.append_data(frame)
    results["duckling_push"] = {
        "run": str(push_run),
        "force_n": 10,
        "force_steps": 1,
        "push_time_s": 2.0,
        "fell": push_summary.fell,
        "forward_m": push_summary.forward_displacement,
    }
    print(f"duckling push: fell={push_summary.fell}; 10 N for one timestep", flush=True)

    # Exact recorded frames, replayed at their simulation timestamps.
    with imageio.get_writer(root / "duckling-short.mp4", fps=FPS, macro_block_size=1) as writer:
        for frame in sequences["duckling"] * 3:
            writer.append_data(frame)
    with imageio.get_writer(root / "creature-lab-story.mp4", fps=FPS, macro_block_size=1) as writer:

        def card(title: str, lines: list[str], seconds: int = 4) -> None:
            frame = title_card(title, lines)
            for _ in range(seconds * FPS):
                writer.append_data(frame)

        card(
            "Creature Lab",
            [
                "Build a creature. Run it. Understand what happened.",
                "Recorded PyBullet experiments - five simulated seconds each.",
            ],
        )
        for name in ("humanoid", "duckling"):
            before, after = results[f"{name}_baseline"], results[f"{name}_walking"]
            card(
                name.capitalize(),
                [
                    "Goal: move forward",
                    "A: motors held still",
                    "B: the same body with a packaged walking gait",
                ],
            )
            for frame in sequences[name] * 2:
                writer.append_data(frame)
            card(
                "What happened?",
                [
                    f"Baseline: {before['forward_m']:+.3f} m; fell: {before['fell']}",
                    f"Walking gait: {after['forward_m']:+.3f} m; fell: {after['fell']}",
                    "One recorded run per variant; inspect the report for conditions.",
                ],
            )
        card(
            "Try it yourself",
            [
                "Open Results > Guided experiment.",
                "Run a baseline, try the gait, and compare the saved runs.",
            ],
        )
    write_walkthrough(root / "humanoid-walkthrough.mp4", sequences)

    # An animated WebP is small enough for the README; the supplied --out directory
    # stays separate from tracked source until an author chooses an asset to use.
    hero = sequences["duckling"] + sequences["humanoid"]
    images = [Image.fromarray(frame).resize((720, 270)) for frame in hero[::2]]
    images[0].save(
        root / "showcase.webp",
        save_all=True,
        append_images=images[1:],
        duration=100,
        loop=0,
        quality=70,
        method=4,
    )
    Image.fromarray(hero[0]).save(root / "showcase-still.png")
    (root / "measurements.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(f"Saved recordings and reports in {root}", flush=True)


if __name__ == "__main__":
    main()
