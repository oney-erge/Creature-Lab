import type {
  BuildResponse,
  BuilderInfo,
  CreatureCatalog,
  Job,
  RobotsResponse,
  RunCard,
  RunDetail,
  SceneDescription,
} from "./types";

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
  return (await (await check(await fetch(path))).json()) as T;
}

async function postJSON<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method: "POST",
    headers: { ...GUARD, "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  return (await (await check(response)).json()) as T;
}

async function getBuffer(path: string): Promise<ArrayBuffer> {
  return await (await check(await fetch(path))).arrayBuffer();
}

export const api = {
  robots: () => getJSON<RobotsResponse>("/api/robots"),
  runs: async (robot: string) => (await getJSON<{ runs: RunCard[] }>(`/api/robots/${robot}/runs`)).runs,
  run: (id: string) => getJSON<RunDetail>(`/api/runs/${id}`),
  scene: (robot: string) => getJSON<SceneDescription>(`/api/robots/${robot}/scene`),
  mesh: (robot: string, id: number) => getBuffer(`/api/robots/${robot}/mesh/${id}`),
  poses: (id: string) => getBuffer(`/api/runs/${id}/poses`),
  overlay: (id: string) => getBuffer(`/api/runs/${id}/overlay`),
  robotThumbnail: (robot: string) => `/api/robots/${robot}/thumbnail`,
  runThumbnail: (id: string) => `/api/runs/${id}/thumbnail`,
  reportUrl: (robot: string) => `/api/robots/${robot}/report/`,
  download: (robot: string) => postJSON<Job>(`/api/robots/${robot}/download`, { accept_license: true }),
  startCheckup: (robot: string) => postJSON<Job>(`/api/robots/${robot}/checkup`),
  job: (id: string) => getJSON<Job>(`/api/jobs/${id}`),
  runningJobs: async () => (await getJSON<{ jobs: Job[] }>("/api/jobs")).jobs,
  builder: (preset: string) => postJSON<BuilderInfo>("/api/builder", { preset }),
  creaturePresets: () => getJSON<CreatureCatalog>("/api/creatures/presets"),
  buildCreature: (body: { preset: string; params: Record<string, number>; goal: string; simulate: boolean }) =>
    postJSON<BuildResponse>("/api/creatures/build", body),
  creatureMesh: (id: string, mesh: number) => getBuffer(`/api/creatures/${id}/mesh/${mesh}`),
  creaturePoses: (id: string) => getBuffer(`/api/creatures/${id}/poses`),
  creatureOverlay: (id: string) => getBuffer(`/api/creatures/${id}/overlay`),
};
