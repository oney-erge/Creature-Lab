"""The studio set every robot is filmed in: soft key light, shadows, a pale floor."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from creature_lab.robots.terrain import Terrain, add_terrain

if TYPE_CHECKING:
    import mujoco

_STUDIO = """<mujoco model="{name} check-up">
  <include file="{robot_file}"/>
  <statistic center="0 0 0.1" extent="1"/>
  <visual>
    <headlight ambient="0.28 0.29 0.33" diffuse="0.22 0.22 0.24" specular="0 0 0"/>
    <quality shadowsize="8192" offsamples="8"/>
    <rgba haze="0.27 0.34 0.46 1"/>
    <map znear="0.01" zfar="60" fogstart="{fog_start}" fogend="{fog_end}" shadowscale="0.5"
         shadowclip="1.6"/>
    <global offwidth="1920" offheight="1080" azimuth="145" elevation="-16"/>
  </visual>
  <asset>
    <texture type="skybox" builtin="gradient" rgb1="0.05 0.08 0.14" rgb2="0.27 0.34 0.46"
             width="512" height="512"/>
    <texture type="2d" name="floor_tex" builtin="checker" rgb1="0.17 0.20 0.26"
             rgb2="0.14 0.17 0.22" width="512" height="512" mark="edge" markrgb="0.32 0.38 0.48"/>
    <material name="floor_mat" texture="floor_tex" texrepeat="{repeat} {repeat}" texuniform="true"
              reflectance="0.22"/>
  </asset>
  <worldbody>
    <light name="key" pos="2 -3 4" dir="-0.4 0.6 -1" directional="true"
           diffuse="0.95 0.92 0.86" specular="0.10 0.10 0.10" castshadow="true"/>
    <light name="rim" pos="-3 3 2" dir="0.7 -0.6 -0.35" directional="true"
           diffuse="0.30 0.38 0.52" castshadow="false"/>
    <geom name="floor" type="plane" size="0 0 0.05" material="floor_mat"/>
  </worldbody>
</mujoco>
"""


def write_studio_scene(folder: Path, name: str, robot_file: str, *, tile_m: float = 0.5) -> Path:
    """Write ``checkup_scene.xml`` next to the robot file and return its path.

    ``tile_m`` is the side of one floor square in metres.
    """
    repeat = round(1.0 / (2.0 * tile_m), 3)
    path = Path(folder) / "checkup_scene.xml"
    text = _STUDIO.format(
        name=name,
        robot_file=robot_file,
        repeat=repeat,
        fog_start=round(40 * tile_m, 2),
        fog_end=round(150 * tile_m, 2),
    )
    if not path.exists() or path.read_text(encoding="utf-8") != text:
        path.write_text(text, encoding="utf-8")
    return path


def load_model(scene: Path, terrain: Terrain | None = None) -> mujoco.MjModel:
    """Compile a studio scene, with ``terrain`` (stairs, a ramp, ...) added when there is one."""
    import mujoco

    if terrain is None:
        return mujoco.MjModel.from_xml_path(str(scene))
    spec = mujoco.MjSpec.from_file(str(scene))
    add_terrain(spec, terrain)
    return spec.compile()
