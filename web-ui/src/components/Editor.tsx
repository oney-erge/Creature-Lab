import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { changeLine, limitLine, outcomeTone, shoveSentence, shoveStrength } from "../format";
import { Playback } from "../playback";
import type { BuildResponse, CreatureCatalog, CreatureParam, ImproveResponse, ShoveResult } from "../types";
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
  const [busy, setBusy] = useState<"preview" | "run" | "shove" | "improve" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [shove, setShove] = useState<ShoveResult | null>(null);
  const [improvement, setImprovement] = useState<ImproveResponse | null>(null);
  const ticket = useRef(0);
  /** Set when "Improve it" moves the sliders itself: the resting preview must not replace its run. */
  const keepRun = useRef(false);

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
    setShove(null);
    setImprovement(null);
  }, [current?.key]);

  // Whenever the design changes, show it at rest (after a short pause for sliders being dragged).
  useEffect(() => {
    if (!current || Object.keys(params).length === 0) return;
    if (keepRun.current) {
      keepRun.current = false;
      return;
    }
    const mine = ++ticket.current;
    setBusy("preview");
    const timer = setTimeout(() => {
      api
        .buildCreature({ preset: current.key, params, goal, simulate: false })
        .then((response) => {
          if (mine !== ticket.current) return;
          setBuilt(response);
          setResult(null);
          setShove(null);
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
      setShove(null);
      setImprovement(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const creatureId = result?.scene.robot ?? null;

  const shoveIt = async () => {
    if (!creatureId) return;
    setBusy("shove");
    setError(null);
    try {
      setShove(await api.shoveCreature(creatureId));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const improveIt = async () => {
    if (!creatureId || !result) return;
    setBusy("improve");
    setError(null);
    try {
      const found = await api.improveCreature(creatureId);
      setImprovement(found);
      if (found.improved && found.scene && found.run && found.creature) {
        // Move the sliders to the better design and play its run, without a preview replacing it.
        keepRun.current = true;
        setParams(found.creature.params);
        const response: BuildResponse = { scene: found.scene, run: found.run, creature: found.creature };
        setBuilt(response);
        setResult(response);
        setShove(found.after);
      }
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

        {result && (
          <section className="panel" data-testid="shove-panel">
            <h2 className="eyebrow">Shove it</h2>
            <p className="body">
              Kick it sideways from each side at rising strength and see how hard before it topples. The
              strength is the speed the kick gives it, so a light creature and a heavy one are shoved alike.
            </p>
            <button type="button" className="ghost" disabled={busy !== null} onClick={() => void shoveIt()}>
              {busy === "shove" ? "Shoving…" : shove ? "Shove it again" : "Test shoves"}
            </button>
            {shove && (
              <>
                <p className="verdict" data-testid="shove-verdict">
                  {shoveSentence(shove)}
                </p>
                {shove.levels.length > 0 && (
                  <ul className="shove-levels" aria-label="Each strength, from both sides">
                    {shove.levels.map((level) => {
                      const both = level.left && level.right;
                      const said = shoveStrength(level.speed, level.newtons);
                      const how = both
                        ? "stayed up from both sides"
                        : level.left || level.right
                          ? `fell from the ${level.left ? "right" : "left"}`
                          : "fell from both sides";
                      return (
                        <li key={level.speed} className={both ? "ok" : "bad"} title={`${said}: ${how}`}>
                          <span className="mono">{level.speed}</span>
                          <span className="sr-only">{`${said}: ${how}`}</span>
                        </li>
                      );
                    })}
                  </ul>
                )}
                <p className="muted small">m/s of sideways speed. Teal: stayed up from both sides. Red: fell.</p>
              </>
            )}
          </section>
        )}

        {result && (
          <section className="panel" data-testid="improve-panel">
            <h2 className="eyebrow">Improve it</h2>
            <p className="body">
              Tries about 30 small changes to the sliders, and keeps one only if it stays up through more
              shoves, or walks clearly farther without being easier to knock over. It takes 10 to 30 seconds.
            </p>
            <button type="button" className="primary" disabled={busy !== null} onClick={() => void improveIt()}>
              {busy === "improve" ? "Trying changes…" : "Improve it"}
            </button>
            {improvement && !improvement.improved && (
              <p className="muted" data-testid="improve-none" role="status">
                Tried {improvement.tried} changes and none was clearly better. This design is already a good
                one, or the sliders cannot fix what is wrong with it.
              </p>
            )}
            {improvement?.improved && improvement.after && (
              <div data-testid="improve-found" role="status">
                <p className="verdict">Found a better design. The sliders have moved to it.</p>
                <ul className="evidence">
                  {improvement.changes.map((change) => (
                    <li key={change.key}>
                      <span className="bar ok" />
                      <span className="ev-text">
                        <span className="ev-label">{change.label}</span>
                        <span className="ev-value">{changeLine(change).split(": ")[1]}</span>
                      </span>
                    </li>
                  ))}
                  <li>
                    <span className="bar ok" />
                    <span className="ev-text">
                      <span className="ev-label">Holds up to</span>
                      <span className="ev-value">{limitLine(improvement.before, improvement.after)}</span>
                    </span>
                  </li>
                  <li>
                    <span className="bar ok" />
                    <span className="ev-text">
                      <span className="ev-label">Walks</span>
                      <span className="ev-value">
                        {improvement.before.forward} m → {improvement.after.forward} m
                      </span>
                    </span>
                  </li>
                </ul>
                <p className="muted small">
                  A sturdier body can walk less far: both numbers are shown, and Reset puts the sliders back.
                </p>
              </div>
            )}
          </section>
        )}

        {creatureId && (
          <section className="panel">
            <h2 className="eyebrow">Take it with you</h2>
            <p className="body">Download this creature to use it elsewhere.</p>
            <div className="row export-links">
              <a className="ghost" href={api.creatureExport(creatureId, "json")} download>
                Creature Lab JSON
              </a>
              <a className="ghost" href={api.creatureExport(creatureId, "mjcf")} download>
                MuJoCo model
              </a>
              <a className="ghost" href={api.creatureExport(creatureId, "urdf")} download>
                URDF
              </a>
            </div>
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
