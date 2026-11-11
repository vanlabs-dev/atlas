// The tab cycle of the home lead panel. The tabs advance on their own until
// the visitor takes one; from then on the visitor owns the panel for good.
// Import-free, so the node tests can load it.

export const CYCLE_MS = 8000;

export interface CycleState {
  /** The tab on show. */
  tab: number;
  /** Who chooses the tab. "visitor" is final. */
  owner: "auto" | "visitor";
  /** Enough of the panel is on screen. */
  inView: boolean;
  /** A pointer rests on the panel. */
  held: boolean;
}

export type CycleEvent =
  | { type: "enter" }
  | { type: "leave" }
  | { type: "hold" }
  | { type: "release" }
  /** The timer ran out. `tabs` is how many there are. */
  | { type: "tick"; tabs: number }
  /** The visitor chose a tab, by click or by key. */
  | { type: "take"; tab: number }
  /** Focus moved into the panel. */
  | { type: "focus" };

export const CYCLE_PHASES = ["cycling", "held", "offscreen", "taken", "still"] as const;
/**
 * cycling:   the timer runs and the red line fills under the tab.
 * held:      a pointer rests on the panel; the timer waits.
 * offscreen: the panel is out of view; the timer waits.
 * taken:     the visitor chose; the timer never runs again.
 * still:     reduced motion; the timer never runs.
 */
export type CyclePhase = (typeof CYCLE_PHASES)[number];

export const CYCLE_START: CycleState = { tab: 0, owner: "auto", inView: false, held: false };

export function cyclePhase(s: CycleState, reducedMotion: boolean): CyclePhase {
  if (s.owner === "visitor") return "taken";
  if (reducedMotion) return "still";
  if (!s.inView) return "offscreen";
  return s.held ? "held" : "cycling";
}

export function cycleStep(s: CycleState, e: CycleEvent): CycleState {
  switch (e.type) {
    case "enter":
      return s.inView ? s : { ...s, inView: true };
    case "leave":
      return s.inView ? { ...s, inView: false } : s;
    case "hold":
      return s.held ? s : { ...s, held: true };
    case "release":
      return s.held ? { ...s, held: false } : s;
    case "tick":
      // A late timer must not move a panel the visitor owns.
      return s.owner === "auto" && e.tabs > 0 ? { ...s, tab: (s.tab + 1) % e.tabs } : s;
    case "take":
      return { ...s, tab: e.tab, owner: "visitor" };
    case "focus":
      return s.owner === "visitor" ? s : { ...s, owner: "visitor" };
  }
}
