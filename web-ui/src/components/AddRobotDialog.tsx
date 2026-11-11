import { useEffect, useRef, useState, type FormEvent } from "react";
import { api } from "../api";
import type { PackReport } from "../types";

const GUIDE = "https://github.com/oney-erge/Creature-Lab/blob/main/docs/ROBOT_PACKS.md";

interface Props {
  /** Called with the new robot's key once it is in the list. */
  onAdded: (key: string) => void;
  onCancel: () => void;
}

/** Asks for the folder of a robot pack, shows what is wrong with it in plain words, and adds it. */
export function AddRobotDialog({ onAdded, onCancel }: Props) {
  const [path, setPath] = useState("");
  const [busy, setBusy] = useState<"check" | "add" | null>(null);
  const [report, setReport] = useState<PackReport | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    input.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onCancel();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onCancel]);

  const edit = (value: string) => {
    setPath(value);
    setReport(null); // what was found belongs to the old path
    setProblem(null);
  };

  const run = async (kind: "check" | "add") => {
    setBusy(kind);
    setProblem(null);
    try {
      const found = kind === "check" ? await api.checkRobotFolder(path) : await api.addRobotFolder(path);
      if (kind === "add" && found.added && found.key) {
        onAdded(found.key);
        return;
      }
      setReport(found);
    } catch (e) {
      setReport(null);
      setProblem(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (busy || !path.trim()) return;
    void run(report?.ok ? "add" : "check");
  };

  const ready = report?.ok === true;
  return (
    <div className="scrim" onMouseDown={(e) => e.target === e.currentTarget && onCancel()}>
      <form className="dialog" role="dialog" aria-modal="true" aria-labelledby="add-robot-title" onSubmit={submit}>
        <h2 id="add-robot-title">Add your own robot</h2>
        <p className="lede">
          Point Creature Lab at a folder with a MuJoCo model, a trained policy and a <code>robot.toml</code> that says
          how the two connect. It checks everything, then shoves your robot the way it shoves the built-in ones. The
          folder stays where it is.{" "}
          <a href={GUIDE} target="_blank" rel="noopener noreferrer">
            How to set one up
          </a>
        </p>
        <label className="field">
          <span>Folder on this computer</span>
          <input
            ref={input}
            type="text"
            value={path}
            onChange={(e) => edit(e.target.value)}
            placeholder="C:\robots\my-robot"
            spellCheck={false}
            autoComplete="off"
            aria-describedby="add-robot-note"
          />
        </label>
        <p id="add-robot-note" className="muted small">
          Only add folders you trust: Creature Lab opens the model and policy files in them.
        </p>

        {busy && (
          <p className="muted" role="status">
            {busy === "check" ? "Checking, and walking the robot for a couple of seconds…" : "Adding…"}
          </p>
        )}
        {problem && (
          <p className="warn" role="alert">
            {problem}
          </p>
        )}
        {report && (
          <div className="pack-report" role="status">
            {report.errors.length > 0 && (
              <>
                <h3 className="tone-bad">Fix this first</h3>
                <ul className="pack-problems bad">
                  {report.errors.map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
              </>
            )}
            {report.warnings.length > 0 && (
              <>
                <h3>Worth a look</h3>
                <ul className="pack-problems">
                  {report.warnings.map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
              </>
            )}
            {ready && (
              <p className="pack-ok">
                {report.title ? `${report.title} is ready to add.` : "Ready to add."}
              </p>
            )}
            {report.facts.length > 0 && (
              <dl className="pack-facts">
                {report.facts.map((fact) => (
                  <div key={fact.name}>
                    <dt>{fact.name}</dt>
                    <dd>{fact.value}</dd>
                  </div>
                ))}
              </dl>
            )}
          </div>
        )}

        <div className="dialog-actions">
          <button type="button" className="ghost" onClick={onCancel}>
            Cancel
          </button>
          {ready ? (
            <button type="submit" className="primary" disabled={busy !== null}>
              {report?.title ? `Add ${report.title}` : "Add this robot"}
            </button>
          ) : (
            <button type="submit" className="primary" disabled={busy !== null || !path.trim()}>
              Check it
            </button>
          )}
        </div>
      </form>
    </div>
  );
}
