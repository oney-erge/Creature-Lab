# Robot check-up

Run a real, published robot with its real trained walking policy, shove it, make the floor
slippery, weaken the battery, and get a plain-language answer to *why it fell*.

```bash
uv sync --inexact --extra robots
uv run creature-lab robots checkup microduck
```

The [browser app](WEB_APP.md) shows the same results in 3D, puts a shove to both policies side by
side, and can start a check-up for you.

"Balance point vs feet" compares where the body is heading with the area the feet hold it up
from. That area is the hull of the foot contacts, or, for a mesh foot such as Microduck's, of the
part of the sole within 6 mm of the floor (MuJoCo reports a mesh touching at a few points
millimetres apart, which would make a flat foot look like a point).

The first run downloads the robot (14 to 40 MB, depending on the robot) after showing you its
license. It then runs
about fifty ten-second simulations per policy on the CPU (20 to 40 seconds), and writes a folder
containing `report.html`, a `checkup.json` per policy, and the saved runs behind every claim.
Add `--film` for a 1080p film of the same results (about 5 minutes to encode).

| Command | What it does |
| --- | --- |
| `creature-lab robots list` | The robots, their policies, and whether they are downloaded |
| `creature-lab robots fetch ROBOT` | Download a robot's files, verified against pinned SHA-256 hashes |
| `creature-lab robots checkup ROBOT` | Run every test, write the HTML report (`--film` for the video) |
| `creature-lab robots init FOLDER` | Draft `robot.toml` from your model and policy (see [Bring your own robot](ROBOT_PACKS.md)) |
| `creature-lab robots validate FOLDER` | Check your own robot and policy, then walk it for two seconds |
| `creature-lab robots add FOLDER` / `remove ROBOT` | Add or forget your own robot (see [Bring your own robot](ROBOT_PACKS.md)) |
| `creature-lab robots film RESULTS` | Encode the film for an existing results folder |
| `creature-lab robots loop RESULTS` | The short side-by-side README loop (animated WebP) |

## The robots

