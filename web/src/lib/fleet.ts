// Fleet board wording. No direction cue (change: subnt-site-honesty): the
// gap between the code-activity rank and the 7-day price rank is shown as a
// distance only, never which of the two leads. Import-free of aliases so
// the node tests can load it.

/** Gap at which code and price count as apart; matches the board's count. */
export const APART_AT = 40;

export const COLD = "No commits for 30 days or more in the tracked repository";

const WHY: Record<string, string> = {
  emission: "Emission route changed",
  abandon: "Code gone quiet",
  fresh: "Economics code just changed",
  opaque: "Emission split not readable",
};

/** Why a subnet ranks, true for this row. */
export function whyText(why: string | null, divergence: number | null): string {
  if (!why || why === "quiet") return "No strong signal";
  if (why === "divergence") {
    return divergence !== null && Math.abs(divergence) >= APART_AT ? "Code and price apart" : "No strong signal";
  }
  return WHY[why] ?? "On the board";
}

/** The gap as an unsigned distance in places. */
export function gapPlaces(divergence: number | null): number | null {
  return divergence === null ? null : Math.abs(divergence);
}

export function gapText(divergence: number | null): string {
  const g = gapPlaces(divergence);
  return g === null ? "no price to rank" : `${g} ${g === 1 ? "place" : "places"} apart`;
}

/** Days since the last commit, said against the data day, never "today". */
export function lastCommitText(days: number | null): string {
  if (days === null) return "no commits read";
  if (days === 0) return "last commit on the data day";
  return `last commit ${days} ${days === 1 ? "day" : "days"} before the data`;
}
