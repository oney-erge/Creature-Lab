import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import {
  type Overlay,
  type Poses,
  POSE_STRIDE,
  decodeMesh,
  headingAt,
  pushForceAt,
  supportAt,
  trunkAt,
} from "./decode";
import {
  type TopFace,
  arrowLength,
  framingFor,
  groundHeight,
  pointInConvexPolygon,
  robotUnit,
  shoveReferenceFor,
  topFaces,
} from "./geometry";
import { frameAt } from "./playback";
import { isSoftwareGL } from "./prefs";
import type { SceneDescription, TerrainDescription } from "./types";

// MuJoCo, the server and the films all use Z up; so does this scene.
THREE.Object3D.DEFAULT_UP.set(0, 0, 1);

const FOG = 0x24334d;
const TEAL = 0x2bc4a9;
const RED = 0xf2645e;
const AMBER = 0xf5c542;
const ORANGE = 0xff7a30;

interface Loaded {
  key: string;
  unit: number;
  /** A shove of this many newtons draws a mid-length arrow. */
  shoveReferenceN: number;
  bodies: THREE.Group[];
  root: THREE.Group;
}

export interface ViewOptions {
  follow: boolean;
  overlays: boolean;
}

/** An imperative three.js view of one robot at a time. React owns it through a ref. */
export class RobotView {
  private renderer: THREE.WebGLRenderer;
  private scene = new THREE.Scene();
  private camera: THREE.PerspectiveCamera;
  private controls: OrbitControls;
  private key: THREE.DirectionalLight;
  private floor: THREE.Mesh;
  private observer: ResizeObserver;
  /** Set whenever the picture could differ from the last one drawn. */
  private dirty = true;
  private frame = 0;
  private disposed = false;

  private loaded: Loaded | null = null;
  private poses: Poses | null = null;
  private overlay: Overlay | null = null;
  private fps = 50;
  private options: ViewOptions = { follow: true, overlays: true };
  private lastFocus: THREE.Vector3 | null = null;
  private time = 0;

  private markers = new THREE.Group();
  /** Stairs, a ramp, rough ground or stepping stones: one instanced box mesh. */
  private terrain: THREE.InstancedMesh | null = null;
  private faces: TopFace[] = [];
  private floorZ = 0;
  /** The area the feet hold up: a translucent fill with a thick edge, teal or red. */
  private supportFill: THREE.Mesh;
  private supportEdge: THREE.Mesh;
  private heading: THREE.Mesh;
  /** A thin line from the floor point up to the trunk, so the dot reads as "weight lands here". */
  private plumb = new THREE.Group();
  private plumbLine: THREE.Mesh;
  private arrow = new THREE.Group();
  private tmpA = new THREE.Quaternion();
  private tmpB = new THREE.Quaternion();

  /** True once the view has dropped shadows and extra resolution to keep up (no GPU, or slow). */
  lite = false;
  /** Called once, when the view switches itself to the simplified drawing. */
  onLite: (() => void) | null = null;
  private lastDraw = 0;
  private slowDraws = 0;

