// The story the home field tells: the hero, then three statements. In fly
// mode the page scroll gives a progress from 0 to 1; in swipe mode the
// statement strip gives a position from 0 to 2. Everything on screen (which
// statement shows, where the camera is, which labels are on) is a pure
// function of that one number. Import-free, so the node tests can load it.

export const FLIGHT_SCENES = ["hero", "rows", "days", "moving"] as const;
/** hero: the whole field. rows: "One row for every subnet". days: "90 days of commits". moving: "Where the code is moving". */
export type FlightScene = (typeof FLIGHT_SCENES)[number];

export const STATEMENTS = 3;
const clamp01 = (t: number) => Math.min(1, Math.max(0, t));

/** Scroll progress at which statement k (0 to 2) is centred. The last one lands a little before the end. */
export const stopAt = (k: number) => (k + 1) / STATEMENTS - (k === STATEMENTS - 1 ? 0.06 : 0);

/** The scene in charge at a scroll progress. */
export function sceneAtProgress(p: number): FlightScene {
  if (p < 1 / 6) return "hero";
  let best = 0;
  for (let k = 1; k < STATEMENTS; k++) if (Math.abs(p - stopAt(k)) < Math.abs(p - stopAt(best))) best = k;
  return FLIGHT_SCENES[best + 1];
}

/** The scene in charge at a strip position: 0 is the first statement, 2 the last. */
export function sceneAtSwipe(q: number): FlightScene {
  return FLIGHT_SCENES[Math.min(STATEMENTS - 1, Math.max(0, Math.round(q))) + 1];
}

export interface CopyPose {
  opacity: number;
  /** Vertical shift in px. */
  shift: number;
  hidden: boolean;
}

/** The hero copy leaves in the first tenth of the scroll. */
export function heroPose(p: number): CopyPose {
  return { opacity: Math.max(0, 1 - p / 0.09), shift: -p * 240, hidden: p > 0.1 };
}

/** Statement k fades in around its stop and out again. */
export function statementPose(p: number, k: number): CopyPose {
  const at = stopAt(k);
  const opacity = clamp01(1.6 - Math.abs(p - at) / 0.1);
  return { opacity, shift: (p - at) * -120, hidden: opacity < 0.02 };
}

/** The hero rests while the scroll is under this; the camera drifts and the field keeps rendering. */
export const REST_UNTIL = 0.06;

/** How much of the resting drift remains: 1 at the top, 0 once the flight starts. */
export const restWeight = (p: number) => Math.max(0, 1 - p / REST_UNTIL);

/** Which HTML labels show over the field during the scroll flight. */
export function flightLabels(p: number): { names: boolean; axis: boolean } {
  return { names: p < REST_UNTIL || p > 0.8, axis: p < REST_UNTIL || p > 0.45 };
}

const ease = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

/**
 * The camera leg at a scroll progress, for `stops` camera positions: travel
 * from stop `from` to the next by `t`. Each leg holds at both ends, so a
 * statement is read against a still camera.
 */
export function flightLeg(p: number, stops: number): { from: number; t: number } {
  const legs = stops - 1;
  const from = Math.min(legs - 1, Math.max(0, Math.floor(p * legs)));
  return { from, t: ease(clamp01((p * legs - from - 0.16) / 0.68)) };
}

/** The camera leg at a strip position: a straight blend, since the thumb is the easing. */
export function swipeLeg(q: number, stops: number): { from: number; t: number } {
  const x = Math.min(stops - 1, Math.max(0, q));
  const from = Math.min(stops - 2, Math.floor(x));
  return { from, t: x - from };
}
