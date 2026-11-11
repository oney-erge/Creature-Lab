# Bring your own robot and policy

A **robot pack** is a folder that lets Creature Lab shove *your* MuJoCo robot with *your* trained
policy, then explain each fall, exactly as it does for the built-in Microduck and Unitree G1.

```text
my-robot/
  robot.toml      how the policy talks to the robot (this page)
  robot.xml       the MuJoCo model (MJCF), with its meshes
  policy.onnx     your trained policy
```

## Try the example

[`examples/robot-pack/`](../examples/robot-pack) in the repository is a small two-legged robot with
a stand-still policy. It needs no download.

```bash
uv run creature-lab robots validate examples/robot-pack   # checks everything, walks it for 2 s
uv run creature-lab robots add examples/robot-pack        # remembers the folder
uv run creature-lab robots checkup stick-biped            # report.html with every fall explained
uv run creature-lab robots remove stick-biped             # forgets it; your files are untouched
```

Copy the folder, replace the model and the policy with yours, and edit `robot.toml`.
`validate` lists every problem in plain words; fix them and run it again.

In the [browser app](WEB_APP.md), **Add your own robot** (under the robot cards) does the same:
type the folder, press **Check it**, read what it found, then **Add**. An added robot gets a
**Your robot** badge, runs the same check-up, and **Remove from the list** forgets it again.

The folder stays where it is (nothing is copied), so edits to `robot.toml` or the policy are
picked up on the next run. Creature Lab writes one generated file, `checkup_scene.xml` (the model
plus a floor and lights), beside your model. Only add folders you trust: Creature Lab opens the
model and policy files in them.

## `robot.toml`

```toml
key = "my_robot"                 # lowercase letters, digits, underscores
title = "My robot"
maker = "Me"
summary = "A 1 m, 20 kg biped trained in my own simulator."
height_cm = 100
mass_kg = 20                     # sizes the default shoves and loads

model = "robot.xml"              # relative to this folder; must not contain a ground plane
trunk = "pelvis"                 # the body with the free joint; "upright" means this body's z axis up
physics_dt = 0.005               # seconds; must divide 0.02 (control runs at 50 Hz)
actuator = "pd"                  # "pd" or "position", see below
action_scale = 0.25              # target pose = default pose + action x action_scale
walk_command = 0.5               # forward speed the policy was trained for (0 to 1)
gait_period_s = 0.8              # seconds per stride; shoves are spread across one stride

[license]
notice = "Where the model and policy come from, and under what license."
credit = "One line printed on every report and video."
non_commercial = false

[joints]                         # every actuated joint, in the order the policy outputs actions
hip = { default = 0.0, kp = 80.0, kd = 2.5 }
knee = { default = 0.3, kp = 80.0, kd = 2.5 }

[[observation]]                  # the policy's input, in order
term = "base_ang_vel"
scale = 0.25
# ...more terms...

[[policies]]                     # one or more; a check-up runs every policy
key = "walk"
title = "My walking policy"
file = "policy.onnx"
gets_up = false                  # true if it stands back up after a fall
```

