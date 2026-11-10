import type { Playback } from "./playback";
import type { RunEvents } from "./types";

/** The part of a run worth keeping: from a moment before the shove to a couple of seconds after the outcome. */
export function clipWindow(events: RunEvents, duration: number): { start: number; end: number } {
  if (events.pushAt === null) return { start: 0, end: duration };
  const outcome = events.recoveredAt ?? events.fallAt ?? events.pushAt + 1;
  return { start: Math.max(events.pushAt - 1.2, 0), end: Math.min(outcome + 2, duration) };
}

export function clipFileName(parts: string[]): string {
  const slug = parts
    .join("-")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return `creature-lab-${slug || "run"}.webm`;
}

export function canRecordClip(): boolean {
  return typeof MediaRecorder !== "undefined" && typeof HTMLCanvasElement.prototype.captureStream === "function";
}

function pickType(): string {
  for (const type of ["video/webm;codecs=vp9", "video/webm;codecs=vp8", "video/webm"]) {
    if (MediaRecorder.isTypeSupported(type)) return type;
  }
  return "";
}

/**
 * Records the 3D view while the run plays through its interesting window (slow motion included),
 * with the model's credit line burned in, and resolves with the finished WebM.
 */
export async function recordClip(
  source: HTMLCanvasElement,
  playback: Playback,
  window: { start: number; end: number },
  credit: string,
): Promise<Blob> {
  const frame = document.createElement("canvas");
  frame.width = source.width;
  frame.height = source.height;
  const ctx = frame.getContext("2d");
  if (!ctx) throw new Error("This browser cannot record the view.");
  const recorder = new MediaRecorder(frame.captureStream(30), {
    mimeType: pickType() || undefined,
    videoBitsPerSecond: 6_000_000,
  });
  const chunks: Blob[] = [];
  recorder.ondataavailable = (event) => event.data.size > 0 && chunks.push(event.data);
  const finished = new Promise<Blob>((resolve) => {
    recorder.onstop = () => resolve(new Blob(chunks, { type: "video/webm" }));
  });

  const resume = playback.getSnapshot();
  playback.seek(window.start);
  playback.play();
  recorder.start(200);
  await new Promise<void>((done) => {
    const draw = () => {
      ctx.drawImage(source, 0, 0, frame.width, frame.height);
      const size = Math.max(12, Math.round(frame.height / 40));
      ctx.font = `${size}px system-ui, sans-serif`;
      ctx.fillStyle = "rgba(10,15,26,0.7)";
      ctx.fillRect(0, frame.height - size * 2, frame.width, size * 2);
      ctx.fillStyle = "#e6ecf8";
      ctx.fillText(credit, size, frame.height - size * 0.7);
      if (playback.getSnapshot().time >= window.end) done();
      else requestAnimationFrame(draw);
    };
    requestAnimationFrame(draw);
  });
  recorder.stop();
  const blob = await finished;
  playback.seek(resume.time);
  if (!resume.playing) playback.pause();
  return blob;
}

export function saveBlob(blob: Blob, name: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}
