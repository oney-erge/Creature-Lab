/** What the address bar says about the page: which view, robot and run, and whether two are compared. */

export interface Place {
  view: "robots" | "build";
  robot: string | null;
  run: string | null;
  compare: boolean;
  /** The creature preset open in the editor (`#/build/hexapod`). */
  preset: string | null;
}

export const HOME: Place = { view: "robots", robot: null, run: null, compare: false, preset: null };

const SAFE = /^[A-Za-z0-9_-]{1,64}$/;

/** `#/build/hexapod`, `#/robots/microduck` or `#/robots/microduck/3f2a9c01d4e7/compare`. Unknown parts are ignored. */
export function parseHash(hash: string): Place {
  const parts = hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  if (parts[0] === "build") {
    const preset = parts[1];
    return { ...HOME, view: "build", preset: preset && SAFE.test(preset) ? preset : null };
  }
  if (parts[0] !== "robots") return HOME;
  const [, robot, run, flag] = parts;
  return {
    view: "robots",
    robot: robot && SAFE.test(robot) ? robot : null,
    run: run && SAFE.test(run) ? run : null,
    compare: flag === "compare",
    preset: null,
  };
}

export function hashFor(place: Place): string {
  if (place.view === "build") return place.preset ? `#/build/${place.preset}` : "#/build";
  if (!place.robot) return "#/robots";
  const base = `#/robots/${place.robot}`;
  if (!place.run) return base;
  return place.compare ? `${base}/${place.run}/compare` : `${base}/${place.run}`;
}
