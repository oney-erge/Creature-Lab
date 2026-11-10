import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { outcomeTone } from "../format";
import { Playback } from "../playback";
import type { BuildResponse, CreatureCatalog, CreatureParam } from "../types";
import { Stage, type StageSource } from "./Stage";
import { Timeline } from "./Timeline";

interface Props {
  preset: string;
  onPreset: (preset: string) => void;
  /** Opens the part-by-part classic editor for the current preset. */
  onClassic: (preset: string) => void;
  classicNote: string | null;
}

const PRESET_BLURB: Record<string, string> = {
  quadruped: "Four legs, a steady crawl.",
  hexapod: "Six legs: slower, hard to topple.",
  worm: "Segments that wave forward.",
  humanoid: "Two legs and arms; the hard one.",
};

function digits(step: number): number {
  return step >= 1 ? 0 : Math.min(3, Math.ceil(-Math.log10(step)));
}

function Slider({ param, value, onChange }: { param: CreatureParam; value: number; onChange: (v: number) => void }) {
  return (
    <label className="slider">
      <span className="slider-head">
        <span>{param.label}</span>
        <output className="mono">{value.toFixed(digits(param.step))}</output>
      </span>
      <input
        type="range"
        min={param.min}
        max={param.max}
        step={param.step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        aria-label={param.label}
      />
    </label>
  );
}

/** Design a preset creature, see it in 3D, and run it toward a goal: the app's own editor. */
export function Editor({ preset, onPreset, onClassic, classicNote }: Props) {
  const playback = useMemo(() => new Playback(), []);
  const [catalog, setCatalog] = useState<CreatureCatalog | null>(null);
  const [goal, setGoal] = useState("move_forward");
  const [params, setParams] = useState<Record<string, number>>({});
  const [built, setBuilt] = useState<BuildResponse | null>(null);
  const [result, setResult] = useState<BuildResponse | null>(null);
  const [busy, setBusy] = useState<"preview" | "run" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const ticket = useRef(0);

  useEffect(() => {
    api
      .creaturePresets()
      .then(setCatalog)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  const current = catalog?.presets.find((p) => p.key === preset) ?? catalog?.presets[0] ?? null;

  // A new preset starts from its own defaults.
  useEffect(() => {
    if (!current) return;
    setParams(Object.fromEntries(current.params.map((p) => [p.key, p.initial])));
    setResult(null);
  }, [current?.key]);

  // Whenever the design changes, show it at rest (after a short pause for sliders being dragged).
  useEffect(() => {
    if (!current || Object.keys(params).length === 0) return;
    const mine = ++ticket.current;
    setBusy("preview");
    const timer = setTimeout(() => {
      api
        .buildCreature({ preset: current.key, params, goal, simulate: false })
        .then((response) => {
          if (mine !== ticket.current) return;
          setBuilt(response);
          setResult(null);
          setError(null);
        })
        .catch((e) => mine === ticket.current && setError(e instanceof Error ? e.message : String(e)))
        .finally(() => mine === ticket.current && setBusy(null));
    }, 160);
    return () => clearTimeout(timer);
  }, [current?.key, params, goal]);

  const run = async () => {
    if (!current) return;
    ticket.current += 1; // a preview still in flight must not replace the run
    setBusy("run");
    setError(null);
    try {
      const response = await api.buildCreature({ preset: current.key, params, goal, simulate: true });
      setBuilt(response);
      setResult(response);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const source: StageSource | null = useMemo(() => {
    if (!built || !current) return null;
    const id = built.scene.robot;
    return {
      key: id,
      cameraKey: current.key,
      title: current.label,
      credit: "Creature Lab preset",
      heightCm: built.run.sizeCm,
      markers: false,
      scene: () => Promise.resolve(built.scene),
      mesh: (mesh) => api.creatureMesh(id, mesh),
      poses: () => api.creaturePoses(id),
      overlay: () => api.creatureOverlay(id),
    };
  }, [built?.scene.robot, current?.key]);

  const reset = () => current && setParams(Object.fromEntries(current.params.map((p) => [p.key, p.initial])));
  const changed = current ? current.params.some((p) => params[p.key] !== p.initial) : false;

  return (
    <div className="shell editor">
      <aside className="rail-col" aria-label="Design">
        <section>
          <h2 className="eyebrow">Start from</h2>
          <div className="presets big">
            {catalog?.presets.map((p) => (
              <button
                key={p.key}
                type="button"
                className={`preset-card${p.key === current?.key ? " selected" : ""}`}
                aria-pressed={p.key === current?.key}
                onClick={() => onPreset(p.key)}
              >
                <span className="name">{p.label}</span>
                <span className="sub">{PRESET_BLURB[p.key] ?? ""}</span>
              </button>
            ))}
          </div>
        </section>

        <section>
          <h2 className="eyebrow">Goal</h2>
          <div className="seg stacked" role="group" aria-label="Goal">
            {catalog?.goals.map((g) => (
              <button key={g.key} type="button" aria-pressed={goal === g.key} onClick={() => setGoal(g.key)}>
                {g.label}
              </button>
            ))}
          </div>
        </section>

        <section>
          <div className="row between">
            <h2 className="eyebrow">Shape and motion</h2>
            <button type="button" className="link" disabled={!changed} onClick={reset}>
              Reset
            </button>
          </div>
          <div className="sliders">
            {current?.params.map((param) => (
              <Slider
                key={`${current.key}-${param.key}`}
                param={param}
                value={params[param.key] ?? param.initial}
                onChange={(v) => setParams((old) => ({ ...old, [param.key]: v }))}
              />
            ))}
          </div>
        </section>
      </aside>

      <main className="center" id="player" tabIndex={-1}>
        {source && built ? (
          <Stage source={source} run={built.run} playback={playback} />
        ) : (
          <div className="stage">
            <div className="stage-note">{error ? "" : "Building…"}</div>
          </div>
        )}
        {result && <Timeline playback={playback} run={result.run} />}
      </main>

      <aside className="side-col" aria-label="Run">
        <section className="panel">
          <h2 className="eyebrow">Try it</h2>
          <p className="body">
            {result
              ? "Change a slider and the creature goes back to rest; run it again to see what changed."
              : "Shape the creature on the left, then run it toward the goal."}
          </p>
          <button type="button" className="primary big" disabled={!current || busy === "run"} onClick={() => void run()}>
            {busy === "run" ? "Running…" : "Run simulation"}
          </button>
          {error && (
            <p className="warn" role="alert">
              {error}
            </p>
          )}
        </section>

        {result && (
          <section className="panel" data-testid="result">
            <h2 className="eyebrow">What happened · {result.run.title}</h2>
            <p className={`verdict tone-${outcomeTone(result.run.outcome)}`}>{result.run.verdict}</p>
            {result.run.causeText && <p className="body">{result.run.causeText}</p>}
            <ul className="evidence">
              {result.run.evidence.map((e) => (
                <li key={e.label} title={e.detail}>
                  <span className={`bar ${e.label === "Stayed upright" && e.value === "No" ? "bad" : "ok"}`} />
                  <span className="ev-text">
                    <span className="ev-label">{e.label}</span>
                    <span className="ev-value">{e.value}</span>
                  </span>
                </li>
              ))}
            </ul>
          </section>
        )}

        <section className="panel">
          <h2 className="eyebrow">Go further</h2>
          <p className="body">
            Edit parts, joints and motors one by one in the classic editor. It opens in a new tab.
          </p>
          <button type="button" className="ghost" onClick={() => current && onClassic(current.key)}>
            Open the classic editor
          </button>
          {classicNote && (
            <p className="muted small" role="status">
              {classicNote}
            </p>
          )}
        </section>
      </aside>
    </div>
  );
}
