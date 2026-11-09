import { dotLabel, dotsFor, limitText, outcomeTone, totals } from "../format";
import type { CheckupSummary, PolicySummary, RobotInfo, RunDetail } from "../types";

interface Props {
  robot: RobotInfo;
  checkup: CheckupSummary | null;
  policyKey: string | null;
  onPolicy: (key: string) => void;
  run: RunDetail | null;
  onRun: (id: string) => void;
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

export function Inspector({ robot, checkup, policyKey, onPolicy, run, onRun }: Props) {
  const policy = checkup?.policies.find((p) => p.policy === policyKey) ?? checkup?.policies[0] ?? null;
  return (
    <aside className="side-col" aria-label="Inspector">
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
