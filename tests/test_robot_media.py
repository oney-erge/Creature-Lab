"""README loop writers: animated WebP and palette GIF, chosen by suffix."""

import numpy as np
import pytest

pytest.importorskip("mujoco")  # the video module draws with the renderer
pytest.importorskip("imageio_ffmpeg")
pytest.importorskip("PIL")

from PIL import Image  # noqa: E402

from creature_lab.robots.video import write_gif, write_loop  # noqa: E402


def _frames(count=8, width=160, height=90):
    for index in range(count):
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        frame[:, : (index + 1) * width // count] = (240, 120, 40)  # a bar that grows
        yield frame


def test_gif_keeps_every_other_frame_at_the_requested_width(tmp_path):
    path = write_gif(tmp_path / "loop.gif", _frames(), width=80)
    with Image.open(path) as gif:
        assert gif.format == "GIF"
        assert gif.size[0] == 80
        assert gif.n_frames == 4
        assert gif.info.get("loop") == 0  # loops forever


def test_loop_format_follows_the_suffix(tmp_path):
    with Image.open(write_loop(tmp_path / "a.webp", _frames(), width=120)) as webp:
        assert webp.format == "WEBP" and webp.size[0] == 120
    with Image.open(write_loop(tmp_path / "a.gif", _frames(), width=120)) as gif:
        assert gif.format == "GIF" and gif.size[0] == 120
