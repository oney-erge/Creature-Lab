"""Compose check-up films from recorded runs: clips, split screens, cards, and encoders."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

from creature_lab.robots import overlay
from creature_lab.robots.analysis import balance_margin_cm
from creature_lab.robots.render import Studio
from creature_lab.robots.types import RobotRun

FPS = 30
_RAMP_S = 0.25  # sim seconds over which slow motion eases in and out


@dataclass
class Clip:
    """A run filmed from ``t0`` to ``t1`` (simulation seconds), with HUD and captions."""

    studio: Studio
    run: RobotRun
    t0: float
    t1: float
    robot_title: str
    policy_title: str
    credit: str
    #: (start, end, factor) windows of simulation time shown slower.
    slow: Sequence[tuple[float, float, float]] = ()
    #: (start, end, lines) captions in simulation time.
    captions: Sequence[tuple[float, float, Sequence[str]]] = ()
    #: (start, heading, items) evidence card revealed from ``start`` (simulation time).
    evidence: tuple[float, str, Sequence[tuple[str, str, tuple]]] | None = None
    #: (start, text, color) tag in the HUD from ``start`` on.
    tags: Sequence[tuple[float, str, tuple]] = ()
    timeline: bool = True
    markers: bool = True
    #: (kicker, title, subtitle) block drawn over the opening shot.
    hero: tuple[str, str, str] | None = None
    #: Sideways framing offset passed to the renderer (see ``Studio.render``).
    shift: float = 0.0
    _margin: np.ndarray = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._margin = balance_margin_cm(self.run)

    def rate(self, sim_t: float) -> float:
        factor = 1.0
        for start, end, slow in self.slow:
            if start - _RAMP_S < sim_t < end + _RAMP_S:
                edge = min(sim_t - (start - _RAMP_S), (end + _RAMP_S) - sim_t) / _RAMP_S
                ease = min(max(edge, 0.0), 1.0)
                factor = min(factor, 1.0 + (slow - 1.0) * ease)
        return factor

    def sim_times(self, fps: int = FPS) -> list[float]:
        times, t = [], self.t0
        while t < self.t1:
            times.append(t)
            t += self.rate(t) / fps
        return times

    def duration(self, fps: int = FPS) -> float:
        return len(self.sim_times(fps)) / fps

    def begin(self) -> None:
        self.studio.reset_camera()

    def frame(self, sim_t: float) -> np.ndarray:
        width, height = self.studio.width, self.studio.height
        progress = (sim_t - self.t0) / max(self.t1 - self.t0, 1e-6)
        image = Image.fromarray(
            self.studio.render(
                self.run,
                sim_t,
                progress=progress,
                margin_cm=self._margin,
                markers=self.markers,
                shift=self.shift,
            )
        )
        sprites: list[overlay.Sprite] = []
        if self.hero is not None:
            image = overlay.hero_shade(image)
            sprites.append(overlay.hero_text((width, height), *self.hero))
        tag, color = None, overlay.ORANGE
        for start, label, tint in self.tags:
            if sim_t >= start:
                tag, color = label, tint
        sprites += overlay.hud(
            (width, height),
            robot=self.robot_title,
            policy=self.policy_title,
            tag=tag,
            tag_color=color,
            now_s=sim_t,
            credit=self.credit,
            slow=self.rate(sim_t),
            show_clock=self.hero is None,
        )
        lines: Sequence[str] = ()
        for start, end, words in self.captions:
            if start <= sim_t < end:
                lines = words
        if lines:
            sprites.append(
                overlay.caption((width, height), lines, y_from_bottom=190 if self.timeline else 70)
            )
        if self.evidence is not None and sim_t >= self.evidence[0]:
            shown = (sim_t - self.evidence[0]) / 0.7
            sprites.append(overlay.evidence_panel(self.evidence[1], self.evidence[2], shown))
        if self.timeline:
            box = (int(width * 0.11), height - 118, int(width * 0.89), height - 56)
            sprites.append(overlay.tilt_timeline(self.run, box, sim_t))
        return overlay.to_array(overlay.paste(image, sprites))


@dataclass
class SplitClip:
    """Two clips side by side, advanced on the same simulation clock."""

    left: Clip
    right: Clip

    def sim_times(self, fps: int = FPS) -> list[float]:
        return self.left.sim_times(fps)

    def duration(self, fps: int = FPS) -> float:
        return self.left.duration(fps)

    def begin(self) -> None:
        self.left.begin()
        self.right.begin()

    def frame(self, sim_t: float) -> np.ndarray:
        a = self.left.frame(sim_t)
        b = self.right.frame(sim_t)
        out = np.concatenate([a, b], axis=1)
        out[:, a.shape[1] - 2 : a.shape[1] + 2] = overlay.BG
        return out


@dataclass
class Card:
    """A still or animated full-frame card; ``draw(progress)`` returns an image."""

    seconds: float
    draw: Callable[[float], Image.Image]
    #: Maps progress (0..1) to a cache key; equal keys reuse the previous picture.
    key: Callable[[float], object] = lambda progress: progress
    _cache: dict = field(default_factory=dict, repr=False)

    def begin(self) -> None:
        self._cache.clear()

    def sim_times(self, fps: int = FPS) -> list[float]:
        return [i / fps for i in range(int(self.seconds * fps))]

    def duration(self, fps: int = FPS) -> float:
        return self.seconds

    def frame(self, t: float) -> np.ndarray:
        progress = t / self.seconds
        key = self.key(progress)
        if key not in self._cache:
            self._cache.clear()
            self._cache[key] = overlay.to_array(self.draw(progress))
        return self._cache[key]


def frames(scenes: Sequence, fps: int = FPS, fade_s: float = 0.25) -> Iterator[np.ndarray]:
    """All frames of the film, each scene fading in and out."""
    fade_frames = max(int(fade_s * fps), 1)
    for scene in scenes:
        scene.begin()
        times = scene.sim_times(fps)
        for index, sim_t in enumerate(times):
            image = scene.frame(sim_t)
            edge = min(index, len(times) - 1 - index)
            if edge < fade_frames:
                image = (image * ((edge + 1) / (fade_frames + 1))).astype(np.uint8)
            yield image


def write_mp4(path: Path, frame_iter: Iterator[np.ndarray], fps: int = FPS) -> Path:
    import imageio.v2 as imageio

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = imageio.get_writer(
        str(path),
        fps=fps,
        codec="libx264",
        pixelformat="yuv420p",
        macro_block_size=1,
        ffmpeg_params=["-crf", "19", "-preset", "medium", "-movflags", "+faststart"],
    )
    try:
        for image in frame_iter:
            writer.append_data(image)
    finally:
        writer.close()
    return path


def write_webp(
    path: Path, frame_iter: Iterator[np.ndarray], fps: int = FPS, width: int = 800, step: int = 2
) -> Path:
    """Animated WebP for READMEs: every ``step``-th frame, scaled to ``width``."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    images = []
    for index, image in enumerate(frame_iter):
        if index % step:
            continue
        picture = Image.fromarray(image)
        scale = width / picture.width
        images.append(picture.resize((width, round(picture.height * scale)), Image.LANCZOS))
    images[0].save(
        path,
        save_all=True,
        append_images=images[1:],
        duration=round(1000 * step / fps),
        loop=0,
        quality=72,
        method=6,
    )
    return path
