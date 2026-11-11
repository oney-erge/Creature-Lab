# Example robot pack

A small two-legged robot with a stand-still policy, to show the shape of a robot pack. It does not
walk: the policy always answers "hold the default pose", so the check-up shows how much shove a
stiff little biped takes before it tips over.

| File | What it is |
| --- | --- |
| `robot.toml` | How the policy talks to the robot: joints, gains, observation, policy |
| `stick_biped.xml` | The MuJoCo model (no ground plane: Creature Lab adds the floor) |
| `policy.onnx` | 27 observation numbers in, 6 actions out (written by `make_policy.py`) |
| `make_policy.py` | Writes `policy.onnx` by hand, so no ONNX library is needed |

```bash
uv run creature-lab robots validate examples/robot-pack
uv run creature-lab robots add examples/robot-pack
uv run creature-lab robots checkup stick-biped
```

Full guide: [Bring your own robot](../../docs/ROBOT_PACKS.md). The model and the policy were written
for Creature Lab and are Apache-2.0, like the rest of the project.
