#!/bin/bash
# Train the two G1 policies the way the bundled ones were trained (about 1 hour 15 minutes on a
# laptop RTX 3080 with 2048 simulated robots; needs a Linux or WSL environment with an NVIDIA GPU).
#
#   python -m venv ~/mjlab-venv && . ~/mjlab-venv/bin/activate && pip install mjlab==1.6.0 onnx
#   bash train.sh
#
# Both policies share one seed and one training budget of 1500 iterations (49,152 simulated steps
# per iteration, about 74 million in all). "standard" is mjlab's own recipe. "shoved" is the same run's iteration-900 checkpoint
# (where it already walks reliably) trained 600 more iterations with shoves twice as strong. A
# from-scratch run with strong shoves never learned to stay up (episodes plateaued at 2.6 s), so
# the strong shoves start only once the policy walks.
set -euo pipefail
cd "$(dirname "$0")"
export MUJOCO_GL=egl
ENVS=2048
SEED=7

python train_shoved.py Mjlab-Velocity-Flat-Unitree-G1 \
  --env.scene.num-envs $ENVS --agent.max-iterations 1500 \
  --env.seed $SEED --agent.seed $SEED \
  --agent.run-name stock --agent.logger tensorboard

python train_shoved.py Mjlab-G1-Flat-Shoved \
  --env.scene.num-envs $ENVS --agent.max-iterations 600 \
  --env.seed $SEED --agent.seed $SEED \
  --agent.run-name shoved_ft --agent.logger tensorboard \
  --agent.resume True --agent.load-run '.*_stock$' --agent.load-checkpoint 'model_900.pt'

# Each run leaves <run>/<run>.onnx beside its checkpoints (mjlab exports it when training ends).