Optional: `action_clip`, `spawn_height_m` (when the model's own start height is wrong),
`[levels]` (`shoves_n`, `grips`, `payloads_kg`) and `[view]` (`camera_distance_m`,
`floor_tile_m`).

By default the shoves are fractions of body weight (15, 30, 45, 60 and 90 percent of `mass_kg`
times 9.81) and the carried loads are 10, 20 and 30 percent of `mass_kg`. For a 35 kg humanoid
that is about 52 to 310 N and 3.5 to 10 kg, close to the numbers chosen by hand for the G1. List
your own levels under `[levels]` if you want others.

### Observation terms

List the terms in the order your policy was trained on. `scale` is one number or one per entry.

| `term` | What it is | Numbers |
| --- | --- | --- |
| `base_ang_vel` | Trunk angular velocity in the trunk's own frame | 3 |
| `base_lin_vel` | Trunk velocity in the trunk's own frame | 3 |
| `projected_gravity` | Where "down" is in the trunk's frame | 3 |
| `command` | The walking command: forward speed first, then zeros (`size = 3` unless set) | `size` |
| `joint_pos` | Joint angles minus the default pose | one per joint |
| `joint_vel` | Joint velocities | one per joint |
| `last_action` | The policy's previous output | one per joint |
| `gait_phase` | `sin` and `cos` of a stride clock (`period_s` = seconds per stride) | 2 |
| `sensor` | A named MuJoCo sensor (`sensor = "imu_gyro"`) | the sensor's width |

The policy's input size must equal the total. `validate` shows the layout and the two numbers when
they disagree.

### Actions, torque and limits

The policy outputs one action per joint. The target pose is
`default + action x action_scale` (after an optional `action_clip`). A joint can set its own
`action_scale`, which replaces the pack's for that joint; the pack-level one may then be left out.

- **`actuator = "pd"`**: the model's actuators are plain motors and Creature Lab computes
  `torque = kp x (target - angle) - kd x velocity` at every physics step, with the `kp` and `kd`
  you list per joint. This is how Unitree's legged_gym-style policies are trained.
- **`actuator = "position"`**: the model's actuators are position servos that hold their own
  gains (MuJoCo `<position>`). The target is sent as the control.

"Torque limit" is what counts as 100 percent load in the report (the "motors ran out of torque"
test). It is read from the joint's `actuatorfrcrange`, or the actuator's `forcerange` or
`ctrlrange`; add `torque_limit = <N·m>` to a joint when the model has none.

### Policy files

- **`.onnx`**: one input (the observation, shape `[1, N]`) and one output (the action). Export
  from PyTorch with
  `torch.onnx.export(policy, torch.zeros(1, N), "policy.onnx", input_names=["obs"], output_names=["action"])`.
- **`.npz`**: a one-layer LSTM followed by a two-layer head with ELU, which is the shape of
  Unitree's G1 policy. The arrays are PyTorch's: `lstm_weight_ih_l0`, `lstm_weight_hh_l0`,
  `lstm_bias_ih_l0`, `lstm_bias_hh_l0`, `fc1_weight`, `fc1_bias`, `fc2_weight`, `fc2_bias`.

A TorchScript `.pt` needs converting first. Policies that stack past observations or keep other
hidden state are not supported yet.

## When the robot falls in the 2-second trial

`validate` walks the robot for two seconds with no shove. If it falls, the pack is still usable
(a bad policy is a legitimate thing to check up), but the usual cause is a mismatch with training:

- the observation terms, their order or their scales differ from training;
- the default pose or the gains differ;
- the model differs from the one the policy was trained on (masses, friction, joint limits);
- the policy expects a different control or physics rate (only 50 Hz control is supported).

## What is checked

The same tests as for the built-in robots: shoves at five strengths at eight points of the stride,
slippery floors, and carried loads. The explanation of each fall (where the weight went relative
to the feet, how fast the feet slid, whether the motors ran out of torque) comes from the recorded
run, so it does not depend on which robot it is. There is no battery test for your robot.

The Unitree G1 itself is verified this way: a pack holding the G1's constants runs bit for bit
identically to the built-in G1 (tests `test_the_g1_as_a_pack_matches_the_built_in_adapter_exactly`).

## Limits

- Control runs at 50 Hz; `physics_dt` must divide 0.02.
- The trunk must carry the robot's free joint, and the model must not contain a ground plane.
- Every actuated joint is listed and driven by the policy. A policy that drives only some joints
  and holds the rest still is not supported yet.
- The browser app draws a model's visible meshes. A model with no meshes is drawn from its
  boxes, capsules, cylinders, spheres and ellipsoids (geom groups 0 to 2); a model that has both
  draws only the meshes, since published robots keep their collision shapes beside them.
