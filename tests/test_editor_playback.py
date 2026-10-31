"""Tests for the pure trace-playback state machine."""

from __future__ import annotations

from creature_lab.editor.playback import EditorPlayback
from creature_lab.schema import EpisodeTrace, FrameState


def _trace(n: int) -> EpisodeTrace:
    frames = [
        FrameState.model_validate(
            {
                "t": i * 0.1,
                "parts": {"root": {"position": (0.0, 0.0, 0.0)}},
                "score": float(i),
            }
        )
        for i in range(n)
    ]
    return EpisodeTrace.model_validate(
        {
            "run_id": "test",
            "creature_name": "x",
            "task_name": "y",
            "backend": "pybullet",
            "frames": [f.model_dump(mode="json") for f in frames],
            "score": float(n - 1),
        }
    )


def test_load_resets_to_first_frame_paused():
    playback = EditorPlayback()
    playback.load(_trace(5))

    assert playback.frame_index == 0
    assert playback.playing is False
    assert playback.frame_count == 5
    assert playback.current_frame().t == 0.0


def test_play_pause_toggle():
    playback = EditorPlayback()
    playback.load(_trace(5))

    playback.play()
    assert playback.playing is True
    playback.pause()
    assert playback.playing is False
    playback.toggle()
    assert playback.playing is True
    playback.toggle()
    assert playback.playing is False


def test_play_is_a_no_op_with_no_trace_or_single_frame():
    playback = EditorPlayback()
    playback.play()
    assert playback.playing is False

    playback.load(_trace(1))
    playback.play()
    assert playback.playing is False  # nothing to animate


def test_advance_moves_forward_at_configured_fps():
    playback = EditorPlayback(fps=10.0)  # one frame per 0.1s
    playback.load(_trace(5))
    playback.play()

    changed = playback.advance(0.1)
    assert changed is True
    assert playback.frame_index == 1

    changed = playback.advance(0.05)  # not enough time for another frame yet
    assert changed is False
    assert playback.frame_index == 1


def test_advance_does_nothing_when_paused():
    playback = EditorPlayback(fps=10.0)
    playback.load(_trace(5))

    changed = playback.advance(1.0)

    assert changed is False
    assert playback.frame_index == 0


def test_advance_loops_by_default():
    playback = EditorPlayback(fps=10.0, loop=True)
    playback.load(_trace(3))
    playback.play()

    playback.advance(0.5)  # far more than needed to reach the end and wrap

    assert playback.playing is True
    assert 0 <= playback.frame_index < 3


def test_advance_stops_at_end_when_not_looping():
    playback = EditorPlayback(fps=10.0, loop=False)
    playback.load(_trace(3))
    playback.play()

    playback.advance(1.0)  # far more than needed to reach the end

    assert playback.frame_index == 2
    assert playback.playing is False


def test_seek_clamps_to_valid_range():
    playback = EditorPlayback()
    playback.load(_trace(5))

    playback.seek(100)
    assert playback.frame_index == 4

    playback.seek(-5)
    assert playback.frame_index == 0


def test_seek_with_no_trace_is_a_no_op():
    playback = EditorPlayback()
    playback.seek(3)
    assert playback.frame_index == 0


def test_step_moves_by_delta_and_pauses():
    playback = EditorPlayback()
    playback.load(_trace(5))
    playback.play()

    playback.step(2)
    assert playback.frame_index == 2
    assert playback.playing is False

    playback.step(-1)
    assert playback.frame_index == 1


def test_to_start_resets_index():
    playback = EditorPlayback()
    playback.load(_trace(5))
    playback.seek(3)

    playback.to_start()
    assert playback.frame_index == 0


def test_current_frame_none_with_no_trace_loaded():
    playback = EditorPlayback()
    assert playback.current_frame() is None
    assert playback.frame_count == 0
