import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import { Inspector } from "./components/Inspector";
import { LicenseDialog } from "./components/LicenseDialog";
import { Library } from "./components/Library";
import { Stage } from "./components/Stage";
import { Timeline } from "./components/Timeline";
import { featuredRun } from "./format";
import { Playback } from "./playback";
import type { Job, RobotInfo, RunCard, RunDetail } from "./types";

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/** Polls a job until it finishes, reporting each state; resolves with the final one. */
async function follow(job: Job, onUpdate: (job: Job) => void): Promise<Job> {
  let current = job;
  onUpdate(current);
  while (current.state === "running") {
    await new Promise((resolve) => setTimeout(resolve, 700));
    current = await api.job(current.id);
    onUpdate(current);
  }
  return current;
}

function Hero({
  robot,
  job,
  missing,
  onDownload,
  onCheckup,
}: {
  robot: RobotInfo;
  job: Job | null;
  missing: string[];
  onDownload: () => void;
  onCheckup: () => void;
}) {
  const busy = job?.state === "running";
  return (
    <div className="hero" data-testid="hero">
      <div className="hero-text">
        <p className="eyebrow">{robot.maker}</p>
        <h1>{robot.installed ? `Check up the ${robot.title}` : `Meet the ${robot.title}`}</h1>
        <p className="lede">{robot.summary}</p>
        {busy && job ? (
          <div className="hero-progress" role="status" aria-live="polite">
            <progress max={1} value={job.progress} aria-label="Progress" />
            <p>
              {job.kind === "download" ? "Downloading" : "Running the check-up"} ·{" "}
              {job.message || "working…"}
            </p>
            <p className="muted">
              {job.kind === "download"
                ? "This takes a few seconds."
                : "This takes a minute or two. You can leave this tab open."}
            </p>
          </div>
        ) : !robot.installed ? (
          <>
            <p className="muted">
              Creature Lab runs the real robot model with its real trained policy, shoves it, and
              explains every fall. The model is about 25 MB and comes from its authors; you will see
              the license first.
            </p>
            <button type="button" className="primary big" disabled={busy} onClick={onDownload}>
              Download {robot.title}
            </button>
          </>
        ) : (
          <>
            <p className="muted">
              The robot is on this computer. A check-up shoves it at several strengths and moments,
              tries slippery floors and weak batteries, and writes down why each fall happened. It
              takes a minute or two.
            </p>
            <button
              type="button"
              className="primary big"
              disabled={busy || missing.length > 0}
              onClick={onCheckup}
            >
              Run the check-up
            </button>
          </>
        )}
        {missing.length > 0 && (
          <p className="warn" role="alert">
            Missing packages: {missing.join(", ")}. Install them with{" "}
            <code>uv sync --inexact --extra robots</code> and restart.
          </p>
        )}
      </div>
      {robot.installed ? (
        <img
          className="hero-photo"
          src={api.robotThumbnail(robot.key)}
          alt={`${robot.title} standing in the studio (simulation)`}
        />
      ) : (
      <svg className="hero-art" viewBox="0 0 220 220" aria-hidden="true">
        <ellipse cx="110" cy="196" rx="70" ry="9" fill="rgba(0,0,0,.35)" />
        <rect x="62" y="70" width="96" height="58" rx="22" fill="none" stroke="currentColor" strokeWidth="5" />
        <path d="M84 128 74 182M136 128l10 54M110 70V34" stroke="currentColor" strokeWidth="5" strokeLinecap="round" fill="none" />
        <circle cx="90" cy="98" r="7" fill="currentColor" />
        <circle cx="130" cy="98" r="7" fill="currentColor" />
      </svg>
      )}
    </div>
  );
}

