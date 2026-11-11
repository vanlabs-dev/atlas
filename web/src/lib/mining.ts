// Mining board order and wording. The order is the stored Atlas ranking:
// the site never re-sorts on a figure (mining-triage: consumers read the
// stored result). Import-free of aliases so the node tests can load it.

import type { MiningRow } from "../data/types.ts";

/** Public reason for each cut rung of the mining ladder. */
export const CUT: Record<string, string> = {
  "pool-side-switch-off": "Emission switched off",
  "identity-placeholder": "No subnet identity",
  "owner-capture": "Owner takes most",
  "no-independent-earner": "Only the owner earns",
  "winner-take-all": "Winner takes all",
  "prune-risk": "New miners pruned early",
  "not-minable": "No miner to run",
  // The band itself is operator material; the reason says only this.
  "above-budget-band": "Needs a larger GPU",
};

/** Public reason for each unrated marker. */
export const UNRATED: Record<string, string> = {
  "not-emitting": "Not emitting",
  "no-mechanism-figure": "No figure Atlas trusts",
  "no-budget-band": "Not ranked",
};

export const UNNAMED_CUT = "Cut, reason not named";
export const UNNAMED_UNRATED = "Not ranked, reason not named";

/** What the miner-code scan found. Never "runs on a CPU". */
export const VERDICT: Record<string, string> = {
  possible: "No GPU code found",
  "needs-gpu": "Needs a GPU",
  unknown: "Not readable",
  closed: "Closed source",
  stub: "Stub miner",
};

/**
 * Where a subnet stands on the mining ladder. The order of the checks is the
 * rule: a cut reason outranks a rank, and an unrated marker counts only
 * without a rank.
 * cut:      taken off the ladder, with a public reason.
 * ranked:   on the ladder at its stored rank.
 * unrated:  no rank, with a public reason.
 * unlisted: no rank and no reason recorded.
 */
export type Standing = "cut" | "ranked" | "unrated" | "unlisted";

export function standing(r: Pick<MiningRow, "rank" | "cutReason" | "unratedReason">): Standing {
  if (r.cutReason) return "cut";
  if (r.rank !== null) return "ranked";
  return r.unratedReason ? "unrated" : "unlisted";
}

export function reason(r: MiningRow): string | null {
  const s = standing(r);
  if (s === "cut") return CUT[r.cutReason as string] ?? UNNAMED_CUT;
  if (s === "unrated") return UNRATED[r.unratedReason as string] ?? UNNAMED_UNRATED;
  return null;
}

/** The mining table's filter, by what the code scan found. */
export type MiningFilter = "all" | "possible" | "needs-gpu" | "other";

export const MINING_FILTERS: { value: MiningFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "possible", label: "No GPU code found" },
  { value: "needs-gpu", label: "Needs a GPU" },
  { value: "other", label: "Not readable or not scanned" },
];

export const inMiningFilter = (filter: MiningFilter) => (r: Pick<MiningRow, "verdict">) =>
  filter === "all" ? true : filter === "other" ? r.verdict !== "possible" && r.verdict !== "needs-gpu" : r.verdict === filter;

export function codeText(r: MiningRow): string {
  if (!r.verdict) return "Not scanned";
  const base = VERDICT[r.verdict] ?? "Not readable";
  if (r.verdict === "possible") {
    const n = r.gpuMentionFiles ?? 0;
    return n > 0 ? `${base}; GPU mentioned in ${n} ${n === 1 ? "file" : "files"}` : base;
  }
  if (r.verdict === "needs-gpu" && r.gpuFloor) return `${base}, ${r.gpuFloor.replace(/\s*\(.*\)$/, "")}`;
  return base;
}

/** Ranked by Atlas rank, then cut subnets, then the rest, each by netuid. */
export function order(rows: MiningRow[]): MiningRow[] {
  const group = (r: MiningRow) => (r.rank !== null ? 0 : r.cutReason ? 1 : 2);
  return [...rows].sort(
    (a, b) => group(a) - group(b) || (a.rank ?? 0) - (b.rank ?? 0) || a.netuid - b.netuid,
  );
}

/** The read block the figures are valued at: the one most rows carry. */
export function readBlock(rows: MiningRow[]): number | null {
  const seen = new Map<number, number>();
  for (const r of rows) if (r.blockRef !== null) seen.set(r.blockRef, (seen.get(r.blockRef) ?? 0) + 1);
  let best: number | null = null;
  for (const [b, n] of seen) if (best === null || n > (seen.get(best) ?? 0)) best = b;
  return best;
}

export function headline(rows: MiningRow[]): string {
  const ranked = rows.filter((r) => r.rank !== null);
  const cut = rows.filter((r) => r.rank === null && r.cutReason).length;
  const first = ranked.find((r) => r.rank === 1);
  if (!first) return `Atlas ranks none of the ${rows.length} subnets for a new miner in this pass.`;
  return `Atlas ranks ${ranked.length} of ${rows.length} subnets for one new miner, after hardware cost. First is SN${first.netuid} ${first.name ?? "(name not recorded)"}. ${cut} are cut, with the reason in the table.`;
}