  constructor(private container: HTMLElement) {
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFShadowMap;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.05;
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.domElement.style.cssText = "display:block;width:100%;height:100%";
    container.appendChild(this.renderer.domElement);

    this.scene.fog = new THREE.Fog(FOG, 4, 30);
    this.camera = new THREE.PerspectiveCamera(38, 1, 0.01, 200);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.08;
    this.controls.maxPolarAngle = Math.PI / 2 - 0.04; // never below the floor
    this.controls.screenSpacePanning = false;

    this.scene.add(new THREE.HemisphereLight(0xb4c6e6, 0x182036, 1.15));
    this.key = new THREE.DirectionalLight(0xfff1dc, 2.6);
    this.key.castShadow = true;
    this.key.shadow.mapSize.set(2048, 2048);
    this.key.shadow.bias = -0.0004;
    this.key.shadow.normalBias = 0.002;
    this.scene.add(this.key, this.key.target);
    const rim = new THREE.DirectionalLight(0x6f94d6, 0.9);
    rim.position.set(-3, 3, 2);
    this.scene.add(rim);

    this.floor = new THREE.Mesh(
      new THREE.PlaneGeometry(400, 400),
      new THREE.MeshStandardMaterial({ roughness: 0.62, metalness: 0.08 }),
    );
    this.floor.receiveShadow = true;
    this.scene.add(this.floor);

    this.supportFill = new THREE.Mesh(
      new THREE.BufferGeometry().setAttribute("position", new THREE.BufferAttribute(new Float32Array(6 * 3 * 3), 3)),
      new THREE.MeshBasicMaterial({
        color: TEAL,
        transparent: true,
        opacity: 0.3,
        side: THREE.DoubleSide,
        depthWrite: false,
      }),
    );
    this.supportEdge = new THREE.Mesh(
      new THREE.BufferGeometry().setAttribute("position", new THREE.BufferAttribute(new Float32Array(8 * 6 * 3), 3)),
      new THREE.MeshBasicMaterial({
        color: TEAL,
        transparent: true,
        opacity: 0.95,
        side: THREE.DoubleSide,
        depthWrite: false,
      }),
    );
    this.supportFill.frustumCulled = false;
    this.supportEdge.frustumCulled = false;
    this.heading = new THREE.Mesh(
      new THREE.CylinderGeometry(1, 1, 0.12, 28),
      new THREE.MeshBasicMaterial({ color: AMBER }),
    );
    this.heading.rotation.x = Math.PI / 2; // a disc lying on the floor
    this.plumbLine = new THREE.Mesh(
      new THREE.CylinderGeometry(1, 1, 1, 8),
      new THREE.MeshBasicMaterial({ color: AMBER, transparent: true, opacity: 0.7 }),
    );
    this.plumbLine.rotation.x = Math.PI / 2; // along Z, from the floor up
    this.plumb.add(this.plumbLine);
    const shaft = new THREE.Mesh(
      new THREE.CylinderGeometry(0.1, 0.1, 1, 16),
      new THREE.MeshStandardMaterial({ color: ORANGE, emissive: ORANGE, emissiveIntensity: 0.35 }),
    );
    const head = new THREE.Mesh(
      new THREE.ConeGeometry(0.26, 0.42, 20),
      new THREE.MeshStandardMaterial({ color: ORANGE, emissive: ORANGE, emissiveIntensity: 0.35 }),
    );
    shaft.name = "shaft";
    head.name = "head";
    this.arrow.add(shaft, head);
    this.markers.add(this.supportFill, this.supportEdge, this.heading, this.plumb, this.arrow);
    this.scene.add(this.markers);

    this.controls.addEventListener("change", () => (this.dirty = true));
    this.observer = new ResizeObserver(() => this.resize());
    this.observer.observe(container);
    this.resize();
    if (isSoftwareGL(this.renderer.getContext())) this.enableLite();
    this.loop();
  }

  /** Simplified drawing for computers without graphics acceleration: no shadows, 1x resolution. */
  private enableLite(): void {
    if (this.lite) return;
    this.lite = true;
    this.renderer.setPixelRatio(1);
    this.renderer.shadowMap.enabled = false;
    this.key.castShadow = false;
    this.scene.traverse((object) => {
      const material = (object as THREE.Mesh).material as THREE.Material | undefined;
      if (material) material.needsUpdate = true;
    });
    this.resize();
    this.dirty = true;
    this.onLite?.();
  }

