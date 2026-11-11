"""Exact joint defaults and action scales of mjlab's G1, resolved the way mjlab resolves them."""

import json
import re

from mjlab.asset_zoo.robots import G1_ACTION_SCALE, get_g1_robot_cfg
from mjlab.entity.entity import Entity

cfg = get_g1_robot_cfg()
entity = Entity(cfg)
names = [j.name for j in entity.spec.joints if j.type.name != "mjJNT_FREE"]
init = cfg.init_state.joint_pos


def first_match(table, name, default):
    for pattern, value in table.items():
        if re.fullmatch(pattern, name):
            return value
    return default


out = {
    "joints": names,
    "default": [first_match(init, n, 0.0) for n in names],
    "action_scale": [first_match(G1_ACTION_SCALE, n, None) for n in names],
    "init_height": cfg.init_state.pos[2],
}
assert None not in out["action_scale"], [
    n for n, s in zip(names, out["action_scale"], strict=True) if s is None
]
print(json.dumps(out))
