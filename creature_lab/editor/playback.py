"""Trace playback state, decoupled from simulation and from Viser.

Before this existed, clicking Simulate synchronously replayed every frame inside the
same call (``time.sleep`` per frame) before the button handler returned - the browser
looked frozen for the length of the episode. Now a finished trace is *loaded* here and
the caller drives ``advance(dt)`` from its own loop; playback is just data plus a small
state machine, so it is fully unit-testable without a server or physics.
"""

from __future__ import annotations

from dataclasses import dataclass

from creature_lab.schema import EpisodeTrace, FrameState

DEFAULT_FPS = 30.0


@dataclass
class EditorPlayback:
    """Frame-index playback over one loaded trace, advanced by wall-clock time."""

    trace: EpisodeTrace | None = None
    frame_index: int = 0
    playing: bool = False
    loop: bool = True
    speed: float = 1.0
    fps: float = DEFAULT_FPS
    _accum: float = 0.0

    def load(self, trace: EpisodeTrace) -> None:
        """Load a new trace, paused at its first frame."""
        self.trace = trace
        self.frame_index = 0
        self.playing = False
        self._accum = 0.0

    def clear(self) -> None:
        """Drop the loaded trace, back to the empty 'nothing to play' state."""
        self.trace = None
        self.frame_index = 0
        self.playing = False
        self._accum = 0.0

    @property
    def frame_count(self) -> int:
        return len(self.trace.frames) if self.trace is not None else 0

    def current_frame(self) -> FrameState | None:
        if self.trace is None or not self.trace.frames:
            return None
        return self.trace.frames[self.frame_index]

    def play(self) -> None:
        if self.trace is not None and self.frame_count > 1:
            self.playing = True

    def pause(self) -> None:
        self.playing = False

    def toggle(self) -> None:
        self.pause() if self.playing else self.play()

    def to_start(self) -> None:
        self.frame_index = 0
        self._accum = 0.0

    def seek(self, frame_index: int) -> None:
        """Jump to a frame directly (used by the timeline scrubber)."""
        if self.frame_count == 0:
            return
        self.frame_index = max(0, min(self.frame_count - 1, frame_index))
        self._accum = 0.0

    def step(self, delta: int) -> None:
        """Move by ``delta`` frames and pause (manual stepping implies manual control)."""
        self.playing = False
        self.seek(self.frame_index + delta)

    def advance(self, dt: float) -> bool:
        """Advance playback by ``dt`` wall-clock seconds. Returns True if the frame changed."""
        if not self.playing or self.frame_count < 2:
            return False
        self._accum += dt * self.speed
        step_dt = 1.0 / self.fps
        changed = False
        while self._accum >= step_dt:
            self._accum -= step_dt
            self.frame_index += 1
            changed = True
            if self.frame_index >= self.frame_count:
                if self.loop:
                    self.frame_index = 0
                else:
                    self.frame_index = self.frame_count - 1
                    self.playing = False
                    break
        return changed
