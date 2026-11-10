// Decoders for the binary payloads of creature_lab/web/scene.py (all little-endian float32/uint32).

export const SUPPORT_VERTICES = 8;
export const POSE_STRIDE = 7;
/** support outline (8 x/y pairs), extrapolated centre of mass (2), shove force (1), trunk (3) */
export const OVERLAY_STRIDE = SUPPORT_VERTICES * 2 + 2 + 1 + 3;

export interface MeshData {
  positions: Float32Array;
  indices: Uint32Array;
}

/** uint32 vertices, uint32 faces, float32[vertices*3], uint32[faces*3] */
export function decodeMesh(buffer: ArrayBuffer): MeshData {
  const header = new DataView(buffer);
  const vertices = header.getUint32(0, true);
  const faces = header.getUint32(4, true);
  const positions = new Float32Array(buffer, 8, vertices * 3);
  const indices = new Uint32Array(buffer, 8 + vertices * 12, faces * 3);
  return { positions, indices };
}

export interface Poses {
  frames: number;
  bodies: number;
  data: Float32Array;
}

/** float32 (frames, bodies, 7): position xyz then quaternion w, x, y, z */
export function decodePoses(buffer: ArrayBuffer, bodies: number): Poses {
  const data = new Float32Array(buffer);
  const frames = bodies === 0 ? 0 : Math.floor(data.length / (bodies * POSE_STRIDE));
  return { frames, bodies, data };
}

export interface Overlay {
  frames: number;
  data: Float32Array;
}

export function decodeOverlay(buffer: ArrayBuffer): Overlay {
  const data = new Float32Array(buffer);
  return { frames: Math.floor(data.length / OVERLAY_STRIDE), data };
}

/** The outline of the feet at a frame as [x, y] pairs (NaN padding dropped). */
export function supportAt(overlay: Overlay, frame: number): [number, number][] {
  const base = frame * OVERLAY_STRIDE;
  const points: [number, number][] = [];
  for (let i = 0; i < SUPPORT_VERTICES; i++) {
    const x = overlay.data[base + i * 2];
    const y = overlay.data[base + i * 2 + 1];
    if (x !== undefined && y !== undefined && !Number.isNaN(x)) points.push([x, y]);
  }
  return points;
}

export function headingAt(overlay: Overlay, frame: number): [number, number] {
  const base = frame * OVERLAY_STRIDE + SUPPORT_VERTICES * 2;
  return [overlay.data[base] ?? 0, overlay.data[base + 1] ?? 0];
}

export function pushForceAt(overlay: Overlay, frame: number): number {
  return overlay.data[frame * OVERLAY_STRIDE + SUPPORT_VERTICES * 2 + 2] ?? 0;
}

export function trunkAt(overlay: Overlay, frame: number): [number, number, number] {
  const base = frame * OVERLAY_STRIDE + SUPPORT_VERTICES * 2 + 3;
  return [overlay.data[base] ?? 0, overlay.data[base + 1] ?? 0, overlay.data[base + 2] ?? 0];
}
