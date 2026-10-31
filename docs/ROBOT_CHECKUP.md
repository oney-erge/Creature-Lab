# Robot check-up

Run a real, published robot with its real trained walking policy, shove it, make the floor
slippery, weaken the battery, and get a plain-language answer to *why it fell*.

```bash
uv sync --inexact --extra robots
uv run creature-lab robots checkup microduck
```

The first run downloads the robot (about 25 MB) after showing you its license. It then runs
about fifty ten-second simulations per policy on the CPU (20 to 40 seconds), and writes a folder
containing `report.html`, a `checkup.json` per policy, and the saved runs behind every claim.
Add `--film` for a 1080p film of the same results (about 5 minutes to encode).

| Command | What it does |
| --- | --- |
| `creature-lab robots list` | The robots, their policies, and whether they are downloaded |
| `creature-lab robots fetch ROBOT` | Download a robot's files, verified against pinned SHA-256 hashes |
| `creature-lab robots checkup ROBOT` | Run every test, write the HTML report (`--film` for the video) |
| `creature-lab robots film RESULTS` | Encode the film for an existing results folder |
| `creature-lab robots loop RESULTS` | The short side-by-side README loop (animated WebP) |

## The robots

| Robot | Policy | Where it comes from |
| --- | --- | --- |
| **Microduck** (25 cm, 14 servos; Pollen Robotics and Hugging Face) | `alpha_walking`: an earlier walk-only policy | [pollen-robotics/microduck-policies](https://huggingface.co/pollen-robotics/microduck-policies) |
| | `velstand`: Pollen's current walk + get-up policy | same repository |
| **Unitree G1** (1.3 m humanoid; leg joints only, arms held still) | `motion`: Unitree's pretrained walking policy | [unitreerobotics/unitree_rl_gym](https://github.com/unitreerobotics/unitree_rl_gym) |

Microduck is the robot Jensen Huang showed at GTC Berlin in October 2026. Creature Lab is not
affiliated with or endorsed by any of these companies; their names only say what was tested.

### Licenses

- **Microduck:** the code, model XML and policies are Apache-2.0, but the 3D mesh files are
  **CC BY-NC-SA 4.0**: non-commercial, share-alike, credit Pollen Robotics. Creature Lab never
  bundles them. `robots fetch` shows this notice and asks before downloading, and every film and
  report that shows the meshes carries the credit line. Treat pictures and videos made with the
  meshes as non-commercial.
- **Unitree G1:** BSD 3-Clause. The model is downloaded on first use. The policy weights are
  bundled as a small `.npz` converted from Unitree's `motion.pt`; the license text sits beside
  it in `creature_lab/robots/data/`.
- **Servo model:** Microduck's policies were trained against Rhoban's
  [BAM](https://github.com/Rhoban/bam) XL330 servo model (Apache-2.0). Creature Lab
  reimplements just those equations (`robots/actuator.py`); a test pins it to values produced by
  the BAM package.

Downloaded files live in `%LOCALAPPDATA%\creature-lab\robots` (Windows),
`~/Library/Caches/creature-lab/robots` (macOS) or `~/.cache/creature-lab/robots` (Linux).
Set `CREATURE_LAB_ROBOTS_DIR` to move them.

## What it tests

1. **Baseline walk.** Ten seconds forward at a fixed command.
2. **Shoves.** A sideways force on the trunk for 0.2 s, at several strengths. Each strength is
   tried **eight times, at eight points of the stride, alternating sides**, because whether a
   shove topples a walking robot depends on which foot is down when it lands. One lucky or
   unlucky timing would otherwise decide the result.
3. **Conditions.** Floor grip at 0.5×, 0.3× and 0.15× normal; a weak battery (Microduck); a
   carried load (G1).

A run **falls** when the trunk tilts past 60°. It **gets back up** if it is within about 26° of
upright for half a second afterwards.

## How it explains a fall

For the first fall in a run, `analysis.py` reads the recorded signals and names the one that
fits, always showing all of them:

| Cause | Evidence used |
| --- | --- |
| Pushed off balance | A shove just before the fall, and the **extrapolated centre of mass** (where the body is heading, `x + v/√(g/h)`) leaving the outline of the feet |
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
- **G1:** only the 12 leg joints are driven; the arms hang in a fixed pose, and the policy has no
  get-up behaviour.
- **Rendering** needs OpenGL. On a headless Linux machine set `MUJOCO_GL=egl` (or `osmesa`).
  The check-up itself and the HTML report need no graphics.
- The editor's interactive 3D view does not show these robots yet; the check-up writes its own
  report and film.

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
