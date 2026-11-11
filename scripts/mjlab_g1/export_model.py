"""Write mjlab's Unitree G1 (as it is trained) to a standalone MuJoCo model folder.

mjlab builds the robot in Python: it loads the menagerie-derived XML, then adds position
actuators with per-joint gains and effort limits, joint armature, collision settings and an IMU.
The XML on disk lacks all of that, so this exports the finished spec instead, plus the physics
settings mjlab simulates with. Run it in an environment that has mjlab installed:

    python export_model.py OUT_DIR
"""

import shutil
import sys
from pathlib import Path

import mujoco
import numpy as np
from mjlab.asset_zoo.robots import get_g1_robot_cfg
from mjlab.asset_zoo.robots.unitree_g1.g1_constants import G1_XML
from mjlab.entity.entity import Entity
from mjlab.tasks.velocity.config.g1.env_cfgs import unitree_g1_flat_env_cfg

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)

sim = unitree_g1_flat_env_cfg().sim.mujoco
spec = Entity(get_g1_robot_cfg()).spec
# The physics mjlab trains with (the entity's own spec says 0.002 s and the defaults).
spec.option.timestep = sim.timestep
spec.option.integrator = {"implicitfast": mujoco.mjtIntegrator.mjINT_IMPLICITFAST}[sim.integrator]
spec.option.cone = {"pyramidal": mujoco.mjtCone.mjCONE_PYRAMIDAL}[sim.cone]
spec.option.impratio = sim.impratio
spec.option.solver = {"newton": mujoco.mjtSolver.mjSOL_NEWTON}[sim.solver]
spec.option.iterations = sim.iterations
spec.option.ls_iterations = sim.ls_iterations
spec.option.tolerance = sim.tolerance
spec.option.ccd_iterations = sim.ccd_iterations
reference = spec.compile()

xml = spec.to_xml()
(out / "g1_mjlab.xml").write_text(xml, encoding="utf-8")
assets = out / "assets"
if not assets.exists():
    shutil.copytree(G1_XML.parent / "assets", assets)

# The XML must rebuild exactly the model mjlab trains with.
loaded = mujoco.MjModel.from_xml_path(str(out / "g1_mjlab.xml"))
checks = {
    "sizes": (loaded.nq, loaded.nv, loaded.nu, loaded.ngeom, loaded.nsensor, loaded.nmesh)
    == (
        reference.nq,
        reference.nv,
        reference.nu,
        reference.ngeom,
        reference.nsensor,
        reference.nmesh,
    ),
    "timestep": loaded.opt.timestep == reference.opt.timestep == sim.timestep,
    "integrator": loaded.opt.integrator == reference.opt.integrator,
    "cone/impratio/solver": (loaded.opt.cone, loaded.opt.impratio, loaded.opt.solver)
    == (reference.opt.cone, reference.opt.impratio, reference.opt.solver),
}
for name in (
    "body_mass",
    "body_inertia",
    "dof_armature",
    "dof_damping",
    "dof_frictionloss",
    "jnt_range",
    "jnt_actfrcrange",
    "actuator_gainprm",
    "actuator_biasprm",
    "actuator_forcerange",
    "actuator_ctrlrange",
    "actuator_trnid",
    "geom_friction",
    "geom_condim",
    "geom_priority",
    "geom_contype",
    "geom_conaffinity",
    "geom_size",
    "geom_pos",
    "qpos0",
):
    checks[name] = bool(np.allclose(getattr(loaded, name), getattr(reference, name), atol=1e-9))
bad = [k for k, ok in checks.items() if not ok]
print("checked", len(checks), "properties; mismatches:", bad or "none")
print("mass kg:", round(float(loaded.body_subtreemass[1]), 3), "nq", loaded.nq, "nu", loaded.nu)
print(
    "sensors:",
    [mujoco.mj_id2name(loaded, mujoco.mjtObj.mjOBJ_SENSOR, i) for i in range(loaded.nsensor)],
)
print("files:", sorted(p.name for p in out.iterdir()), "meshes:", len(list(assets.iterdir())))
sys.exit(1 if bad else 0)
