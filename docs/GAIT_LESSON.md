# Compare two quadruped controllers

Change one part of an experiment: keep the quadruped, crawl-forward task,
physics backend, and seed fixed, and compare its curated gait with the simpler
sinusoid controller. This uses the packaged zoo, so no model or API key is
needed. Install the `sim` extra first, or run the root launcher once.

From a checkout, run:

```bash
uv run creature-lab zoo run quadruped --controller curated --seed 7 --runs-dir runs/gait-lesson
uv run creature-lab zoo run quadruped --controller sinusoid --seed 7 --runs-dir runs/gait-lesson
```

Each command prints the score and a run directory. Copy those two printed
paths into the following command to create a local, self-contained report:

```bash
uv run creature-lab compare <curated-run-directory> <sinusoid-run-directory> --html outputs/gait-comparison.html
```

Replace both bracketed placeholders with the actual paths, then open the HTML
file. The report compares the saved traces, scores, and diagnostics; keep the
two run directories if you want to replay them later. If you installed the
wheel into an active Python environment, use `creature-lab` in place of
`uv run creature-lab`.

One Windows test with Python 3.12, PyBullet 3.2.7, and seed 7 produced scores
of 1.9703 for the curated gait and 0.5736 for the sinusoid. These are scores
for this task and backend, not a promise of identical physics across machines
or a claim about physical robots.

An [older recorded comparison report](https://github.com/oney-erge/Creature-Lab/releases/download/preview-windows-2026-10-30/gait-comparison-example.html)
shows the two scores and root paths. It was produced with an earlier local 0.2.0
candidate; its original run directories are not included. The current preview
has not been run to verify that it reproduces those results.