| Robot | Policy | Where it comes from |
| --- | --- | --- |
| **Microduck** (25 cm, 14 servos; Pollen Robotics and Hugging Face) | `alpha_walking`: an earlier walk-only policy | [pollen-robotics/microduck-policies](https://huggingface.co/pollen-robotics/microduck-policies) |
| | `velstand`: Pollen's current walk + get-up policy | same repository |
| **Unitree G1** (1.3 m humanoid; leg joints only, arms held still) | `motion`: Unitree's pretrained walking policy | [unitreerobotics/unitree_rl_gym](https://github.com/unitreerobotics/unitree_rl_gym) |
| **Unitree G1, 29 joints** (1.3 m humanoid; every joint driven; the model as [mjlab](https://github.com/mujocolab/mjlab) trains it) | `standard`: mjlab's standard G1 recipe, trained with small random shoves; `shoved`: the same run trained further with shoves twice as strong. Both trained for Creature Lab, see [scripts/mjlab_g1](../scripts/mjlab_g1/README.md) | mjlab v1.6.0 (Apache-2.0); Unitree's model and meshes (BSD 3-Clause) |
| **Unitree H1** (1.8 m humanoid; 10 leg joints, upper body held still) | `motion`: Unitree's pretrained walking policy | same repository |
| **Unitree H1-2** (1.8 m humanoid; 12 leg joints, upper body held still) | `motion`: Unitree's pretrained walking policy | same repository |

Microduck is the robot Jensen Huang showed at GTC Berlin in October 2026. Creature Lab is not
affiliated with or endorsed by any of these companies; their names only say what was tested.

### Licenses

- **Microduck:** the code, model XML and policies are Apache-2.0, but the 3D mesh files are
  **CC BY-NC-SA 4.0**: non-commercial, share-alike, credit Pollen Robotics. Creature Lab never
  bundles them. `robots fetch` shows this notice and asks before downloading, and every film and
  report that shows the meshes carries the credit line. Treat pictures and videos made with the
  meshes as non-commercial.
- **Unitree G1 with 29 joints:** the model and meshes are Unitree's (BSD 3-Clause; the meshes are
  byte-identical to MuJoCo Menagerie's `unitree_g1`) as distributed with mjlab (Apache-2.0). The
  meshes are downloaded on first use from mjlab at a pinned commit; the model XML (mjlab's G1 task
  exported as it is simulated) and the two policies, which were trained for Creature Lab, ship with
  it, with both license texts beside them in `creature_lab/robots/data/packs/unitree_g1_29dof/`.
- **Unitree G1, H1 and H1-2:** BSD 3-Clause. The model is downloaded on first use. The policy
  weights are bundled as a small `.npz` converted from Unitree's `motion.pt` (checked against the
  original TorchScript outputs); the license text sits beside them in
  `creature_lab/robots/data/` (G1) and `creature_lab/robots/data/packs/<robot>/` (H1, H1-2).
  H1 and H1-2 are described by a bundled robot pack ([Bring your own robot](ROBOT_PACKS.md)): a
  `robot.toml` and the policy ship with Creature Lab, and only the model and meshes are downloaded.
- **Servo model:** Microduck's policies were trained against Rhoban's
  [BAM](https://github.com/Rhoban/bam) XL330 servo model (Apache-2.0). Creature Lab
  reimplements just those equations (`robots/actuator.py`); a test pins it to values produced by
  the BAM package.

Downloaded files live in `%LOCALAPPDATA%\creature-lab\robots` (Windows),
`~/Library/Caches/creature-lab/robots` (macOS) or `~/.cache/creature-lab/robots` (Linux).
Set `CREATURE_LAB_ROBOTS_DIR` to move them.

## In the editor

Open **Real robots: Microduck, Unitree G1** at the top of the build editor's panel (`uv run
creature-lab build`):

- **Show robot in 3D** swaps your creature for the real robot, drawn from its meshes.
- **Replay in 3D** plays any saved run of the newest check-up (baseline, the shoves that fell and
  the ones that did not, slippery floors) on that robot, with a camera that follows it.
- **Run robot check-up** starts a check-up in the background and opens its report when done.
- **Back to my creature** returns to the design you were editing.

The panel never accepts a license for you: if the robot is not downloaded yet it tells you to
run `creature-lab robots fetch ...` in a terminal, which shows the license first.

## What it tests

1. **Baseline walk.** Ten seconds forward at a fixed command.
2. **Shoves.** A sideways force on the trunk for 0.2 s, at several strengths. Each strength is
   tried **eight times, at eight points of the stride, alternating sides**, because whether a
   shove topples a walking robot depends on which foot is down when it lands. One lucky or
   unlucky timing would otherwise decide the result.
3. **Uneven ground.** Four short courses laid ahead of the robot, each at a few heights: stairs
   (four steps up, a landing, four down), a ramp up and over, rough ground of randomly raised
   tiles, and stepping stones over a pit. Every course is sized from the robot's height: for the
   1.34 m G1 the steps are 4, 8, 12 and 16 cm on 30 cm treads, the ramps 8°, 16° and 24°, the
   bumps up to 3, 5 and 8 cm and the gaps between 40 cm stones 5, 11 and 16 cm; the 25 cm
   Microduck meets the same shapes at a fifth of the size.
4. **Conditions.** Floor grip at 0.5×, 0.3× and 0.15× normal; a weak battery (Microduck); a
   carried load (G1).

A run **falls** when the trunk tilts past 60°. It **gets back up** if it is within about 26° of
upright for half a second afterwards.

## How it explains a fall

For the first fall in a run, `analysis.py` reads the recorded signals and names the one that
fits, always showing all of them:

| Cause | Evidence used |
| --- | --- |
| Pushed off balance | A shove just before the fall, and the **extrapolated centre of mass** (where the body is heading, `x + v/√(g/h)`) leaving the outline of the feet |
| Missed the stones | On stepping stones, a foot down in a gap between them (lower than 15% of the pit's depth) in the second before it started to tip |
| Caught a step | A foot pressing on the side or edge of a step, stone or tile (a contact whose surface leans more than 45° from flat) with at least a quarter of the body's weight, in the second before it started to tip |
| Too steep | On a ramp, a fall with nothing caught and nothing pushing |
| Slipped | Median sliding speed of the touching points above 0.05 m/s in the 0.8 s before the fall |
| Servos saturated | Any servo at 95% of its torque limit for at least 30% of that window |
| Unclear | None of the above: the report says so instead of guessing |

The pass/fail table and the explanations come from the same saved runs, so each number can be
traced to a replayable scenario.

## Reading the result

The Microduck check-up shows the kind of finding this is for. The older walk-only policy tops
out at a 1 N shove: from 2 N up, most shoves leave it on the floor for good. Pollen's newer
policy falls a little more often, but never stays down, because it gets back up. On a very
slippery floor (0.15× grip) *both* fail, and the report says that no policy swap fixes that:
the feet need grip. Re-run it to see the current numbers on your machine.

## Did a change make it more robust?

`robots compare` reads two saved check-ups (no simulator needed) and says, test by test, what got
better or worse:

```bash
uv run creature-lab robots compare outputs/checkup/old outputs/checkup/new --policy velstand
uv run creature-lab robots compare old new --fail-on-regression --json compare.json --markdown compare.md
```

Each argument is a folder holding `checkup.json`, or a results folder with policy folders inside
(choose one with `--policy`). A shove strength gets worse when more of its shoves end on the floor
(a shove that leaves the robot down counts 2, one it recovers from counts 1; `--tolerance N`
forgives small changes). A floor, battery or payload test gets worse when it passed and now falls.
`--fail-on-regression` makes the command exit with status 1, so a training pipeline can stop when
a new policy is less robust than the last one. The Markdown file is a table for a pull-request
comment. A sketch for a GitHub Actions step, after the new policy is trained:

```yaml
- run: uv run creature-lab robots checkup unitree-g1 --yes --out new
- run: uv run creature-lab robots compare baseline/unitree_g1 new/motion --fail-on-regression --markdown compare.md
```

`--yes` accepts the robot's license for you, so only use it where you have read it. A full check-up
runs on the CPU in a few minutes. Keep the baseline folder in your repository or a cache.

## A robustness card for your README

```bash
uv run creature-lab robots card outputs/checkup/microduck-20261110/velstand --out docs/robustness.svg
```

writes a self-contained SVG (the shove strengths as rows of coloured squares, the grip, battery and
payload tests, and the credit and "simulation, not hardware" line) and prints a one-sentence claim to
paste beside it, for example "never fell up to 1 N; never stayed on the floor up to 6 N. 21 of 48
simulated shoves ended standing...". It is built only from the saved results.

## Saved runs

Each run is a folder with `robot_run.json` (scenario, hash, versions, policy SHA-256) and
`states.npz` (50 Hz poses, velocities, servo load, contact outline, slide speed). Runs are
deterministic: the same files and versions give the same arrays. `RobotRun.read(folder)` loads
one for analysis or filming.

## Honest limits

- **It is a simulation, not the hardware.** The Microduck policies were trained against a
  different simulator (MuJoCo Warp on a GPU); Creature Lab runs them in CPU MuJoCo through a
  reimplemented servo model. Our walking speed is below the commanded speed, and absolute
  results differ from Pollen's own. Use the comparisons between policies and conditions, not
  the absolute numbers.
- **Shove forces are applied at the trunk for 0.2 s.** They are a standard test, not a model of
  any real person's push.
- **The courses are boxes.** Steps have sharp edges and the same grip as the floor, and the robot
  walks straight at them with the same command it walks with on the flat. A policy that never saw
  stairs in training is expected to trip; the courses show where, and whether another policy does
  better.
- **G1:** only the 12 leg joints are driven; the arms hang in a fixed pose, and the policy has no
  get-up behaviour.
- **Rendering** needs OpenGL. On a headless Linux machine set `MUJOCO_GL=egl` (or `osmesa`).
  The check-up itself and the HTML report need no graphics.
- The editor's 3D robot view and replay are unit-tested and were drawn once in a headless
  browser; the buttons have not had a walkthrough in a GPU browser.

## Adding another robot

Add a `RobotInfo` to `robots/catalog.py` with a pinned manifest in `robots/data/`
(`url` pinned to a commit, `sha256`, `bytes` for every file), a `MujocoRobot` subclass that wires
observations and actuators, and a test that the manifest is pinned. Prefer permissive licenses;
never bundle files whose license is more restrictive than this repository's.

Hash the upstream bytes (`git show <commit>:<path>`), not a Windows checkout: a checkout may
convert line endings in text files, and the downloader will then refuse the genuine file.
Read the policy's training configuration for its observation layout (Microduck's policies take
projected gravity, not the raw accelerometer) and compare a short run against the authors' own
reference script before trusting results.