  // ---- loading ---------------------------------------------------------------------------
  /** Build the robot from its server-side description; `fetchMesh` returns a mesh payload. */
  async loadRobot(
    key: string,
    heightCm: number,
    description: SceneDescription,
    fetchMesh: (id: number) => Promise<ArrayBuffer>,
    reframe = true,
    shoveReferenceN?: number,
  ): Promise<void> {
    const geometries = new Map<number, THREE.BufferGeometry>();
    await Promise.all(
      description.meshes.map(async (mesh) => {
        const data = decodeMesh(await fetchMesh(mesh.id));
        const geometry = new THREE.BufferGeometry();
        geometry.setAttribute("position", new THREE.BufferAttribute(data.positions, 3));
        geometry.setIndex(new THREE.BufferAttribute(data.indices, 1));
        geometries.set(mesh.id, geometry);
      }),
    );
    if (this.disposed) return;
    this.clearRobot();
    const unit = robotUnit(heightCm);
    const root = new THREE.Group();
    const bodies = Array.from({ length: description.bodyCount }, () => {
      const group = new THREE.Group();
      root.add(group);
      return group;
    });
    for (const geom of description.geoms) {
      const geometry = geometries.get(geom.mesh);
      const body = bodies[geom.body];
      if (!geometry || !body) continue;
      const material = new THREE.MeshStandardMaterial({
        roughness: 0.46,
        metalness: 0.06,
        flatShading: true, // per-face shading, like the films: crisp servos, no normals to compute
      });
      material.color.setRGB(geom.rgba[0], geom.rgba[1], geom.rgba[2], THREE.SRGBColorSpace);
      const mesh = new THREE.Mesh(geometry, material);
      mesh.castShadow = true;
      mesh.receiveShadow = true;
      mesh.position.set(...geom.pos);
      mesh.quaternion.set(geom.quat[1], geom.quat[2], geom.quat[3], geom.quat[0]);
      body.add(mesh);
    }
    this.scene.add(root);
    this.loaded = { key, unit, shoveReferenceN: shoveReferenceFor(unit, shoveReferenceN), bodies, root };
    this.dress(unit);
    if (reframe) this.frameCamera();
    this.dirty = true;
  }

  private clearRobot(): void {
    if (!this.loaded) return;
    this.scene.remove(this.loaded.root);
    const seen = new Set<THREE.BufferGeometry>();
    this.loaded.root.traverse((object) => {
      if (object instanceof THREE.Mesh) {
        if (!seen.has(object.geometry)) {
          seen.add(object.geometry);
          object.geometry.dispose();
        }
        (object.material as THREE.Material).dispose();
      }
    });
    this.loaded = null;
  }

  /** Floor, light and fog sized to the robot: a 25 cm duck and a 1.3 m humanoid differ 5x. */
  private dress(unit: number): void {
    const tile = 0.12 * unit;
    const texture = checkerTexture();
    texture.repeat.set(400 / (2 * tile), 400 / (2 * tile));
    texture.anisotropy = this.renderer.capabilities.getMaxAnisotropy();
    const material = this.floor.material as THREE.MeshStandardMaterial;
    material.map?.dispose();
    material.map = texture;
    material.needsUpdate = true;
    (this.scene.fog as THREE.Fog).near = 3 * unit + 1;
    (this.scene.fog as THREE.Fog).far = 18 * unit + 8;
    const reach = 2.6 * unit;
    const cam = this.key.shadow.camera;
    cam.left = -reach;
    cam.right = reach;
    cam.top = reach;
    cam.bottom = -reach;
    cam.near = 0.1;
    cam.far = 12 * unit + 4;
    cam.updateProjectionMatrix();
    this.markers.scale.setScalar(1);
    this.heading.scale.set(0.02 * unit, 0.02 * unit, 0.02 * unit);
    this.camera.near = 0.01 * unit;
    this.camera.far = 80 * unit + 30;
    this.camera.updateProjectionMatrix();
    this.controls.minDistance = 0.15 * unit;
    this.controls.maxDistance = 8 * unit;
  }

  setRun(
    poses: Poses,
    overlay: Overlay,
    fps: number,
    reframe = true,
    terrain: TerrainDescription | null = null,
  ): void {
    this.poses = poses;
    this.overlay = overlay;
    this.fps = fps;
    this.setTerrain(terrain);
    // Same robot: keep the last focus, so following carries the camera (same angle and zoom) to
    // where this run starts. A new robot is framed afresh around its start.
    if (reframe) this.lastFocus = null;
    this.dirty = true;
    this.setTime(0);
    if (reframe) this.frameCamera();
  }