export default function App() {
  const playback = useMemo(() => new Playback(), []);
  const [robots, setRobots] = useState<RobotInfo[]>([]);
  const [missing, setMissing] = useState<string[]>([]);
  const [robotKey, setRobotKey] = useState<string | null>(null);
  const [runs, setRuns] = useState<RunCard[]>([]);
  const [runId, setRunId] = useState<string | null>(null);
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [policyKey, setPolicyKey] = useState<string | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [licenseFor, setLicenseFor] = useState<RobotInfo | null>(null);
  const [banner, setBanner] = useState<string | null>(null);
  const [buildNote, setBuildNote] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [canRetry, setCanRetry] = useState(false);
  const jobRunning = useRef(false);

  const robot = robots.find((r) => r.key === robotKey) ?? null;

  // On narrow screens the library sits below the 3D view: bring the view back after a pick.
  const showPlayer = useCallback(() => {
    document.getElementById("player")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, []);
  const watch = useCallback(
    (id: string) => {
      setRunId(id);
      showPlayer();
    },
    [showPlayer],
  );

  const refresh = useCallback(async (): Promise<RobotInfo[]> => {
    const data = await api.robots();
    setRobots(data.robots);
    setMissing(data.missingPackages);
    return data.robots;
  }, []);

  const openRobot = useCallback(async (key: string, list: RobotInfo[]) => {
    setRobotKey(key);
    const info = list.find((r) => r.key === key);
    if (!info?.hasResults) {
      setRuns([]);
      setRunId(null);
      setDetail(null);
      return;
    }
    const cards = await api.runs(key);
    setRuns(cards);
    setRunId(featuredRun(cards)?.id ?? null);
  }, []);

  // First load: open the first robot that already has results, else the first one.
  useEffect(() => {
    (async () => {
      try {
        const list = await refresh();
        const first = list.find((r) => r.hasResults) ?? list.find((r) => r.installed) ?? list[0];
        if (first) await openRobot(first.key, list);
      } catch (e) {
        setBanner(`Could not reach the Creature Lab server (${errorText(e)}). Is it still running?`);
        setCanRetry(true);
      } finally {
        setLoaded(true);
      }
    })();
  }, [refresh, openRobot, attempt]);

  // The selected run's story.
  useEffect(() => {
    if (!runId) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    api
      .run(runId)
      .then((d) => {
        if (cancelled) return;
        setDetail(d);
        setPolicyKey(d.policy);
      })
      .catch((e) => !cancelled && setBanner(errorText(e)));
    return () => {
      cancelled = true;
    };
  }, [runId]);

  const track = useCallback(
    async (start: () => Promise<Job>, then: (finished: Job) => Promise<void>) => {
      if (jobRunning.current) return;
      jobRunning.current = true;
      setBanner(null);
      try {
        const finished = await follow(await start(), setJob);
        if (finished.state === "failed") setBanner(finished.error ?? "The job failed.");
        else await then(finished);
      } catch (e) {
        setBanner(errorText(e));
      } finally {
        jobRunning.current = false;
        setTimeout(() => setJob((j) => (j && j.state !== "running" ? null : j)), 2500);
      }
    },
    [],
  );

  const download = (target: RobotInfo) => {
    setLicenseFor(null);
    void track(
      () => api.download(target.key),
      async () => {
        const list = await refresh();
        await openRobot(target.key, list);
      },
    );
  };

  const checkup = (target: RobotInfo) =>
    void track(
      () => api.startCheckup(target.key),
      async () => {
        const list = await refresh();
        await openRobot(target.key, list);
      },
    );

  // A page reloaded during a download or check-up follows the running job again.
  useEffect(() => {
    if (!loaded) return;
    api
      .runningJobs()
      .then((active) => {
        const resumed = active[0];
        if (!resumed) return;
        void track(
          async () => resumed,
          async () => {
            const list = await refresh();
            await openRobot(resumed.robot, list);
          },
        );
      })
      .catch(() => undefined);
  }, [loaded, track, refresh, openRobot]);

  const build = async (preset: string) => {
    setBuildNote("Opening the classic builder…");
    try {
      const { url } = await api.builder(preset);
      window.open(url, "_blank", "noopener");
      setBuildNote("The classic builder opened in a new tab.");
    } catch (e) {
      setBuildNote(errorText(e));
    }
  };

  const hasStage = !!robot && robot.installed && robot.hasResults;
  const busy = job?.state === "running";

  return (
    <div className="app">
      <a className="skip" href="#player">
        Skip to the 3D view
      </a>
      <header className="top">
        <div className="brand">
          <svg width="28" height="28" viewBox="0 0 28 28" aria-hidden="true">
            <rect x="3" y="7" width="22" height="12" rx="4" />
            <path d="M8 19 6 25M20 19l2 6M14 7V3" />
            <circle cx="10" cy="13" r="1.6" className="solid" />
            <circle cx="18" cy="13" r="1.6" className="solid" />
          </svg>
          <span>Creature Lab</span>
        </div>
        <nav aria-label="Breadcrumb" className="crumbs">
          <span>Robots</span>
          <span aria-hidden="true">›</span>
          <strong>{robot?.title ?? "…"}</strong>
        </nav>
        <div className="spacer" />
        {robot?.hasResults && (
          <a className="ghost button" href={api.reportUrl(robot.key)} target="_blank" rel="noopener">
            Open report
          </a>
        )}
        <button
          type="button"
          className="primary"
          disabled={!robot || !robot.installed || busy || missing.length > 0}
          onClick={() => robot && checkup(robot)}
        >
          <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
            <path d="M4 3 13 8 4 13Z" />
          </svg>
          Run check-up
        </button>
      </header>

      {job && !(robot && !hasStage && job.robot === robot.key) && (
        <div className={`jobbar ${job.state}`} role="status" aria-live="polite">
          <span>
            {job.kind === "download" ? "Downloading" : "Check-up"} · {job.message || "working…"}
          </span>
          <progress max={1} value={job.progress} aria-label="Progress" />
        </div>
      )}
      {banner && (
        <div className="banner" role="alert">
          <span>{banner}</span>
          <span className="banner-actions">
            {canRetry && (
              <button
                type="button"
                className="link"
                onClick={() => {
                  setBanner(null);
                  setCanRetry(false);
                  setLoaded(false);
                  setAttempt((n) => n + 1);
                }}
              >
                Try again
              </button>
            )}
            <button type="button" className="link" onClick={() => setBanner(null)}>
              Dismiss
            </button>
          </span>
        </div>
      )}

      <div className={`shell${hasStage ? "" : " solo"}`}>
        <Library
          robots={robots}
          selected={robotKey ?? ""}
          onSelect={(key) => {
            void openRobot(key, robots);
            showPlayer();
          }}
          runs={runs}
          runId={runId}
          onRun={watch}
          onBuild={(preset) => void build(preset)}
          buildNote={buildNote}
        />

        <main className="center" id="player" tabIndex={-1}>
          {!loaded && <div className="stage-note">Loading…</div>}
          {loaded && robot && hasStage && <Stage robot={robot} run={detail} playback={playback} />}
          {loaded && robot && !hasStage && (
            <Hero
              robot={robot}
              job={job}
              missing={missing}
              onDownload={() => setLicenseFor(robot)}
              onCheckup={() => checkup(robot)}
            />
          )}
          {hasStage && <Timeline playback={playback} run={detail} />}
        </main>

        {robot && hasStage && (
          <Inspector
            robot={robot}
            checkup={robot.checkup}
            policyKey={policyKey}
            onPolicy={setPolicyKey}
            run={detail}
            onRun={watch}
          />
        )}
      </div>

      {licenseFor && (
        <LicenseDialog robot={licenseFor} onAccept={() => download(licenseFor)} onCancel={() => setLicenseFor(null)} />
      )}
    </div>
  );
}
