import type {
  BuildResponse,
  BuilderInfo,
  CreatureCatalog,
  ImproveResponse,
  Job,
  PackReport,
  RobotsResponse,
  RunCard,
  RunDetail,
  SceneDescription,
  ShoveResult,
} from "./types";

declare global {
  interface Window {
    /** Set by an exported copy of the app (`creature-lab app --export-static`): no server behind it. */
    CREATURE_LAB_STATIC?: boolean;
  }
}

/** True in an exported copy, which reads recorded files and cannot run anything new. */
export const STATIC = typeof window !== "undefined" && window.CREATURE_LAB_STATIC === true;

/**
 * Where an exported copy keeps what the live app serves at `path`: files under `data/`, next to
 * the page (so the copy works from any folder). Paths the export does not hold map to themselves.
 */
export function staticUrl(path: string): string {
  const robots = path.match(/^\/api\/robots\/([a-z0-9_]+)\/(runs|scene|thumbnail)$/);
  if (robots) return `data/robots/${robots[1]}/${robots[2] === "thumbnail" ? "thumbnail.jpg" : `${robots[2]}.json`}`;
  const mesh = path.match(/^\/api\/robots\/([a-z0-9_]+)\/mesh\/(\d+)$/);
  if (mesh) return `data/robots/${mesh[1]}/mesh/${mesh[2]}.bin`;
  const run = path.match(/^\/api\/runs\/([0-9a-f]+)(?:\/(poses|overlay|thumbnail))?$/);
  if (run) {
    const part = run[2];
    if (!part) return `data/runs/${run[1]}/detail.json`;
    return `data/runs/${run[1]}/${part === "thumbnail" ? "thumbnail.jpg" : `${part}.bin`}`;
  }
  if (path === "/api/robots") return "data/robots.json";
  return path;
}

/** The address to fetch: the live app's, or the recorded file in an exported copy. */
const at = (path: string): string => (STATIC ? staticUrl(path) : path);

// Changing requests carry this header; the server refuses them without it, so a page on
// another site cannot trigger a download or a check-up on this computer.
const GUARD = { "X-Creature-Lab": "1" };

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function check(response: Response): Promise<Response> {
  if (response.ok) return response;
  let message = `${response.status} ${response.statusText}`;
  try {
    const body = (await response.json()) as { detail?: string; error?: string };
    message = body.detail ?? body.error ?? message;
  } catch {
    /* not JSON: keep the status line */
  }
  throw new ApiError(message, response.status);
}

async function getJSON<T>(path: string): Promise<T> {
  return (await (await check(await fetch(at(path)))).json()) as T;
}

async function postJSON<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method: "POST",
    headers: { ...GUARD, "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  return (await (await check(response)).json()) as T;
}

async function deleteJSON<T>(path: string): Promise<T> {
  const response = await fetch(path, { method: "DELETE", headers: GUARD });
  return (await (await check(response)).json()) as T;
}

async function getBuffer(path: string): Promise<ArrayBuffer> {
  return await (await check(await fetch(at(path)))).arrayBuffer();
}

export const api = {
  robots: () => getJSON<RobotsResponse>("/api/robots"),
  runs: async (robot: string) => (await getJSON<{ runs: RunCard[] }>(`/api/robots/${robot}/runs`)).runs,
  run: (id: string) => getJSON<RunDetail>(`/api/runs/${id}`),
  checkRobotFolder: (path: string) => postJSON<PackReport>("/api/robots/validate", { path }),
  addRobotFolder: (path: string) => postJSON<PackReport>("/api/robots/add", { path }),
  removeRobot: (robot: string) => deleteJSON<{ removed: string }>(`/api/robots/${robot}`),
  scene: (robot: string) => getJSON<SceneDescription>(`/api/robots/${robot}/scene`),
  mesh: (robot: string, id: number) => getBuffer(`/api/robots/${robot}/mesh/${id}`),
  poses: (id: string) => getBuffer(`/api/runs/${id}/poses`),
  overlay: (id: string) => getBuffer(`/api/runs/${id}/overlay`),
  robotThumbnail: (robot: string) => at(`/api/robots/${robot}/thumbnail`),
  runThumbnail: (id: string) => at(`/api/runs/${id}/thumbnail`),
  reportUrl: (robot: string) => `/api/robots/${robot}/report/`,
  download: (robot: string) => postJSON<Job>(`/api/robots/${robot}/download`, { accept_license: true }),
  startCheckup: (robot: string) => postJSON<Job>(`/api/robots/${robot}/checkup`),
  whatIf: async (runId: string, change: string) =>
    (await postJSON<{ run: RunCard }>(`/api/runs/${runId}/whatif`, { change })).run,
  job: (id: string) => getJSON<Job>(`/api/jobs/${id}`),
  // A recorded copy has no jobs to resume.
  runningJobs: async () => (STATIC ? [] : (await getJSON<{ jobs: Job[] }>("/api/jobs")).jobs),
  builder: (preset: string) => postJSON<BuilderInfo>("/api/builder", { preset }),
  creaturePresets: () => getJSON<CreatureCatalog>("/api/creatures/presets"),
  buildCreature: (body: { preset: string; params: Record<string, number>; goal: string; simulate: boolean }) =>
    postJSON<BuildResponse>("/api/creatures/build", body),
  shoveCreature: (id: string) => postJSON<ShoveResult>(`/api/creatures/${id}/shove`),
  improveCreature: (id: string, tries = 30) => postJSON<ImproveResponse>(`/api/creatures/${id}/improve`, { tries }),
  creatureExport: (id: string, format: "json" | "mjcf" | "urdf") => `/api/creatures/${id}/export/${format}`,
  creatureMesh: (id: string, mesh: number) => getBuffer(`/api/creatures/${id}/mesh/${mesh}`),
  creaturePoses: (id: string) => getBuffer(`/api/creatures/${id}/poses`),
  creatureOverlay: (id: string) => getBuffer(`/api/creatures/${id}/overlay`),
};
