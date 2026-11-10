import type { Outcome, PolicySummary, RunCard, ShoveRow } from "./types";

export type Tone = "good" | "ok" | "bad";

export function outcomeTone(outcome: Outcome): Tone {
  if (outcome === "walked") return "ok";
  return outcome === "fell_and_got_up" ? "good" : "bad";
}

export type Dot = "up" | "got" | "down";

/** One entry per shove at a strength, best result first. */
export function dotsFor(row: ShoveRow): Dot[] {
  return [
    ...Array<Dot>(row.stayedUp).fill("up"),
    ...Array<Dot>(row.gotUp).fill("got"),
    ...Array<Dot>(row.stayedDown).fill("down"),
  ];
}

export function dotLabel(row: ShoveRow): string {
  return `${row.force} N: ${row.stayedUp} stayed up, ${row.gotUp} fell and got up, ${row.stayedDown} stayed down`;
}

/** A shove limit in words, as the report says it. */
export function limitText(limit: number | null, policy: PolicySummary): string {
  const last = policy.shoves[policy.shoves.length - 1]?.force;
  const first = policy.shoves[0]?.force;
  if (limit === null) return `none (even ${first ?? "?"} N)`;
  if (limit === last) return `all tested (to ${limit} N)`;
  return `up to ${limit} N`;
}

export function totals(policy: PolicySummary): { down: number; falls: number; total: number } {
  let down = 0;
  let falls = 0;
  let total = 0;
  for (const row of policy.shoves) {
    down += row.stayedDown;
    falls += row.gotUp + row.stayedDown;
    total += row.total;
  }
  return { down, falls, total };
}

/** The middle one of runs sorted by shove strength: a story, not the weakest or the harshest. */
function middleShove(runs: RunCard[]): RunCard | undefined {
  const sorted = [...runs].sort((a, b) => a.pushN - b.pushN);
  return sorted[Math.floor((sorted.length - 1) / 2)];
}

/** The run to open first: a mid-strength shove the robot got up from (the story), else a fall. */
export function featuredRun(runs: RunCard[]): RunCard | undefined {
  const shoves = runs.filter((r) => r.kind === "shove");
  return (
    middleShove(shoves.filter((r) => r.outcome === "fell_and_got_up")) ??
    middleShove(shoves.filter((r) => r.outcome === "fell")) ??
    runs.find((r) => r.kind === "baseline") ??
    runs[0]
  );
}

export const KIND_LABEL: Record<string, string> = {
  baseline: "Walks",
  shove: "Shoves",
  grip: "Slippery floors",
  battery: "Weak batteries",
  payload: "Carried loads",
  other: "Other runs",
};

export function groupRuns(runs: RunCard[]): { kind: string; label: string; runs: RunCard[] }[] {
  const groups: { kind: string; label: string; runs: RunCard[] }[] = [];
  for (const run of runs) {
    let group = groups.find((g) => g.kind === run.kind);
    if (!group) {
      group = { kind: run.kind, label: KIND_LABEL[run.kind] ?? run.kind, runs: [] };
      groups.push(group);
    }
    group.runs.push(run);
  }
  return groups;
}

/** How bad an outcome is: 0 stayed up, 1 fell but got up, 2 stayed down. */
export function severity(outcome: Outcome): number {
  return outcome === "walked" ? 0 : outcome === "fell_and_got_up" ? 1 : 2;
}

/** What two policies did on the same shove, in one sentence. `a` is the one being looked at. */
export function compareSentence(a: RunCard, b: RunCard): string {
  const left = severity(a.outcome);
  const right = severity(b.outcome);
  const name = (run: RunCard) => `The ${run.policyTitle.charAt(0).toLowerCase()}${run.policyTitle.slice(1)}`;
  const did = (run: RunCard) => {
    if (run.outcome === "walked") return "stayed on its feet";
    if (run.outcome === "fell_and_got_up") return `fell and was ${run.outcomeText.toLowerCase()}`;
    return "fell and stayed down";
  };
  if (left === right) return `Both policies ended the same way: ${did(a)}.`;
  const better = right < left ? b : a;
  const worse = right < left ? a : b;
  return `${name(better)} ${did(better)}; ${name(worse).toLowerCase()} ${did(worse)}.`;
}

export type Filter = "all" | "down" | "got-up" | "up";

/** Whether a run belongs under the history filter (by how it ended). */
export function matchesFilter(run: RunCard, filter: Filter): boolean {
  switch (filter) {
    case "down":
      return run.outcome === "fell";
    case "got-up":
      return run.outcome === "fell_and_got_up";
    case "up":
      return run.outcome === "walked";
    default:
      return true;
  }
}

/** A time worth saying out loud: "under a minute", "about a minute", "about 2 minutes". */
export function roughDuration(seconds: number): string {
  if (seconds <= 0) return "a minute or two";
  if (seconds < 50) return "under a minute";
  if (seconds < 100) return "about a minute";
  return `about ${Math.round(seconds / 60)} minutes`;
}

/** The robot to open first on a clean machine: the one whose first check-up finishes soonest. */
export function quickestStart<T extends { firstRunSeconds: number }>(robots: T[]): T | undefined {
  const timed = robots.filter((r) => r.firstRunSeconds > 0).sort((a, b) => a.firstRunSeconds - b.firstRunSeconds);
  return timed[0] ?? robots[0];
}
