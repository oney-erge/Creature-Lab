import { useEffect, useRef, useState } from "react";
import type { RobotInfo } from "../types";

interface Props {
  robot: RobotInfo;
  onAccept: () => void;
  onCancel: () => void;
}

/** Shows a robot's license before anything is downloaded; accepting is an explicit click. */
export function LicenseDialog({ robot, onAccept, onCancel }: Props) {
  const [read, setRead] = useState(false);
  const accept = useRef<HTMLButtonElement>(null);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    box.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onCancel();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onCancel]);

  return (
    <div className="scrim" onMouseDown={(e) => e.target === e.currentTarget && onCancel()}>
      <div
        ref={box}
        className="dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="license-title"
        tabIndex={-1}
      >
        <h2 id="license-title">Before you download {robot.title}</h2>
        <p className="lede">
          Creature Lab fetches the robot's files from their authors. They are checked against pinned
          hashes and stay on this computer.
        </p>
        <blockquote>{robot.licenseNotice}</blockquote>
        {robot.nonCommercial && (
          <p className="warn">
            Pictures and videos that show this robot's meshes must carry its credit and stay
            non-commercial.
          </p>
        )}
        <label className="check">
          <input type="checkbox" checked={read} onChange={(e) => setRead(e.target.checked)} />I have read this and agree
          to the license.
        </label>
        <div className="dialog-actions">
          <button type="button" className="ghost" onClick={onCancel}>
            Cancel
          </button>
          <button type="button" className="primary" ref={accept} disabled={!read} onClick={onAccept}>
            Download {robot.title}
          </button>
        </div>
      </div>
    </div>
  );
}
