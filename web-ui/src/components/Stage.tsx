import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { decodeOverlay, decodePoses } from "../decode";
import { outcomeTone } from "../format";
import type { Playback } from "../playback";
import { canRecordClip, clipFileName, clipWindow, recordClip, saveBlob } from "../clip";
import { prefersReducedMotion } from "../prefs";
import { RobotView } from "../robotView";
import type { RobotInfo, RunDetail, SceneDescription } from "../types";

/** Where a stage gets its meshes and each run's poses from, and what to call it. */
export interface StageSource {
  /** Identity of the meshes: they are fetched again when it changes. */
  key: string;
  /** The camera is put back on the subject only when this changes (defaults to `key`). */
  cameraKey?: string;
  title: string;
  credit: string;
  heightCm: number;
  /** Whether the run carries balance markers (support area, weight point, shove); a robot's does. */
  markers?: boolean;
  scene: () => Promise<SceneDescription>;
  mesh: (id: number) => Promise<ArrayBuffer>;
  poses: (run: RunDetail) => Promise<ArrayBuffer>;
  overlay: (run: RunDetail) => Promise<ArrayBuffer>;
}

export function robotSource(robot: RobotInfo): StageSource {
  return {
    key: robot.key,
    title: robot.title,
    credit: robot.credit,
    heightCm: robot.heightCm,
    scene: () => api.scene(robot.key),
    mesh: (id) => api.mesh(robot.key, id),
    poses: (run) => api.poses(run.id),
    overlay: (run) => api.overlay(run.id),
  };
}

interface Props {
  source: StageSource;
  run: RunDetail | null;
  playback: Playback;
  /** A second view on the same clock (side-by-side compare): it never drives playback itself. */
  follower?: boolean;
  /** What to call the run in the corner; defaults to its policy (see `pairName` for pairs). */
  label?: string;
}

type Status = "loading" | "ready" | "error";

