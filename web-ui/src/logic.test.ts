import { describe, expect, it } from "vitest";
import {
  OVERLAY_STRIDE,
  POSE_STRIDE,
  SUPPORT_VERTICES,
  decodeMesh,
  decodeOverlay,
  decodePoses,
  headingAt,
  pushForceAt,
  supportAt,
  trunkAt,
} from "./decode";
import { dotsFor, featuredRun, groupRuns, limitText, outcomeTone, totals } from "./format";
import { arrowLength, framingFor, pointInConvexPolygon, robotUnit, shoveReference } from "./geometry";
import { HOLD_S, Playback, SLOW_FACTOR, frameAt, rateAt } from "./playback";
import { clipFileName, clipWindow } from "./clip";
import { HOME, hashFor, parseHash } from "./url";
import type { PolicySummary, RunCard, RunEvents, ShoveRow } from "./types";

const events: RunEvents = {
  pushAt: 4,
  pushFor: 0.2,
  pushN: 3,
  pushSide: "left",
  fallAt: 4.6,
  recoveredAt: null,
};

describe("decoding the server's binary payloads", () => {
  it("reads a mesh: header, then vertices, then faces", () => {
    const buffer = new ArrayBuffer(8 + 4 * 12 + 2 * 12);
    const view = new DataView(buffer);
    view.setUint32(0, 4, true);
    view.setUint32(4, 2, true);
    [0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1].forEach((v, i) => view.setFloat32(8 + i * 4, v, true));
    [0, 1, 2, 0, 2, 3].forEach((v, i) => view.setUint32(8 + 48 + i * 4, v, true));
    const mesh = decodeMesh(buffer);
    expect(mesh.positions.length).toBe(12);
    expect(Array.from(mesh.positions.slice(3, 6))).toEqual([1, 0, 0]);
    expect(Array.from(mesh.indices)).toEqual([0, 1, 2, 0, 2, 3]);
  });

  it("counts pose frames from the byte length", () => {
    const poses = decodePoses(new Float32Array(3 * 2 * POSE_STRIDE).buffer, 2);
    expect(poses.frames).toBe(3);
    expect(decodePoses(new ArrayBuffer(0), 0).frames).toBe(0);
  });

  it("reads the overlay fields at their documented offsets", () => {
    expect(OVERLAY_STRIDE).toBe(22);
    const data = new Float32Array(2 * OVERLAY_STRIDE).fill(NaN);
    const base = OVERLAY_STRIDE; // frame 1
    [0, 0, 1, 0, 1, 1, 0, 1].forEach((v, i) => (data[base + i] = v)); // a square outline
    data[base + SUPPORT_VERTICES * 2] = 0.5; // heading x
    data[base + SUPPORT_VERTICES * 2 + 1] = 0.25;
    data[base + SUPPORT_VERTICES * 2 + 2] = -3; // shove force
    [1, 2, 0.12].forEach((v, i) => (data[base + SUPPORT_VERTICES * 2 + 3 + i] = v));
    const overlay = decodeOverlay(data.buffer);
    expect(overlay.frames).toBe(2);
    expect(supportAt(overlay, 1)).toEqual([
      [0, 0],
      [1, 0],
      [1, 1],
      [0, 1],
    ]);
    expect(supportAt(overlay, 0)).toEqual([]); // all NaN: no foot on the floor
    expect(headingAt(overlay, 1)).toEqual([0.5, 0.25]);
    expect(pushForceAt(overlay, 1)).toBe(-3);
    expect(trunkAt(overlay, 1)[1]).toBe(2);
  });
});

