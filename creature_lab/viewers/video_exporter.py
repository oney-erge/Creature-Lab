"""Write rendered frames to a shareable GIF or MP4.

This is a pure consumer of image frames (numpy RGB arrays); it knows nothing about
physics or any backend. The output format is chosen from the file extension. Requires
the optional ``export`` dependency (imageio); import this module lazily.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import imageio.v2 as imageio


def write_animation(frames: list[Any], path: Path, *, fps: float = 30.0) -> Path:
    """Write `frames` to `path` as a GIF or MP4 (by extension) and return the path."""
    if not frames:
        raise ValueError("cannot write an animation with no frames")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".gif":
        # The GIF (Pillow) plugin takes per-frame duration in milliseconds, not fps.
        imageio.mimsave(path, frames, duration=1000.0 / fps)
    else:
        imageio.mimsave(path, frames, fps=fps)
    return path
