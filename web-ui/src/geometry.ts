/** Whether `p` lies inside a convex outline (either winding). Fewer than 3 points: never inside. */
export function pointInConvexPolygon(p: [number, number], polygon: [number, number][]): boolean {
  const n = polygon.length;
  if (n < 3) return false;
  let sign = 0;
  for (let i = 0; i < n; i++) {
    const a = polygon[i]!;
    const b = polygon[(i + 1) % n]!;
    const cross = (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0]);
    if (cross === 0) continue;
    const s = cross > 0 ? 1 : -1;
    if (sign === 0) sign = s;
    else if (s !== sign) return false;
  }
  return true;
}

/** Per-robot sizing for markers and the camera, from the robot's height in cm. */
export function robotUnit(heightCm: number): number {
  return Math.max(heightCm, 1) / 25; // Microduck (25 cm) is 1
}

export interface Framing {
  distance: number;
  lookHeight: number;
}

const FRAMING: Record<string, Framing> = {
  microduck: { distance: 0.62, lookHeight: 0.13 },
  unitree_g1: { distance: 2.6, lookHeight: 0.3 },
};

export function framingFor(robot: string, heightCm: number): Framing {
  return FRAMING[robot] ?? { distance: (heightCm / 100) * 2.4, lookHeight: 0.2 };
}

/** Length of the shove arrow in metres: grows with force, relative to a mid-strength shove. */
export function arrowLength(force: number, referenceN: number, unit: number): number {
  const strength = Math.min(Math.abs(force) / referenceN, 2);
  return (0.07 + 0.07 * strength) * unit;
}

/** Shove strength that draws a mid-length arrow: 4 N on a Microduck, 150 N on a G1. */
export function shoveReference(unit: number): number {
  return unit > 2 ? 150 : 4;
}