  /** Build the run's ground (or clear it for a flat floor). */
  private setTerrain(terrain: TerrainDescription | null): void {
    if (this.terrain) {
      this.scene.remove(this.terrain);
      this.terrain.geometry.dispose();
      (this.terrain.material as THREE.Material).dispose();
      this.terrain = null;
    }
    this.faces = terrain ? topFaces(terrain.boxes) : [];
    this.floorZ = terrain?.floorZ ?? 0;
    this.floor.position.z = this.floorZ;
    this.dirty = true;
    if (!terrain || terrain.boxes.length === 0) return;
    const mesh = new THREE.InstancedMesh(
      new THREE.BoxGeometry(2, 2, 2), // scaled by each box's half sizes
      new THREE.MeshStandardMaterial({ roughness: 0.7, metalness: 0.04 }),
      terrain.boxes.length,
    );
    const matrix = new THREE.Matrix4();
    const position = new THREE.Vector3();
    const rotation = new THREE.Quaternion();
    const scale = new THREE.Vector3();
    const colour = new THREE.Color();
    terrain.boxes.forEach((box, i) => {
      position.set(...box.pos);
      rotation.set(box.quat[1], box.quat[2], box.quat[3], box.quat[0]);
      scale.set(...box.half);
      mesh.setMatrixAt(i, matrix.compose(position, rotation, scale));
      mesh.setColorAt(i, colour.setRGB(box.rgba[0], box.rgba[1], box.rgba[2], THREE.SRGBColorSpace));
    });
    mesh.castShadow = !this.lite;
    mesh.receiveShadow = true;
    this.terrain = mesh;
    this.scene.add(mesh);
  }

  /** Height of the ground under a point (the floor's height on a flat floor). */
  private groundAt(x: number, y: number): number {
    return this.faces.length ? groundHeight(this.faces, this.floorZ, x, y) : this.floorZ;
  }

  /** Ground height the camera follows: averaged along the walk so a step does not jolt it, and
   * never down into a pit. */
  private followHeight(x: number, y: number, unit: number): number {
    if (!this.faces.length) return 0;
    let sum = 0;
    for (let k = -4; k <= 4; k++) sum += Math.max(this.groundAt(x + k * 0.025 * unit, y), 0);
    return sum / 9;
  }

  setOptions(options: ViewOptions): void {
    this.options = options;
    this.markers.visible = options.overlays;
    this.dirty = true;
  }

  // ---- per-frame state -------------------------------------------------------------------
  /** Pose the robot (interpolated between recorded frames) and the markers at run time `t`. */
  setTime(t: number): void {
    if (t === this.time && !this.dirty) return;
    this.time = t;
    this.dirty = true;
    const { poses, overlay, loaded } = this;
    if (!poses || !overlay || !loaded || poses.frames === 0) return;
    const { i0, i1, w } = frameAt(t, this.fps, poses.frames);
    const stride = poses.bodies * POSE_STRIDE;
    loaded.bodies.forEach((group, body) => {
      const a = i0 * stride + body * POSE_STRIDE;
      const b = i1 * stride + body * POSE_STRIDE;
      const d = poses.data;
      group.position.set(
        lerp(d[a]!, d[b]!, w),
        lerp(d[a + 1]!, d[b + 1]!, w),
        lerp(d[a + 2]!, d[b + 2]!, w),
      );
      this.tmpA.set(d[a + 4]!, d[a + 5]!, d[a + 6]!, d[a + 3]!);
      this.tmpB.set(d[b + 4]!, d[b + 5]!, d[b + 6]!, d[b + 3]!);
      group.quaternion.slerpQuaternions(this.tmpA, this.tmpB, w);
    });
    const trunk = trunkAt(overlay, i0);
    const trunkNext = trunkAt(overlay, i1);
    const fx = lerp(trunk[0], trunkNext[0], w);
    const fy = lerp(trunk[1], trunkNext[1], w);
    const focus = new THREE.Vector3(fx, fy, this.followHeight(fx, fy, loaded.unit));
    this.updateMarkers(i0, loaded.unit);
    this.follow(focus);
    // Keep the key light and its shadow box over the robot.
    this.key.target.position.copy(focus);
    this.key.position.set(focus.x + 2.2 * loaded.unit, focus.y - 3 * loaded.unit, 4.2 * loaded.unit);
  }

