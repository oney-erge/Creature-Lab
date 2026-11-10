// Shapes of what creature_lab/web/server.py returns. Keep in step with that file.

export type Outcome = "walked" | "fell_and_got_up" | "fell";
export type RunKind = "baseline" | "shove" | "grip" | "battery" | "payload" | "whatif" | "other";

export interface PolicyInfo {
  key: string;
  title: string;
  summary: string;
  getsUp: boolean;
}

export interface ShoveRow {
  force: number;
  total: number;
  stayedUp: number;
  gotUp: number;
  stayedDown: number;
  fallRun: string | null;
  okRun: string | null;
}

export interface ConditionRow {
  label: string;
  passed: boolean;
  relativeDistance: number;
  verdict: string;
  run: string | null;
}

export interface PolicySummary {
  policy: string;
  title: string;
  summary: string;
  getsUp: boolean;
  baseline: string;
  baselineRun: string | null;
  neverFallsUpTo: number | null;
  neverStaysDownUpTo: number | null;
  shoves: ShoveRow[];
  conditions: ConditionRow[];
}

export interface CheckupSummary {
  robot: string;
  folder: string;
  policies: PolicySummary[];
}

export interface RobotInfo {
  key: string;
  title: string;
  maker: string;
  summary: string;
  heightCm: number;
  credit: string;
  licenseNotice: string;
  nonCommercial: boolean;
  installed: boolean;
  hasResults: boolean;
  /** Rough time from nothing on disk to a finished first check-up; 0 when unknown. */
  firstRunSeconds: number;
  /** A short looping clip bundled with the app, shown before the robot is downloaded. */
  introClip: string | null;
  policies: PolicyInfo[];
  checkup: CheckupSummary | null;
}

export interface RobotsResponse {
  robots: RobotInfo[];
  missingPackages: string[];
}

export interface RunCard {
  id: string;
  robot: string;
  policy: string;
  policyTitle: string;
  title: string;
  kind: RunKind;
  outcome: Outcome;
  outcomeText: string;
  verdict: string;
  fallAt: number | null;
  recoveredAt: number | null;
  distance: number;
  pushN: number;
  /**
   * The same test under the robot's other policy, when there is one. For a "what if" run, the
   * run it was made from.
   */
  pair: string | null;
  /** For a "what if" run: what was changed, as a button label ("A harder shove"). */
  whatIf: string | null;
  /** The same change inside a sentence ("shoved harder (4.5 N)"). */
  whatIfShort: string | null;
}

export interface WhatIfOption {
  key: string;
  label: string;
}

export interface Evidence {
  label: string;
  value: string;
  detail: string;
}

export interface RunEvents {
  pushAt: number | null;
  pushFor: number;
  pushN: number;
  pushSide: "left" | "right";
  fallAt: number | null;
  recoveredAt: number | null;
}

export interface RunDetail extends RunCard {
  fps: number;
  frames: number;
  duration: number;
  scenario: Record<string, unknown>;
  cause: string | null;
  causeText: string | null;
  evidence: Evidence[];
  peakTiltDeg: number;
  events: RunEvents;
  tilt: number[];
  credit: string;
  /** One-click changes offered for this run (none for a "what if" run). */
  whatIfs: WhatIfOption[];
}

export interface SceneGeom {
  id: number;
  body: number;
  mesh: number;
  pos: [number, number, number];
  quat: [number, number, number, number];
  rgba: [number, number, number, number];
}

export interface SceneDescription {
  robot: string;
  bodyCount: number;
  poseStride: number;
  geoms: SceneGeom[];
  meshes: { id: number; vertices: number; faces: number }[];
}

export interface Job {
  id: string;
  kind: "download" | "checkup" | string;
  robot: string;
  state: "running" | "done" | "failed";
  progress: number;
  message: string;
  error: string | null;
  output: string | null;
}

export interface BuilderInfo {
  url: string;
}

export interface CreatureParam {
  key: string;
  label: string;
  min: number;
  max: number;
  step: number;
  initial: number;
  integer: boolean;
}

export interface CreaturePresetInfo {
  key: string;
  label: string;
  params: CreatureParam[];
}

export interface CreatureCatalog {
  presets: CreaturePresetInfo[];
  goals: { key: string; label: string }[];
}

/** A designed creature's run, shaped like a robot's so the same 3D view and timeline play it. */
export interface CreatureRun extends RunDetail {
  sizeCm: number;
  score: number;
  simulated: boolean;
  backend?: string;
}

export interface BuildResponse {
  scene: SceneDescription;
  run: CreatureRun;
  creature: { preset: string; params: Record<string, number>; goal: string; backend: string };
}
