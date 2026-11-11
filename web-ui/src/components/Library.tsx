import { useState, type KeyboardEvent } from "react";
import { api } from "../api";
import { type Filter, groupRuns, matchesFilter, outcomeTone } from "../format";
import type { RobotInfo, RunCard } from "../types";

/** A picture from the server that falls back to a plain tile when it cannot be rendered. */
function Picture({ src, alt, className }: { src: string | null; alt: string; className?: string }) {
  const [failed, setFailed] = useState(false);
  if (!src || failed) {
    return (
      <div className={`picture placeholder ${className ?? ""}`} role="img" aria-label={alt}>
        <svg viewBox="0 0 28 28" aria-hidden="true" width="26" height="26">
          <rect x="4" y="8" width="20" height="10" rx="4" fill="none" stroke="currentColor" strokeWidth="1.6" />
          <path d="M8 18 6.5 24M20 18l1.5 6M14 8V4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
        </svg>
      </div>
    );
  }
  return <img className={`picture ${className ?? ""}`} src={src} alt={alt} loading="lazy" onError={() => setFailed(true)} />;
}

interface Props {
  robots: RobotInfo[];
  selected: string;
  onSelect: (key: string) => void;
  runs: RunCard[];
  runId: string | null;
  onRun: (id: string) => void;
  onBuild: (preset: string) => void;
  buildNote: string | null;
  onAddRobot: () => void;
}

const PRESETS = [
  { key: "quadruped", name: "Quadruped" },
  { key: "hexapod", name: "Hexapod" },
  { key: "worm", name: "Worm" },
  { key: "humanoid", name: "Humanoid" },
];

/** Arrow keys, Home and End move between the run cards, so one Tab stop covers the whole list. */
function moveBetweenRuns(event: KeyboardEvent<HTMLElement>) {
  const keys = ["ArrowDown", "ArrowUp", "Home", "End"];
  if (!keys.includes(event.key)) return;
  const cards = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>(".run-card"));
  const at = cards.indexOf(document.activeElement as HTMLButtonElement);
  if (at < 0) return;
  event.preventDefault();
  const next =
    event.key === "Home"
      ? 0
      : event.key === "End"
        ? cards.length - 1
        : Math.min(Math.max(at + (event.key === "ArrowDown" ? 1 : -1), 0), cards.length - 1);
  cards[next]?.focus();
  cards[next]?.scrollIntoView({ block: "nearest" });
}

const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "down", label: "Stayed down" },
  { key: "got-up", label: "Got up" },
  { key: "up", label: "Stayed up" },
];

export function Library({
  robots,
  selected,
  onSelect,
  runs,
  runId,
  onRun,
  onBuild,
  buildNote,
  onAddRobot,
}: Props) {
  const robot = robots.find((r) => r.key === selected);
  const [filter, setFilter] = useState<Filter>("all");
  const shown = runs.filter((run) => matchesFilter(run, filter));
  const groups = groupRuns(shown);
  const tabStop = shown.some((r) => r.id === runId) ? runId : shown[0]?.id;
  return (
    <aside className="rail-col" aria-label="Library">
      <section>
        <h2 className="eyebrow">Real robots</h2>
        <div className="cards">
          {robots.map((r) => (
            <button
              key={r.key}
              type="button"
              className={`robot-card${r.key === selected ? " selected" : ""}`}
              aria-pressed={r.key === selected}
              onClick={() => onSelect(r.key)}
            >
              <Picture
                src={r.installed ? api.robotThumbnail(r.key) : null}
                alt={`${r.title}`}
                className="robot-pic"
              />
              <span className="row">
                <span className="name">{r.title}</span>
                <span className="badge">{r.custom ? "Your robot" : r.installed ? "Real robot" : "Not downloaded"}</span>
              </span>
              <span className="sub">
                {r.maker} · {r.heightCm >= 100 ? `${(r.heightCm / 100).toFixed(1)} m` : `${r.heightCm} cm`}
              </span>
            </button>
          ))}
        </div>
        <button type="button" className="add-robot" onClick={onAddRobot}>
          <span aria-hidden="true">+</span> Add your own robot
        </button>
      </section>

      {robot && runs.length > 0 && (
        <section aria-label={`History of ${robot.title} runs`} onKeyDown={moveBetweenRuns}>
          <h2 className="eyebrow">History · {robot.title}</h2>
          <div className="seg small filters" role="group" aria-label="Show runs">
            {FILTERS.map((f) => (
              <button key={f.key} type="button" aria-pressed={filter === f.key} onClick={() => setFilter(f.key)}>
                {f.label}
              </button>
            ))}
          </div>
          {shown.length === 0 && <p className="muted small">No runs ended that way.</p>}
          {groups.map((group) => (
            <div key={group.kind} className="run-group">
              <h3>{group.label}</h3>
              {group.runs.map((run) => (
                <button
                  key={run.id}
                  type="button"
                  className={`run-card${run.id === runId ? " selected" : ""}`}
                  aria-pressed={run.id === runId}
                  tabIndex={run.id === tabStop ? 0 : -1}
                  onClick={() => onRun(run.id)}
                >
                  <Picture src={api.runThumbnail(run.id)} alt="" className="run-pic" />
                  <span className="run-text">
                    <span className="run-title">{run.title}</span>
                    <span className="run-policy">{run.policyTitle}</span>
                    <span className={`chip ${outcomeTone(run.outcome)}`}>{run.outcomeText}</span>
                  </span>
                </button>
              ))}
            </div>
          ))}
        </section>
      )}

      <section>
        <h2 className="eyebrow">Build your own</h2>
        <p className="muted small">Pick a body, reshape it, and run it.</p>
        <div className="presets">
          {PRESETS.map((p) => (
            <button key={p.key} type="button" className="preset" onClick={() => onBuild(p.key)}>
              {p.name}
            </button>
          ))}
        </div>
        {buildNote && (
          <p className="muted small" role="status">
            {buildNote}
          </p>
        )}
      </section>
    </aside>
  );
}