  private updateMarkers(frame: number, unit: number): void {
    const overlay = this.overlay;
    if (!overlay) return;
    const outline = supportAt(overlay, frame);
    const heading = headingAt(overlay, frame);
    const inside = pointInConvexPolygon(heading, outline);
    const z = 0.0015 * unit;
    const colour = inside || outline.length < 3 ? TEAL : RED;
    this.drawSupport(outline.slice(0, 8), z, 0.007 * unit, colour);
    this.heading.visible = outline.length > 0;
    const ground = this.groundAt(heading[0], heading[1]);
    this.heading.position.set(heading[0], heading[1], ground + z * 1.6);
    // The plumb line runs from the balance point on the ground up to the trunk's height.
    const trunkNow = trunkAt(overlay, frame);
    const height = Math.max((trunkNow[2] ?? 0) - ground, 0.02 * unit);
    this.plumb.visible = outline.length > 0;
    this.plumb.position.set(heading[0], heading[1], ground);
    this.plumbLine.scale.set(0.0035 * unit, height, 0.0035 * unit);
    this.plumbLine.position.z = height / 2;

    const force = pushForceAt(overlay, frame);
    this.arrow.visible = force !== 0;
    if (force !== 0) {
      const length = arrowLength(force, this.loaded?.shoveReferenceN ?? shoveReferenceFor(unit), unit);
      const headLength = 0.22 * length;
      const shaftLength = length - headLength;
      const gap = 0.05 * unit; // the tip stops this far short of the trunk
      const radius = 0.042 * unit; // the unit shaft has radius 0.1, so this is 0.0042 * unit
      const shaft = this.arrow.getObjectByName("shaft") as THREE.Mesh;
      const head = this.arrow.getObjectByName("head") as THREE.Mesh;
      // Built along +Y pointing at the trunk (at the origin): tail at -(gap + length).
      shaft.scale.set(radius, shaftLength, radius);
      shaft.position.set(0, -(gap + length) + shaftLength / 2, 0);
      head.scale.set(radius, headLength / 0.42, radius);
      head.position.set(0, -gap - headLength / 2, 0);
      // A shove toward -Y comes from the +Y side: turn the whole arrow half a turn.
      this.arrow.rotation.z = force > 0 ? 0 : Math.PI;
      const trunk = trunkAt(overlay, frame);
      this.arrow.position.set(trunk[0], trunk[1], trunk[2]);
    }
  }

  /** Fill the foot polygon and give it a thick edge; `colour` says whether the weight is inside. */
  private drawSupport(points: [number, number][], z: number, width: number, colour: number): void {
    const fill = this.supportFill.geometry.getAttribute("position") as THREE.BufferAttribute;
    const edge = this.supportEdge.geometry.getAttribute("position") as THREE.BufferAttribute;
    const n = points.length;
    let fillVerts = 0;
    // Each corner sits on the ground under it (a foot on each of two steps tilts the outline).
    const at = (x: number, y: number) => this.groundAt(x, y) + z;
    for (let i = 1; i + 1 < n; i++) {
      const [x0, y0] = points[0]!;
      const [x1, y1] = points[i]!;
      const [x2, y2] = points[i + 1]!;
      fill.setXYZ(fillVerts++, x0, y0, at(x0, y0));
      fill.setXYZ(fillVerts++, x1, y1, at(x1, y1));
      fill.setXYZ(fillVerts++, x2, y2, at(x2, y2));
    }
    this.supportFill.geometry.setDrawRange(0, fillVerts);
    fill.needsUpdate = true;
    this.supportFill.visible = fillVerts > 0;

    let edgeVerts = 0;
    const segments = n === 2 ? 1 : n;
    for (let i = 0; i < segments && n > 1; i++) {
      const [ax, ay] = points[i]!;
      const [bx, by] = points[(i + 1) % n]!;
      const dx = bx - ax;
      const dy = by - ay;
      const length = Math.hypot(dx, dy) || 1;
      const nx = (-dy / length) * (width / 2);
      const ny = (dx / length) * (width / 2);
      const quad: [number, number][] = [
        [ax + nx, ay + ny],
        [ax - nx, ay - ny],
        [bx + nx, by + ny],
        [bx + nx, by + ny],
        [ax - nx, ay - ny],
        [bx - nx, by - ny],
      ];
      for (const [x, y] of quad) edge.setXYZ(edgeVerts++, x, y, this.groundAt(x, y) + z * 1.15);
    }
    this.supportEdge.geometry.setDrawRange(0, edgeVerts);
    edge.needsUpdate = true;
    this.supportEdge.visible = edgeVerts > 0;
    (this.supportFill.material as THREE.MeshBasicMaterial).color.setHex(colour);
    (this.supportEdge.material as THREE.MeshBasicMaterial).color.setHex(colour);
  }

