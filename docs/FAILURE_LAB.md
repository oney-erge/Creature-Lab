# Failure Lab: Three Reproducible Robotics Lessons

Creature Lab's first post-release specialization is education: short experiments where the goal
is not merely to make something move, but to form a hypothesis, isolate one variable, and preserve
evidence another person can rerun.

## Lesson 1: Body Or Controller?

```bash
creature-lab failure export frozen-gait --out outputs/lesson-1
cd outputs/lesson-1
creature-lab autopsy creature.json --task task.json --controller controller.json
```

Before opening the report, predict the cause. Compare the failed controller with the curated
counterfactual, change only motor amplitude, and rerun. Explain why changing the body first would
be a weaker experiment.

## Lesson 2: Nominal Success Is Not Robustness

Export `overdriven-gait` or `ice-rink-task`. Find a configuration that succeeds once, then run
qualification. Record nominal score, task success rate under perturbations, and which single
change improves the failure rate without simply lowering the task threshold.

```bash
creature-lab qualify creature.json --task task.json --profile basic-locomotion
```

## Lesson 3: Portable Artifact, Different Physics

Run one experiment on both backends and distinguish two claims:

- Structural portability: both backends can load the same artifacts.
- Behavioral portability: scores and task outcomes agree within a declared threshold.

```bash
creature-lab autopsy creature.json --task task.json \
  --controller controller.json --check-portability
```

Use the generated pack as the submission. A complete submission includes the hypothesis, the
single variable changed, the autopsy report, and `verify-pack` output.
The report's `evidence/` folder contains separate hash-verifiable packs for the recorded
reference and perturbation runs. Its JSON records trial seeds and scale factors. If the selected
controller and curated reference cannot be distinguished, the reference is skipped and the
report does not attribute a failure to the controller comparison.

## Instructor Regression Check

```bash
creature-lab zoo check-showcases
creature-lab failure list
```

Failure cases declare expected causal categories. They can become automated curriculum tests as
attribution grows more precise; until then, keep the expected file beside each exported exercise
and discuss disagreements as evidence, not as a score to game.