/** The 3D view: the real robot's meshes, the run replayed on them, and a few viewing controls. */
export function Stage({ source, run, playback, follower = false, label }: Props) {
  const src = useRef(source);
  src.current = source;
  const framedFor = useRef<string | null>(null);
  const needFrame = useRef(true);
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<RobotView | null>(null);
  const [status, setStatus] = useState<Status>("loading");
  const [error, setError] = useState<string | null>(null);
  const [loadedRobot, setLoadedRobot] = useState<string | null>(null);
  const [follow, setFollow] = useState(true);
  const [overlays, setOverlays] = useState(true);
  const [lite, setLite] = useState(false);
  const [recording, setRecording] = useState(false);

  // One view for the life of the stage.
  useEffect(() => {
    if (!host.current) return;
    const v = new RobotView(host.current);
    v.onLite = () => setLite(true);
    setLite(v.lite);
    view.current = v;
    let last = performance.now();
    let frame = 0;
    const loop = (now: number) => {
      if (!follower) playback.tick(Math.min((now - last) / 1000, 0.1));
      last = now;
      v.setTime(playback.getSnapshot().time);
      frame = requestAnimationFrame(loop);
    };
    frame = requestAnimationFrame(loop);
    return () => {
      cancelAnimationFrame(frame);
      v.dispose();
      view.current = null;
    };
  }, [playback, follower]);

  // The meshes, once per subject.
  useEffect(() => {
    let cancelled = false;
    const subject = src.current;
    setStatus("loading");
    setError(null);
    (async () => {
      try {
        const description = await subject.scene();
        const reframe = framedFor.current !== (subject.cameraKey ?? subject.key);
        framedFor.current = subject.cameraKey ?? subject.key;
        needFrame.current = reframe;
        await view.current?.loadRobot(subject.key, subject.heightCm, description, (id) => subject.mesh(id), reframe);
        if (cancelled) return;
        setLoadedRobot(subject.key);
        setStatus("ready");
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : String(e));
        setStatus("error");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [source.key, source.heightCm]);

  // The run's poses and overlay, whenever the run changes.
  useEffect(() => {
    if (!run || loadedRobot !== src.current.key) return;
    let cancelled = false;
    (async () => {
      try {
        const [posesBuffer, overlayBuffer, description] = await Promise.all([
          src.current.poses(run),
          src.current.overlay(run),
          src.current.scene(),
        ]);
        if (cancelled) return;
        view.current?.setRun(
          decodePoses(posesBuffer, description.bodyCount),
          decodeOverlay(overlayBuffer),
          run.fps,
          needFrame.current,
        );
        needFrame.current = false;
        // Start a moment before the shove, like the films, and play.
        if (!follower) {
          const start = run.events.pushAt !== null ? Math.max(run.events.pushAt - 1.2, 0) : 0;
          playback.load(run.duration, run.events, start);
          // Someone who asked their system for less motion presses play themselves.
          if (prefersReducedMotion()) playback.pause();
          else playback.play();
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : String(e));
          setStatus("error");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [run, loadedRobot, playback, follower]);

  useEffect(() => {
    view.current?.setOptions({ follow, overlays });
  }, [follow, overlays]);

  const saveClip = async () => {
    const v = view.current;
    if (!v || !run || recording) return;
    setRecording(true);
    try {
      const blob = await recordClip(
        v.canvas,
        playback,
        clipWindow(run.events, run.duration),
        `Simulation · ${source.credit}`,
      );
      saveBlob(blob, clipFileName([source.title, run.policyTitle, run.title]));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRecording(false);
    }
  };

  const tone = run ? outcomeTone(run.outcome) : "ok";
  return (
    <div
      className={`stage${follower ? " follower" : ""}`}
      data-state={status}
      data-run={run?.id ?? ""}
      data-testid={follower ? "stage-b" : "stage"}
    >
      <div ref={host} className="stage-canvas" />
      {status === "loading" && <div className="stage-note">Loading {source.title}…</div>}
      {status === "error" && (
        <div className="stage-note error" role="alert">
          Could not show {source.title}: {error}
        </div>
      )}
      <div className="hud tl">
        <span className="hud-robot">{source.title.toUpperCase()}</span>
        {run && (label ?? run.policyTitle) !== source.title && <span>{label ?? run.policyTitle}</span>}
      </div>
      {run && <div className={`hud tr badge-${tone}`}>{run.outcomeText}</div>}
      {overlays && run && source.markers !== false && (
        <ul className="hud key3d" aria-label="What the markers show">
          <li>
            <i className="key-area" /> Where the feet hold it up
          </li>
          <li>
            <i className="key-dot" /> Where its weight would land
          </li>
          {run.events.pushAt !== null && (
            <li>
              <i className="key-arrow" /> The shove
            </li>
          )}
        </ul>
      )}
      {lite && (
        <div className="hud lite" role="status">
          Simplified view: this computer is drawing 3D without graphics acceleration.
        </div>
      )}
      <div className="hud bl">Simulation · {source.credit}</div>
      <div className="hud br toolbar" role="toolbar" aria-label="View">
        <button type="button" aria-label="Frame the robot" title="Frame the robot" onClick={() => view.current?.frameCamera()}>
          <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
            <path d="M2 6V2h4M12 2h4v4M16 12v4h-4M6 16H2v-4" />
            <circle cx="9" cy="9" r="2.4" />
          </svg>
        </button>
        <button
          type="button"
          aria-label="Camera follows the robot"
          title="Camera follows the robot"
          aria-pressed={follow}
          onClick={() => setFollow((v) => !v)}
        >
          <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
            <path d="M1.5 9C4 4.5 14 4.5 16.5 9 14 13.5 4 13.5 1.5 9Z" />
            <circle cx="9" cy="9" r="2.2" className="solid" />
          </svg>
        </button>
        {!follower && canRecordClip() && run && (
          <button
            type="button"
            aria-label="Save a clip of this run"
            title={recording ? "Recording…" : "Save a clip of this run"}
            aria-pressed={recording}
            disabled={recording || status !== "ready"}
            onClick={() => void saveClip()}
          >
            <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
              <rect x="1.5" y="4" width="11" height="10" rx="2" />
              <path d="M12.5 8 16.5 5.5v7L12.5 10Z" />
            </svg>
          </button>
        )}
        {source.markers !== false && (
        <button
          type="button"
          aria-label="Show balance and contact markers"
          title="Show balance and contact markers"
          aria-pressed={overlays}
          onClick={() => setOverlays((v) => !v)}
        >
          <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
            <path d="M3 13 9 16l6-3-6-3Z" />
            <path d="M9 2v8" />
            <circle cx="9" cy="12.6" r="1.4" className="amber" />
          </svg>
        </button>
        )}
      </div>
    </div>
  );
}