  private follow(focus: THREE.Vector3): void {
    if (this.options.follow && this.lastFocus) {
      const delta = focus.clone().sub(this.lastFocus);
      this.camera.position.add(delta);
      this.controls.target.add(delta);
    }
    this.lastFocus = focus;
  }

  /** Put the camera at a comfortable three-quarter view of the robot. */
  frameCamera(): void {
    if (!this.loaded) return;
    const { distance, lookHeight } = framingFor(this.loaded.key, this.loaded.unit * 25);
    const focus = this.lastFocus ?? new THREE.Vector3(0, 0, 0);
    const target = new THREE.Vector3(focus.x, focus.y, lookHeight * distance);
    this.controls.target.copy(target);
    this.camera.position.set(
      target.x + distance * 0.78,
      target.y - distance * 0.82,
      target.z + distance * 0.42,
    );
    this.controls.update();
  }

  // ---- loop ------------------------------------------------------------------------------
  private resize(): void {
    const { clientWidth: w, clientHeight: h } = this.container;
    if (w === 0 || h === 0) return;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.dirty = true;
  }

  /** Draw the next frame only when something changed, so a paused view costs nothing. */
  private loop = (): void => {
    if (this.disposed) return;
    this.controls.update();
    if (this.dirty) {
      this.dirty = false;
      this.renderer.render(this.scene, this.camera);
      // Back-to-back draws that each take over 66 ms (under 15 a second) mean this machine is
      // struggling: simplify instead of stuttering.
      const now = performance.now();
      const continuous = now - this.lastDraw < 250;
      this.slowDraws = continuous && now - this.lastDraw > 66 ? this.slowDraws + 1 : 0;
      this.lastDraw = now;
      if (this.slowDraws >= 30) this.enableLite();
    }
    this.frame = requestAnimationFrame(this.loop);
  };

  /** The drawing surface, for recording clips. */
  get canvas(): HTMLCanvasElement {
    return this.renderer.domElement;
  }

  /** The most recent time passed to setTime (for tests and screenshots). */
  get currentTime(): number {
    return this.time;
  }

  dispose(): void {
    this.disposed = true;
    cancelAnimationFrame(this.frame);
    this.observer.disconnect();
    this.controls.dispose();
    this.clearRobot();
    this.setTerrain(null);
    this.renderer.dispose();
    this.renderer.domElement.remove();
  }
}

function lerp(a: number, b: number, w: number): number {
  return a + (b - a) * w;
}

/** A dark two-tone checker with faint grid lines, in the colours of the films' studio floor. */
function checkerTexture(): THREE.CanvasTexture {
  const size = 256;
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext("2d")!;
  ctx.fillStyle = "#2a354c";
  ctx.fillRect(0, 0, size, size);
  ctx.fillStyle = "#232d42";
  ctx.fillRect(0, 0, size / 2, size / 2);
  ctx.fillRect(size / 2, size / 2, size / 2, size / 2);
  ctx.strokeStyle = "rgba(120,150,200,0.28)";
  ctx.lineWidth = 2;
  ctx.strokeRect(1, 1, size - 2, size - 2);
  ctx.beginPath();
  ctx.moveTo(size / 2, 0);
  ctx.lineTo(size / 2, size);
  ctx.moveTo(0, size / 2);
  ctx.lineTo(size, size / 2);
  ctx.stroke();
  const texture = new THREE.CanvasTexture(canvas);
  texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}
