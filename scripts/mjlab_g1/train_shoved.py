"""Register mjlab's G1 velocity task with stronger random shoves, then train it like mjlab does.

mjlab's own task, ``Mjlab-Velocity-Flat-Unitree-G1``, pushes the robot every 1-3 s by setting its
velocity to a random value within +-0.5 m/s (x and y). The task registered here,
``Mjlab-G1-Flat-Shoved``, is identical in every way except that x and y go to +-1.0 m/s. This
file is used instead of mjlab's ``train`` command, with the same arguments:

    python train_shoved.py Mjlab-G1-Flat-Shoved --env.scene.num-envs 2048 ...

See README.md in this folder for the two stages the bundled policies were trained with.
"""

import mjlab.tasks.velocity.config.g1  # noqa: F401  (registers mjlab's own G1 tasks)
from mjlab.scripts.train import main
from mjlab.tasks.registry import register_mjlab_task
from mjlab.tasks.velocity.config.g1.env_cfgs import unitree_g1_flat_env_cfg
from mjlab.tasks.velocity.config.g1.rl_cfg import unitree_g1_ppo_runner_cfg
from mjlab.tasks.velocity.rl import VelocityOnPolicyRunner

#: Largest speed in m/s a random shove gives the robot sideways or forwards (mjlab's default: 0.5).
SHOVE_M_S = 1.0


def shoved_env_cfg(play: bool = False):
    cfg = unitree_g1_flat_env_cfg(play=play)
    if not play:  # play mode removes the push event, as in mjlab
        ranges = cfg.events["push_robot"].params["velocity_range"]
        ranges["x"] = (-SHOVE_M_S, SHOVE_M_S)
        ranges["y"] = (-SHOVE_M_S, SHOVE_M_S)
    return cfg


register_mjlab_task(
    task_id="Mjlab-G1-Flat-Shoved",
    env_cfg=shoved_env_cfg(),
    play_env_cfg=shoved_env_cfg(play=True),
    rl_cfg=unitree_g1_ppo_runner_cfg(),
    runner_cls=VelocityOnPolicyRunner,
)

if __name__ == "__main__":
    main()
