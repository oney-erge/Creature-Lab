import { useSyncExternalStore } from "react";
import { formatTime, type Playback } from "../playback";
import type { RunDetail } from "../types";

const W = 600;
const H = 72;
const FALL_DEG = 60;

function pathFor(tilt: number[]): string {
  if (tilt.length < 2) return "";
  return tilt
    .map((deg, i) => {
      const x = (W * i) / (tilt.length - 1);
      const y = H - (H * Math.min(deg, 100)) / 100;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
}

interface Props {
  playback: Playback;
  run: RunDetail | null;
}

/** Lean angle over the run, with the shove, the fall, the get-up, and a draggable playhead. */
export function Timeline({ playback, run }: Props) {
  const state = useSyncExternalStore(playback.subscribe, playback.getSnapshot);
  const duration = run?.duration ?? 0;
  const x = (t: number) => (duration > 0 ? (W * t) / duration : 0);
  const events = run?.events;
  const slow = state.rate < 0.99;

  return (
    <section className="timeline" aria-label="Timeline">
      <div className="timeline-bar">
        <button
          type="button"
          className="play"
          onClick={() => playback.toggle()}
          aria-label={state.playing ? "Pause" : "Play"}
          disabled={!run}
        >
          {state.playing ? (
            <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
              <rect x="2" y="1" width="3.5" height="12" rx="1" />
              <rect x="8.5" y="1" width="3.5" height="12" rx="1" />
            </svg>
          ) : (
            <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
              <path d="M3 1.5 12.5 7 3 12.5Z" />
            </svg>
          )}
        </button>
        <span className="mono clock" data-testid="clock">
          {formatTime(state.time)} / {formatTime(duration)}
        </span>
        <span className={`slow-pill${slow ? " on" : ""}`} aria-live="polite">
          {slow ? `${state.rate.toFixed(2).replace(/0$/, "")}× slow motion` : "Normal speed"}
        </span>
        <div className="spacer" />
        <div className="seg small" role="group" aria-label="Playback speed">
          {[0.25, 0.5, 1].map((s) => (
            <button
              key={s}
              type="button"
              aria-pressed={state.speed === s}
              onClick={() => playback.setSpeed(s)}
            >
              {s}×
            </button>
          ))}
        </div>
        <label className="check">
          <input
            type="checkbox"
            checked={state.auto}
            onChange={(e) => playback.setAuto(e.target.checked)}
          />
          Slow down at the fall
        </label>
      </div>

      <div className="chart-wrap">
        <svg
          viewBox={`0 0 ${W} ${H + 8}`}
          preserveAspectRatio="none"
          role="img"
          aria-label={run ? `Lean angle over the run. ${run.verdict}` : "Lean angle chart"}
        >
          <rect x="0" y="0" width={W} height={H} className="chart-bg" />
          <line
            x1="0"
            x2={W}
            y1={H - (H * FALL_DEG) / 100}
            y2={H - (H * FALL_DEG) / 100}
            className="fall-line"
          />
          {events?.pushAt != null && (
            <rect
              x={x(events.pushAt)}
              y="0"
              width={Math.max(x(events.pushFor), 5)}
              height={H}
              className="push-band"
            />
          )}
          {events?.recoveredAt != null && (
            <line x1={x(events.recoveredAt)} x2={x(events.recoveredAt)} y1="0" y2={H} className="up-line" />
          )}
          {events?.fallAt != null && (
            <line x1={x(events.fallAt)} x2={x(events.fallAt)} y1="0" y2={H} className="fall-mark" />
          )}
          {run && <polyline points={pathFor(run.tilt)} className="tilt" />}
          <rect x="0" y={H + 2} width={W} height="5" rx="2.5" className="rail" />
          <rect x="0" y={H + 2} width={x(state.time)} height="5" rx="2.5" className="rail-fill" />
          <line x1={x(state.time)} x2={x(state.time)} y1="0" y2={H} className="playhead" />
        </svg>
        <input
          className="scrub"
          type="range"
          min={0}
          max={duration || 1}
          step={0.02}
          value={Math.min(state.time, duration || 1)}
          disabled={!run}
          aria-label="Playback position"
          aria-valuetext={formatTime(state.time)}
          onChange={(e) => playback.seek(Number(e.target.value))}
        />
      </div>

      <div className="legend">
        <span>
          <i className="swatch push" /> Shove
        </span>
        <span>
          <i className="swatch fall" /> Fall line (60°)
        </span>
        <span>
          <i className="swatch tilt" /> Lean angle
        </span>
        <span>
          <i className="swatch up" /> Back on its feet
        </span>
      </div>
    </section>
  );
}