describe("playback timing", () => {
  it("runs at normal speed away from the shove", () => {
    expect(rateAt(1, events, true, 1)).toBe(1);
    expect(rateAt(8, events, true, 1)).toBe(1);
  });

  it("slows to 0.3x through the shove and the fall, like the films", () => {
    expect(rateAt(4.3, events, true, 1)).toBeCloseTo(SLOW_FACTOR);
    expect(rateAt(5.0, events, true, 1)).toBeCloseTo(SLOW_FACTOR); // 0.4 s after the fall
    expect(rateAt(3.9, events, true, 1)).toBeGreaterThan(SLOW_FACTOR); // easing in
    expect(rateAt(3.9, events, true, 1)).toBeLessThan(1);
  });

  it("combines with the chosen speed and can be switched off", () => {
    expect(rateAt(4.3, events, true, 0.5)).toBeCloseTo(0.15);
    expect(rateAt(4.3, events, false, 0.5)).toBe(0.5);
    expect(rateAt(4.3, null, true, 1)).toBe(1);
  });

  it("slows for a shove that did not topple the robot, for under a second", () => {
    const ok = { ...events, fallAt: null };
    expect(rateAt(4.4, ok, true, 1)).toBeCloseTo(SLOW_FACTOR);
    expect(rateAt(5.5, ok, true, 1)).toBe(1);
  });

  it("finds the two frames around a time (frame k is recorded at (k+1)/50 s)", () => {
    expect(frameAt(0, 50, 500)).toEqual({ i0: 0, i1: 1, w: 0 });
    const mid = frameAt(0.05, 50, 500); // between frame 1 (0.04 s) and frame 2 (0.06 s)
    expect(mid.i0).toBe(1);
    expect(mid.w).toBeCloseTo(0.5);
    expect(frameAt(99, 50, 500)).toEqual({ i0: 499, i1: 499, w: 0 });
    expect(frameAt(3, 50, 1)).toEqual({ i0: 0, i1: 0, w: 0 });
  });

  it("plays, slows, holds the last frame, then loops", () => {
    const clock = new Playback();
    clock.load(10, events);
    clock.play();
    clock.tick(1);
    expect(clock.getSnapshot().time).toBeCloseTo(1);
    clock.seek(4.3);
    clock.tick(1); // slow-motion: one second of wall clock is 0.3 s of run
    expect(clock.getSnapshot().time).toBeCloseTo(4.6);
    clock.seek(9.99);
    clock.tick(1);
    expect(clock.getSnapshot().time).toBeGreaterThan(10); // still holding the end
    clock.tick(HOLD_S);
    expect(clock.getSnapshot().time).toBe(0);
  });

  it("does not advance while paused, and pressing play at the end starts over", () => {
    const clock = new Playback();
    clock.load(10, events, 2);
    clock.tick(5);
    expect(clock.getSnapshot().time).toBe(2);
    clock.seek(10);
    clock.play();
    expect(clock.getSnapshot().time).toBe(0);
    expect(clock.getSnapshot().playing).toBe(true);
  });

  it("clamps seeks and notifies subscribers", () => {
    const clock = new Playback();
    clock.load(10, events);
    let calls = 0;
    const stop = clock.subscribe(() => calls++);
    clock.seek(-5);
    expect(clock.getSnapshot().time).toBe(0);
    clock.seek(99);
    expect(clock.getSnapshot().time).toBe(10);
    clock.setSpeed(0.25);
    expect(calls).toBe(3);
    stop();
    clock.seek(1);
    expect(calls).toBe(3);
  });
});

describe("geometry", () => {
  const square: [number, number][] = [
    [0, 0],
    [1, 0],
    [1, 1],
    [0, 1],
  ];
  it("tests a point against a convex outline, either winding", () => {
    expect(pointInConvexPolygon([0.5, 0.5], square)).toBe(true);
    expect(pointInConvexPolygon([1.5, 0.5], square)).toBe(false);
    expect(pointInConvexPolygon([0.5, 0.5], [...square].reverse())).toBe(true);
  });
  it("never counts a single point or a line as standing on the feet", () => {
    expect(pointInConvexPolygon([0, 0], [[0, 0]])).toBe(false);
    expect(pointInConvexPolygon([0.5, 0], [[0, 0], [1, 0]])).toBe(false);
  });
  it("sizes things relative to the 25 cm Microduck", () => {
    expect(robotUnit(25)).toBe(1);
    expect(robotUnit(130)).toBeCloseTo(5.2);
    expect(shoveReference(1)).toBe(4);
    expect(shoveReference(5.2)).toBe(150);
    expect(arrowLength(8, 4, 1)).toBeCloseTo(0.21); // capped at twice the reference
    expect(arrowLength(2, 4, 1)).toBeCloseTo(0.105);
    expect(framingFor("microduck", 25).distance).toBeLessThan(framingFor("unitree_g1", 130).distance);
    expect(framingFor("new_robot", 100).distance).toBeCloseTo(2.4);
  });
});

const row = (stayedUp: number, gotUp: number, stayedDown: number, force = 3): ShoveRow => ({
  force,
  total: stayedUp + gotUp + stayedDown,
  stayedUp,
  gotUp,
  stayedDown,
  fallRun: null,
  okRun: null,
});

const card = (over: Partial<RunCard>): RunCard => ({
  id: "x",
  robot: "microduck",
  policy: "velstand",
  policyTitle: "Walk + get-up policy",
  title: "Baseline walk",
  kind: "baseline",
  outcome: "walked",
  outcomeText: "Walked 1.7 m",
  verdict: "",
  fallAt: null,
  recoveredAt: null,
  distance: 1.7,
  pushN: 0,
  pair: null,
  ...over,
});

