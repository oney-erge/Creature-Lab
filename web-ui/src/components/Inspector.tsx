import { compareSentence, dotLabel, dotsFor, limitText, outcomeTone, severity, totals } from "../format";
import type { CheckupSummary, PolicySummary, RobotInfo, RunCard, RunDetail } from "../types";

interface Props {
  robot: RobotInfo;
  checkup: CheckupSummary | null;
  policyKey: string | null;
  onPolicy: (key: string) => void;
  run: RunDetail | null;
  onRun: (id: string) => void;
  /** The same test under the other policy, if the check-up has one. */
  twin: RunCard | null;
  compare: boolean;
  onCompare: (on: boolean) => void;
}

/** "Can it be fixed?": the same shove under the other policy, one click away. */
function FixPanel({ run, twin, onCompare }: { run: RunDetail; twin: RunCard; onCompare: (on: boolean) => void }) {
  const better = severity(twin.outcome) < severity(run.outcome);
  return (
    <section className="panel fix" data-testid="fix">
      <h2 className="eyebrow">{better ? "Can it be fixed?" : "Another policy"}</h2>
      <p className="body">
        {better
          ? `Yes, for this shove. The ${twin.policyTitle.toLowerCase()} met the same push and `
          : `The ${twin.policyTitle.toLowerCase()} met the same test and `}
        <strong className={`tone-${outcomeTone(twin.outcome)}`}>{twin.outcomeText.toLowerCase()}</strong>.
      </p>
      <button type="button" className={better ? "primary" : "ghost"} onClick={() => onCompare(true)}>
        See both side by side
      </button>
    </section>
  );
}

/** The result of the comparison, in words, with the way back. */
function CompareVerdict({ run, twin, onCompare }: { run: RunDetail; twin: RunCard; onCompare: (on: boolean) => void }) {
  return (
    <section className="panel" data-testid="verdict">
      <h2 className="eyebrow">Same test, two policies</h2>
      <ul className="versus">
        {[run, twin].map((r) => (
          <li key={r.id}>
            <span className="versus-name">{r.policyTitle}</span>
            <span className={`chip ${outcomeTone(r.outcome)}`}>{r.outcomeText}</span>
          </li>
        ))}
      </ul>
      <p className="verdict tone-good">{compareSentence(run, twin)}</p>
      <button type="button" className="ghost" onClick={() => onCompare(false)}>
        Back to one view
      </button>
    </section>
  );
}

function Evidence({ run }: { run: RunDetail }) {
  const blamed = (label: string) =>
    (run.cause === "pushed" && label === "Balance point vs feet") ||
    (run.cause === "slipped" && label === "Feet slide on the floor") ||
    (run.cause === "servos_saturated" && label === "Servos at their torque limit");
  const rows = run.evidence.filter((e) => !e.label.startsWith("Tilt passed"));
  return (
    <ul className="evidence">
      {rows.map((e) => (
        <li key={e.label} title={e.detail}>
          <span className={`bar ${blamed(e.label) ? "bad" : "ok"}`} />
          <span className="ev-text">
            <span className="ev-label">{e.label}</span>
            <span className="ev-value">{e.value}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}

function ShoveMatrix({ policy, onRun }: { policy: PolicySummary; onRun: (id: string) => void }) {
  const { down, falls, total } = totals(policy);
  return (
    <section className="panel">
      <h2 className="eyebrow">Shoves that leave it on the floor</h2>
      <p className="big-number">
        <span className="mono">{down}</span>
        <span className="muted"> of {total} shoves · {falls} falls in all</span>
      </p>
      <div className="matrix">
        {policy.shoves.map((row) => {
          const target = row.fallRun ?? row.okRun;
          return (
            <div className="matrix-row" key={row.force}>
              <span className="mono force">{row.force} N</span>
              <span className="dots" role="img" aria-label={dotLabel(row)}>
                {dotsFor(row).map((kind, i) => (
                  <span key={i} className={`dot ${kind}`} />
                ))}
              </span>
              <button
                type="button"
                className="link"
                disabled={!target}
                onClick={() => target && onRun(target)}
                aria-label={`Watch a ${row.force} N shove`}
              >
                Watch
              </button>
            </div>
          );
        })}
      </div>
      <div className="legend">
        <span>
          <i className="dot up" /> Stayed up
        </span>
        <span>
          <i className="dot got" /> Fell, got up
        </span>
        <span>
          <i className="dot down" /> Stayed down
        </span>
      </div>
      <dl className="limits">
        <dt>Never falls</dt>
        <dd>{limitText(policy.neverFallsUpTo, policy)}</dd>
        <dt>Always ends up standing</dt>
        <dd>{limitText(policy.neverStaysDownUpTo, policy)}</dd>
      </dl>
    </section>
  );
}

export function Inspector({ robot, checkup, policyKey, onPolicy, run, onRun, twin, compare, onCompare }: Props) {
  const policy = checkup?.policies.find((p) => p.policy === policyKey) ?? checkup?.policies[0] ?? null;
  return (
    <aside className="side-col" aria-label="Inspector">
      {run && twin && compare && <CompareVerdict run={run} twin={twin} onCompare={onCompare} />}
      {checkup && checkup.policies.length > 0 && policy && (
        <section className="panel">
          <h2 className="eyebrow">Check-up · {robot.title}</h2>
          {checkup.policies.length > 1 && (
            <div className="seg" role="group" aria-label="Policy">
              {checkup.policies.map((p) => (
                <button
                  key={p.policy}
                  type="button"
                  aria-pressed={p.policy === policy.policy}
                  onClick={() => onPolicy(p.policy)}
                >
                  {p.title}
                </button>
              ))}
            </div>
          )}
          <p className="body">{policy.summary}</p>
          <p className="muted small">{policy.baseline}</p>
        </section>
      )}

      {run && (
        <section className="panel" data-testid="explanation">
          <h2 className="eyebrow">What happened · {run.title}</h2>
          <p className={`verdict tone-${outcomeTone(run.outcome)}`}>{run.verdict}</p>
          {run.causeText && <p className="body">{run.causeText}</p>}
          {run.evidence.length > 0 && <Evidence run={run} />}
          {run.outcome === "walked" && run.events.pushAt !== null && (
            <p className="muted small">Peak lean {run.peakTiltDeg}° (a fall is past 60°).</p>
          )}
        </section>
      )}

      {run && twin && !compare && <FixPanel run={run} twin={twin} onCompare={onCompare} />}

      {policy && policy.shoves.length > 0 && <ShoveMatrix policy={policy} onRun={onRun} />}

      {policy && policy.conditions.length > 0 && (
        <section className="panel">
          <h2 className="eyebrow">Floors, batteries and loads</h2>
          <ul className="conditions">
            {policy.conditions.map((c) => (
              <li key={c.label}>
                <button type="button" className="cond" disabled={!c.run} onClick={() => c.run && onRun(c.run)}>
                  <span className={`status ${c.passed ? "pass" : "fail"}`}>{c.passed ? "Pass" : "Fail"}</span>
                  <span className="cond-text">
                    <span>{c.label}</span>
                    <span className="muted small">
                      {Math.round(c.relativeDistance * 100)}% of normal distance
                    </span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
    </aside>
  );
}
