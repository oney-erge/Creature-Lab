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

/** The robot's own reference when the server names one (an added robot), else the size guess. */
export function shoveReferenceFor(unit: number, declared?: number): number {
  return declared !== undefined && declared > 0 ? declared : shoveReference(unit);
}

/** One box of ground, as the server describes it (MuJoCo's quaternion order: w, x, y, z). */
export interface GroundBox {
  pos: [number, number, number];
  half: [number, number, number];
  quat: [number, number, number, number];
  rgba: [number, number, number, number];
}

/** The face a foot stands on: x and y extent, height at x0 and slope along x. */
export interface TopFace {
  x0: number;
  x1: number;
  y0: number;
  y1: number;
  z0: number;
  slope: number;
}

/** Top faces of the server's boxes. Boxes only ever tilt about y (a ramp), as on the server. */
export function topFaces(boxes: GroundBox[]): TopFace[] {
  return boxes.map(({ pos, half, quat }) => {
    const pitch = -2 * Math.atan2(quat[2], quat[0]); // positive rises along +x
    const [a, , b] = half;
    const topX = pos[0] - b * Math.sin(pitch);
    const topZ = pos[2] + b * Math.cos(pitch);
    return {
      x0: topX - a * Math.cos(pitch),
      x1: topX + a * Math.cos(pitch),
      y0: pos[1] - half[1],
      y1: pos[1] + half[1],
      z0: topZ - a * Math.sin(pitch),
      slope: Math.tan(pitch),
    };
  });
}

/** Height of the ground under (x, y): the highest top face there, else the floor. */
export function groundHeight(faces: TopFace[], floorZ: number, x: number, y: number): number {
  let z = floorZ;
  for (const f of faces) {
    if (x >= f.x0 && x <= f.x1 && y >= f.y0 && y <= f.y1) z = Math.max(z, f.z0 + f.slope * (x - f.x0));
  }
  return z;
}
