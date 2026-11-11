"""Pinned, hashed download manifest for the G1's meshes at mjlab v1.6.0, checked against the files
the model was exported with."""

import hashlib
import json
import sys
import urllib.request
from pathlib import Path

SHA = "0fb8a681136be94ffc636a3dd423cabb97d91f10"
RAW = (
    f"https://raw.githubusercontent.com/mujocolab/mjlab/{SHA}/"
    "src/mjlab/asset_zoo/robots/unitree_g1/xmls/assets"
)
local = Path(sys.argv[1])  # the assets folder the model was exported with
out = Path(sys.argv[2])

files = []
for mesh in sorted(local.iterdir()):
    request = urllib.request.Request(f"{RAW}/{mesh.name}", headers={"User-Agent": "creature-lab"})
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
        remote = response.read()
    mine = mesh.read_bytes()
    assert hashlib.sha256(remote).hexdigest() == hashlib.sha256(mine).hexdigest(), mesh.name
    files.append(
        {
            "path": f"assets/{mesh.name}",
            "url": f"{RAW}/{mesh.name}",
            "sha256": hashlib.sha256(remote).hexdigest(),
            "bytes": len(remote),
        }
    )
manifest = {
    "robot": "unitree_g1_29dof",
    "source": f"https://github.com/mujocolab/mjlab/tree/{SHA}",
    "files": files,
}
out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
print(
    len(files),
    "meshes,",
    round(sum(f["bytes"] for f in files) / 1e6, 1),
    "MB, all identical to the exported files",
)
