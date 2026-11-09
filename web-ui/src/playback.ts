import type { RunEvents } from "./types";

/** Slow motion factor of the films, eased in and out over this many seconds of run time. */
export const SLOW_FACTOR = 0.3;
const RAMP_S = 0.25;
/** A finished replay holds its last frame this long before looping. */
export const HOLD_S = 1.2;

/**
 * Playback rate at run time `t`: 1, or SLOW_FACTOR around the shove and the fall when
 * `auto` is on (the same window the films slow down), times the user's chosen `speed`.
 */
export function rateAt(t: number, events: RunEvents | null, auto: boolean, speed: number): number {
  let factor = 1;
  if (auto && events && events.pushAt !== null) {
    const start = events.pushAt - 0.05;
    const end = events.fallAt !== null ? events.fallAt + 0.5 : events.pushAt + 0.9;
    if (t > start - RAMP_S && t < end + RAMP_S) {
      const edge = Math.min(t - (start - RAMP_S), end + RAMP_S - t) / RAMP_S;
      const ease = Math.min(Math.max(edge, 0), 1);
      factor = 1 + (SLOW_FACTOR - 1) * ease;
    }
  }
  return factor * speed;
}

/** Which two 50 Hz frames surround `t`, and how far between them (for smooth playback). */
export function frameAt(t: number, fps: number, frames: number): { i0: number; i1: number; w: number } {
  if (frames <= 1) return { i0: 0, i1: 0, w: 0 };
  // Frame k (0-based) is recorded at (k + 1) / fps.
  const position = Math.min(Math.max(t * fps - 1, 0), frames - 1);
  const i0 = Math.floor(position);
  return { i0, i1: Math.min(i0 + 1, frames - 1), w: position - i0 };
}

export function formatTime(t: number): string {
  return `${Math.max(t, 0).toFixed(1)} s`;
}

export interface PlaybackState {
  time: number;
  playing: boolean;
  duration: number;
  speed: number;
  auto: boolean;
  rate: number;
}

type Listener = () => void;

/** Framework-free playback clock; React reads it through subscribe/getSnapshot. */
export class Playback {
  private state: PlaybackState = {
    time: 0,
    playing: false,
    duration: 0,
    speed: 1,
    auto: true,
    rate: 1,
  };
  private events: RunEvents | null = null;
  private listeners = new Set<Listener>();

  subscribe = (listener: Listener): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  getSnapshot = (): PlaybackState => this.state;

  private set(patch: Partial<PlaybackState>): void {
    this.state = { ...this.state, ...patch };
    for (const listener of this.listeners) listener();
  }

  load(duration: number, events: RunEvents, startAt = 0): void {
    this.events = events;
    this.set({ duration, time: startAt, rate: rateAt(startAt, events, this.state.auto, this.state.speed) });
  }

  play(): void {
    // Pressing play at the very end starts over.
    const atEnd = this.state.time >= this.state.duration;
    this.set({ playing: true, time: atEnd ? 0 : this.state.time });
  }

  pause(): void {
    this.set({ playing: false });
  }

  toggle(): void {
    if (this.state.playing) this.pause();
    else this.play();
  }

  seek(time: number): void {
    const t = Math.min(Math.max(time, 0), this.state.duration);
    this.set({ time: t, rate: rateAt(t, this.events, this.state.auto, this.state.speed) });
  }

  setSpeed(speed: number): void {
    this.set({ speed, rate: rateAt(this.state.time, this.events, this.state.auto, speed) });
  }

  setAuto(auto: boolean): void {
    this.set({ auto, rate: rateAt(this.state.time, this.events, auto, this.state.speed) });
  }

  /** Advance by `dtSeconds` of wall-clock time. Loops back after holding the last frame. */
  tick(dtSeconds: number): void {
    if (!this.state.playing || this.state.duration <= 0) return;
    const rate = rateAt(this.state.time, this.events, this.state.auto, this.state.speed);
    let time = this.state.time + dtSeconds * rate;
    if (time >= this.state.duration + HOLD_S) time = 0;
    this.set({ time, rate });
  }
}
