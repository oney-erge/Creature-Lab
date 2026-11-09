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
