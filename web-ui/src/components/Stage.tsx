import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { decodeOverlay, decodePoses } from "../decode";
import { outcomeTone } from "../format";
import type { Playback } from "../playback";
import { RobotView } from "../robotView";
import type { RobotInfo, RunDetail } from "../types";

interface Props {
  robot: RobotInfo;
  run: RunDetail | null;
  playback: Playback;
}

type Status = "loading" | "ready" | "error";

/** The 3D view: the real robot's meshes, the run replayed on them, and a few viewing controls. */
export function Stage({ robot, run, playback }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<RobotView | null>(null);
  const [status, setStatus] = useState<Status>("loading");
  const [error, setError] = useState<string | null>(null);
  const [loadedRobot, setLoadedRobot] = useState<string | null>(null);
  const [follow, setFollow] = useState(true);
  const [overlays, setOverlays] = useState(true);

  // One view for the life of the stage.
  useEffect(() => {
    if (!host.current) return;
    const v = new RobotView(host.current);
    view.current = v;
    let last = performance.now();
    let frame = 0;
    const loop = (now: number) => {
      playback.tick(Math.min((now - last) / 1000, 0.1));
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
  }, [playback]);

  // The robot's meshes, once per robot.
  useEffect(() => {
    let cancelled = false;
    setStatus("loading");
    setError(null);
    (async () => {
      try {
        const description = await api.scene(robot.key);
        await view.current?.loadRobot(robot.key, robot.heightCm, description, (id) => api.mesh(robot.key, id));
        if (cancelled) return;
        setLoadedRobot(robot.key);
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
  }, [robot.key, robot.heightCm]);

  // The run's poses and overlay, whenever the run changes.
  useEffect(() => {
    if (!run || loadedRobot !== run.robot) return;
    let cancelled = false;
    (async () => {
      try {
        const [posesBuffer, overlayBuffer, description] = await Promise.all([
          api.poses(run.id),
          api.overlay(run.id),
          api.scene(run.robot),
        ]);
        if (cancelled) return;
        view.current?.setRun(decodePoses(posesBuffer, description.bodyCount), decodeOverlay(overlayBuffer), run.fps);
        // Start a moment before the shove, like the films, and play.
        const start = run.events.pushAt !== null ? Math.max(run.events.pushAt - 1.2, 0) : 0;
        playback.load(run.duration, run.events, start);
        playback.play();
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
  }, [run, loadedRobot, playback]);

  useEffect(() => {
    view.current?.setOptions({ follow, overlays });
  }, [follow, overlays]);

  const tone = run ? outcomeTone(run.outcome) : "ok";
  return (
    <div className="stage" data-state={status} data-run={run?.id ?? ""} data-testid="stage">
      <div ref={host} className="stage-canvas" />
      {status === "loading" && <div className="stage-note">Loading {robot.title}…</div>}
      {status === "error" && (
        <div className="stage-note error" role="alert">
          Could not show {robot.title}: {error}
        </div>
      )}
      <div className="hud tl">
        <span className="hud-robot">{robot.title.toUpperCase()}</span>
        {run && <span>{run.policyTitle}</span>}
      </div>
      {run && <div className={`hud tr badge-${tone}`}>{run.outcomeText}</div>}
      <div className="hud bl">Simulation · {robot.credit}</div>
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
      </div>
    </div>
  );
}