describe("formatting results", () => {
  it("lists dots best first", () => {
    expect(dotsFor(row(2, 1, 1))).toEqual(["up", "up", "got", "down"]);
  });
  it("marks outcomes by how bad they are", () => {
    expect(outcomeTone("walked")).toBe("ok");
    expect(outcomeTone("fell_and_got_up")).toBe("good");
    expect(outcomeTone("fell")).toBe("bad");
  });
  it("says shove limits the way the report does", () => {
    const policy = { shoves: [row(8, 0, 0, 1), row(3, 0, 5, 8)] } as unknown as PolicySummary;
    expect(limitText(null, policy)).toBe("none (even 1 N)");
    expect(limitText(1, policy)).toBe("up to 1 N");
    expect(limitText(8, policy)).toBe("all tested (to 8 N)");
    expect(totals(policy)).toEqual({ down: 5, falls: 5, total: 16 });
  });
  it("opens on the story: a mid-strength shove the robot got up from", () => {
    const shove = (id: string, pushN: number, outcome: RunCard["outcome"]) =>
      card({ id, kind: "shove", pushN, outcome });
    const runs = [
      card({ id: "walk" }),
      shove("harsh-fall", 8, "fell"),
      shove("light-up", 1, "fell_and_got_up"),
      shove("mid-up", 3, "fell_and_got_up"),
      shove("hard-up", 8, "fell_and_got_up"),
    ];
    expect(featuredRun(runs)?.id).toBe("mid-up");
    expect(featuredRun([card({ id: "a" }), shove("b", 2, "fell"), shove("c", 6, "fell")])?.id).toBe("b");
    expect(featuredRun([card({ id: "a" })])?.id).toBe("a");
    expect(featuredRun([])).toBeUndefined();
  });
  it("groups runs in the order they arrive, with readable names", () => {
    const groups = groupRuns([
      card({ id: "a" }),
      card({ id: "b", kind: "shove" }),
      card({ id: "c" }),
      card({ id: "d", kind: "grip" }),
    ]);
    expect(groups.map((g) => g.label)).toEqual(["Walks", "Shoves", "Slippery floors"]);
    expect(groups[0]?.runs.map((r) => r.id)).toEqual(["a", "c"]);
  });
});

describe("the address bar", () => {
  it("round-trips a robot, a run and the compare flag", () => {
    const place = { view: "robots" as const, robot: "microduck", run: "3f2a9c01d4e7", compare: true, preset: null };
    expect(hashFor(place)).toBe("#/robots/microduck/3f2a9c01d4e7/compare");
    expect(parseHash(hashFor(place))).toEqual(place);
    expect(parseHash("#/robots/microduck")).toEqual({ ...HOME, robot: "microduck" });
  });
  it("knows the builder and falls back to home for anything else", () => {
    expect(hashFor({ ...HOME, view: "build" })).toBe("#/build");
    expect(hashFor({ ...HOME, view: "build", preset: "hexapod" })).toBe("#/build/hexapod");
    expect(parseHash("#/build/hexapod")).toEqual({ ...HOME, view: "build", preset: "hexapod" });
    expect(parseHash("#/build").view).toBe("build");
    expect(parseHash("")).toEqual(HOME);
    expect(parseHash("#/elsewhere/1")).toEqual(HOME);
  });
  it("never lets odd characters through into a request path", () => {
    expect(parseHash("#/robots/../../etc/passwd").robot).toBeNull();
    expect(parseHash("#/robots/microduck/<script>").run).toBeNull();
  });
});

describe("saving a clip", () => {
  it("covers a moment before the shove to two seconds after the outcome", () => {
    expect(clipWindow({ ...events, recoveredAt: 5.1 }, 10)).toEqual({ start: 2.8, end: 7.1 });
    expect(clipWindow(events, 10)).toEqual({ start: 2.8, end: 6.6 }); // fell at 4.6, stayed down
    expect(clipWindow({ ...events, fallAt: null }, 10)).toEqual({ start: 2.8, end: 7 }); // no fall: a second after the shove
    expect(clipWindow({ ...events, pushAt: null }, 10)).toEqual({ start: 0, end: 10 });
    expect(clipWindow({ ...events, recoveredAt: 9.5 }, 10).end).toBe(10); // never past the run
  });
  it("names the file after what it shows", () => {
    expect(clipFileName(["Microduck", "Walk-only policy", "3 N shove"])).toBe("creature-lab-microduck-walk-only-policy-3-n-shove.webm");
    expect(clipFileName(["", "!!"])).toBe("creature-lab-run.webm");
  });
});
