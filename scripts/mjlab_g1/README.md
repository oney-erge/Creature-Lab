# The two G1 policies: how they were trained

The built-in **Unitree G1 (29 joints)** has two walking policies that were trained for Creature
Lab with [mjlab](https://github.com/mujocolab/mjlab) (v1.6.0, Apache-2.0):

| Policy | How it was trained |
| --- | --- |
| **Small-shove policy** (`standard`) | mjlab's own `Mjlab-Velocity-Flat-Unitree-G1` recipe, unchanged: 1500 iterations, with a random push every 1 to 3 seconds that sets the robot's speed to a random value up to 0.5 m/s sideways and forwards. |
| **Strong-shove policy** (`shoved`) | The same run's checkpoint at iteration 900, where it already walks reliably, trained 600 more iterations (1500 in all) with the pushes up to **1.0 m/s**, twice as strong. Nothing else differs. |

The point is a controlled comparison for Creature Lab's check-up: same robot, same seed, same
number of iterations, one change.

## What was run

- `train_shoved.py` registers mjlab's G1 task with the stronger push (`Mjlab-G1-Flat-Shoved`) and
  runs mjlab's own training entry point; `train.sh` runs both stages.
- 2048 simulated robots, seed 7, mjlab's default PPO settings. 49,152 simulated steps per iteration,
  about 74 million in all, about 1 hour 15 minutes on a laptop RTX 3080 (about 29,000 steps per
  second), on Ubuntu in WSL2.
- A first attempt trained the strong-shove task from scratch. It never learned to stay up (episodes
  plateaued at about 2.6 seconds, close to the 1 to 3 second gap between pushes), so it was stopped at
  iteration 795. Strong shoves start only once the policy walks.

## How the model and the pack were made

mjlab builds the G1 in Python: its XML has no actuators, and the position actuators, gains, effort
limits, joint armature, collision settings and IMU sensors are added by code. To run the same robot
the policies were trained on, `export_model.py` writes mjlab's finished G1 as a standalone MuJoCo
model together with the physics mjlab simulates with (5 ms steps, `implicitfast`, 10 solver
iterations), and checks that the file rebuilds the same model on 24 properties (masses, inertias,
armature, damping, friction loss, limits, actuator gains and force ranges, contact settings and more).
`exact_constants.py` reads the exact default pose and action scales (mjlab writes them to three
decimals into the policy file), `make_manifest.py` pins the 35 mesh files at mjlab's v1.6.0 commit and
checks that they equal the exported ones, and the bundled `robot.toml` ties them together.
`creature-lab robots init` drafts the same file from the model and a policy's metadata.

The meshes are byte-identical to MuJoCo Menagerie's `unitree_g1` (BSD 3-Clause, Unitree Robotics).

## Re-run it

```bash
python -m venv ~/mjlab-venv && . ~/mjlab-venv/bin/activate && pip install mjlab==1.6.0 onnx
bash train.sh                      # about 1 hour 15 minutes with an NVIDIA GPU
python export_model.py OUT         # the standalone model and meshes, checked against mjlab's
```

Training is not bit-for-bit reproducible across machines (GPU kernels and the physics solver differ),
so a re-run gives policies that behave like these, not the same weights.

## Comparing the two

```bash
creature-lab robots fetch unitree-g1-29dof --yes
creature-lab robots checkup unitree-g1-29dof --out results
creature-lab robots compare results/standard results/shoved
```

`robots compare` says which of the tests got better or worse and `--markdown` writes a table for a
pull-request comment.

## What the check-up found

Both policies walk without falling (4.1 m and 4.7 m in 10 seconds at the same command) and stay up
through every shove sized from the robot's weight alone (up to 290 N), so this robot's check-up
shoves harder: 150, 300, 400, 550 and 700 N, eight shoves each across one stride. The strong-shove
policy is better on four tests and worse on none:

| Test | Small-shove policy | Strong-shove policy |
| --- | --- | --- |
| 400 N shove | 3 of 8 stay up | 7 of 8 stay up |
| 550 N shove | 0 of 8 | 3 of 8 |
| 700 N shove | 0 of 8 | 2 of 8 |
| Floor grip at 0.15x normal | fell | walked |
| 150 and 300 N shoves, other floors, loads of 3.3 to 10 kg | passed | passed |

Neither policy gets back up after a fall: neither was trained to.

The two runs took 73 and 19 minutes of wall time, with other work sharing the machine; at the
measured 29,000 steps per second the 74 million steps are about 45 minutes of GPU time.
