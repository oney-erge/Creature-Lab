import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import { Editor } from "./components/Editor";
import { Inspector } from "./components/Inspector";
import { LicenseDialog } from "./components/LicenseDialog";
import { Library } from "./components/Library";
import { Stage, robotSource } from "./components/Stage";
import { Timeline } from "./components/Timeline";
import { featuredRun, quickestStart, roughDuration } from "./format";
import { Playback } from "./playback";
import { prefersReducedMotion } from "./prefs";
import { hashFor, parseHash } from "./url";
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
              Download and check up
            </button>
            {robot.firstRunSeconds > 0 && (
              <p className="muted small">
                The first time takes {roughDuration(robot.firstRunSeconds)} on a laptop; the physics
                runs on your CPU. You can leave this tab open.
              </p>
            )}
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
      ) : robot.introClip && !prefersReducedMotion() ? (
        <figure className="hero-clip">
          <img
            className="hero-photo"
            src={robot.introClip}
            alt={`A recorded check-up of the ${robot.title}: a shove, shown in slow motion (simulation)`}
          />
          <figcaption className="muted small">Simulation. {robot.credit}</figcaption>
        </figure>
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
  // The change being run for a "what if", and the run to open side by side once it has loaded.
  const [asking, setAsking] = useState<string | null>(null);
  const wantCompare = useRef<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [canRetry, setCanRetry] = useState(false);
  const [compare, setCompare] = useState(false);
  const [other, setOther] = useState<RunDetail | null>(null);
  const [ready, setReady] = useState<string | null>(null);
  const [view, setView] = useState<"robots" | "build">(() => parseHash(window.location.hash).view);
  const [buildPreset, setBuildPreset] = useState<string>(() => parseHash(window.location.hash).preset ?? "quadruped");
  const jobRunning = useRef(false);
  /** Set by anything the person does, so the address bar gets a new entry (the back button). */
  const userNav = useRef(false);
  /** What async callbacks need to know about the screen right now. */
  const live = useRef<{ robotKey: string | null; hasStage: boolean; robots: RobotInfo[] }>({
    robotKey: null,
    hasStage: false,
    robots: [],
  });

  const robot = robots.find((r) => r.key === robotKey) ?? null;
  const source = useMemo(() => (robot ? robotSource(robot) : null), [robot?.key, robot?.heightCm, robot?.title, robot?.credit]);

  // On narrow screens the library sits below the 3D view: bring the view back after a pick.
  const showPlayer = useCallback(() => {
    document
      .getElementById("player")
      ?.scrollIntoView({ behavior: prefersReducedMotion() ? "auto" : "smooth", block: "start" });
  }, []);
  const watch = useCallback(
    (id: string) => {
      userNav.current = true;
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

  const openRobot = useCallback(async (key: string, list: RobotInfo[], preferRun: string | null = null) => {
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
    setRunId(cards.find((c) => c.id === preferRun)?.id ?? featuredRun(cards)?.id ?? null);
  }, []);

  // First load: open the first robot that already has results, else the first one.
  useEffect(() => {
    (async () => {
      try {
        const list = await refresh();
        // A link or a reload names a robot and a run; otherwise open the first robot with results.
        const asked = parseHash(window.location.hash);
        const wanted = list.find((r) => r.key === asked.robot);
        const first =
          wanted ?? list.find((r) => r.hasResults) ?? list.find((r) => r.installed) ?? quickestStart(list);
        if (first) {
          await openRobot(first.key, list, wanted ? asked.run : null);
          setCompare(!!wanted && asked.compare);
        }
      } catch (e) {
        setBanner(`Could not reach the Creature Lab server (${errorText(e)}). Is it still running?`);
        setCanRetry(true);
      } finally {
        setLoaded(true);
      }
    })();
  }, [refresh, openRobot, attempt]);

  // The address bar follows what is on screen (a new entry when the person chose it).
  useEffect(() => {
    if (!loaded) return;
    const desired =
      view === "build"
        ? hashFor({ view: "build", robot: null, run: null, compare: false, preset: buildPreset })
        : hashFor({ view: "robots", robot: robotKey, run: runId, compare, preset: null });
    if (window.location.hash === desired) return;
    if (userNav.current) window.history.pushState(null, "", desired);
    else window.history.replaceState(null, "", desired);
    userNav.current = false;
  }, [loaded, view, buildPreset, robotKey, runId, compare]);

  // Back and forward move between what was on screen.
  useEffect(() => {
    const onPop = () => {
      const place = parseHash(window.location.hash);
      setView(place.view);
      if (place.view === "build") {
        if (place.preset) setBuildPreset(place.preset);
        return;
      }
      const { robotKey: current, robots: list } = live.current;
      if (place.robot && place.robot !== current && list.some((r) => r.key === place.robot)) {
        void openRobot(place.robot, list, place.run);
      } else if (place.run) {
        setRunId(place.run);
      }
      setCompare(place.compare);
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, [openRobot]);

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
        if (wantCompare.current === d.id) {
          wantCompare.current = null;
          setCompare(true);
        }
      })
      .catch((e) => !cancelled && setBanner(errorText(e)));
    return () => {
      cancelled = true;
    };
  }, [runId]);

  // The other policy's run of the same test, while the two are shown together.
  const twin = runs.find((r) => r.id === detail?.pair) ?? null;
  useEffect(() => {
    if (!compare) {
      setOther(null);
      return;
    }
    if (!twin) {
      // A run with no twin (a different robot, or a one-policy robot) cannot be compared.
      if (detail) setCompare(false);
      return;
    }
    let cancelled = false;
    api
      .run(twin.id)
      .then((d) => !cancelled && setOther(d))
      .catch((e) => !cancelled && setBanner(errorText(e)));
    return () => {
      cancelled = true;
    };
  }, [compare, twin?.id, detail]);

  const track = useCallback(
    async (start: () => Promise<Job>, then: (finished: Job) => Promise<void>): Promise<boolean> => {
      if (jobRunning.current) return false;
      jobRunning.current = true;
      setBanner(null);
      let succeeded = false;
      try {
        const finished = await follow(await start(), setJob);
        if (finished.state === "failed") {
          setBanner(finished.error ?? "The job failed.");
        } else {
          await then(finished);
          succeeded = true;
        }
      } catch (e) {
        setBanner(errorText(e));
      } finally {
        jobRunning.current = false;
        setTimeout(() => setJob((j) => (j && j.state !== "running" ? null : j)), 2500);
      }
      return succeeded;
    },
    [],
  );

  // The first run is one click: download, then straight into the check-up, so a robot is shoved
  // and moving as soon as it can be.
  const download = (target: RobotInfo) => {
    setLicenseFor(null);
    void (async () => {
      const downloaded = await track(
        () => api.download(target.key),
        async () => {
          const list = await refresh();
          await openRobot(target.key, list);
        },
      );
      if (downloaded) checkup(target);
    })();
  };

  const checkup = (target: RobotInfo) =>
    void track(
      () => api.startCheckup(target.key),
      async () => {
        // Someone watching a run is not moved to a different one: they are told, and choose.
        if (live.current.hasStage && live.current.robotKey === target.key) {
          setReady(target.key);
          return;
        }
        const list = await refresh();
        await openRobot(target.key, list);
      },
    );

  // "What if…": run the same test with one thing changed, then show it next to the original.
  const askWhatIf = async (key: string) => {
    if (!detail || !robotKey) return;
    setAsking(key);
    setBanner(null);
    try {
      const made = await api.whatIf(detail.id, key);
      setRuns(await api.runs(robotKey));
      userNav.current = true;
      wantCompare.current = made.id;
      setRunId(made.id);
      showPlayer();
    } catch (e) {
      setBanner(errorText(e));
    } finally {
      setAsking(null);
    }
  };

  const showNewCheckup = async () => {
    const key = ready;
    setReady(null);
    if (!key) return;
    userNav.current = true;
    const list = await refresh();
    await openRobot(key, list);
  };

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

  const openEditor = (preset: string) => {
    userNav.current = true;
    setBuildPreset(preset);
    setView("build");
  };
  const showRobots = () => {
    userNav.current = true;
    setView("robots");
  };

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
  live.current = { robotKey, hasStage, robots };

  const setCompareOn = (on: boolean) => {
    userNav.current = true;
    setCompare(on);
    if (on) showPlayer();
  };
  // Side by side: the walk-only policy (before) on the left, the one that gets up (after) on the right.
  const getsUp = (policy: string) => !!robot?.policies.find((p) => p.key === policy)?.getsUp;
  const pairShown = compare && !!detail && !!other;
  // The original goes on the left of its "what if"; of two policies, the walk-only one goes left.
  const sameRobot = pairShown && detail.policy === other.policy;
  const mirrored = pairShown && (sameRobot ? !!detail.whatIf && !other.whatIf : getsUp(detail.policy) && !getsUp(other.policy));

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
        <nav aria-label="Sections" className="tabs">
          <button
            type="button"
            className={view === "robots" ? "on" : ""}
            aria-current={view === "robots" ? "page" : undefined}
            onClick={showRobots}
          >
            Real robots
          </button>
          <button
            type="button"
            className={view === "build" ? "on" : ""}
            aria-current={view === "build" ? "page" : undefined}
            onClick={() => openEditor(buildPreset)}
          >
            Build your own
          </button>
        </nav>
        {view === "robots" && (
          <nav aria-label="Breadcrumb" className="crumbs">
            <strong>{robot?.title ?? "…"}</strong>
          </nav>
        )}
        <div className="spacer" />
        {view === "robots" && robot?.hasResults && (
          <a className="ghost button" href={api.reportUrl(robot.key)} target="_blank" rel="noopener">
            Open report
          </a>
        )}
        {view === "robots" && (
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
        )}
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

      {view === "build" && (
        <Editor
          preset={buildPreset}
          onPreset={(p) => {
            userNav.current = true;
            setBuildPreset(p);
          }}
          onClassic={(p) => void build(p)}
          classicNote={buildNote}
        />
      )}

      {view === "robots" && (
      <div className={`shell${hasStage ? "" : " solo"}`}>
        <Library
          robots={robots}
          selected={robotKey ?? ""}
          onSelect={(key) => {
            userNav.current = true;
            setCompare(false);
            void openRobot(key, robots);
            showPlayer();
          }}
          runs={runs}
          runId={runId}
          onRun={watch}
          onBuild={openEditor}
          buildNote={buildNote}
        />

        <main className="center" id="player" tabIndex={-1}>
          {!loaded && <div className="stage-note">Loading…</div>}
          {loaded && robot && source && hasStage && !pairShown && <Stage source={source} run={detail} playback={playback} />}
          {loaded && robot && source && hasStage && pairShown && detail && other && (
            <div className="pair" data-testid="pair">
              {(mirrored ? [other, detail] : [detail, other]).map((r) => (
                <Stage key={r.id} source={source} run={r} playback={playback} follower={r.id !== detail.id} />
              ))}
            </div>
          )}
          {loaded && robot && !hasStage && (
            <Hero
              robot={robot}
              job={job}
              missing={missing}
              onDownload={() => setLicenseFor(robot)}
              onCheckup={() => checkup(robot)}
            />
          )}
          {hasStage && <Timeline playback={playback} run={detail} other={pairShown ? other : null} />}
        </main>

        {robot && hasStage && (
          <Inspector
            robot={robot}
            checkup={robot.checkup}
            policyKey={policyKey}
            onPolicy={setPolicyKey}
            run={detail}
            onRun={watch}
            twin={twin}
            compare={pairShown}
            onCompare={setCompareOn}
            onWhatIf={(key) => void askWhatIf(key)}
            asking={asking}
          />
        )}
      </div>
      )}

      {ready && (
        <div className="jobbar ready" role="status">
          <span>New check-up ready.</span>
          <button type="button" className="link" onClick={() => void showNewCheckup()}>
            Show it
          </button>
          <button type="button" className="link" onClick={() => setReady(null)}>
            Not now
          </button>
        </div>
      )}

      {licenseFor && (
        <LicenseDialog
          robot={licenseFor}
          action="Download and run the check-up"
          onAccept={() => download(licenseFor)}
          onCancel={() => setLicenseFor(null)}
        />
      )}
    </div>
  );
}
