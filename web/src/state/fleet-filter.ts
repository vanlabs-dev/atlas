// Which tier tab the fleet board shows. Three things can decide it, and the
// newest intent wins: a link to one subnet (/fleet#sn20), the visitor's own
// tab choice, or the default. Import-free of aliases, so the node tests can
// load it.

import type { FleetTier } from "../data/types.ts";

export type FleetFilter = FleetTier | "all";

export const FLEET_FILTERS: { value: FleetFilter; label: string }[] = [
  { value: "head", label: "Head" },
  { value: "mid", label: "Middle" },
  { value: "quiet", label: "Quiet" },
  { value: "all", label: "All" },
];

export const DEFAULT_FILTER: FleetFilter = "head";

/** A tab the visitor chose, and the URL hash at that moment. */
export interface FilterChoice {
  filter: FleetFilter;
  atHash: string;
}

/**
 * default: nothing chose; the head tier shows.
 * link:    the URL names a subnet; the tab that holds its row shows.
 * visitor: the visitor chose a tab after the URL last named a subnet.
 */
export type FilterSource = "default" | "link" | "visitor";

/** The subnet a hash such as "#sn20" names, or null. */
export function hashNetuid(hash: string): number | null {
  const m = /^#sn(\d+)$/.exec(hash);
  return m ? Number(m[1]) : null;
}

/**
 * The tab to show. A choice holds until the hash moves to another subnet:
 * that is a newer intent, so the link wins again. Without this, a visitor
 * who chose "Quiet" and later followed a link to a head-tier subnet would
 * land on a tab that does not hold the row.
 */
export function fleetFilter(
  hash: string,
  targetTier: FleetTier | null,
  choice: FilterChoice | null,
): { filter: FleetFilter; source: FilterSource } {
  if (choice && (choice.atHash === hash || targetTier === null)) return { filter: choice.filter, source: "visitor" };
  if (targetTier !== null) return { filter: targetTier, source: "link" };
  return { filter: DEFAULT_FILTER, source: "default" };
}

export const inFilter = (filter: FleetFilter) => (row: { tier: FleetTier }) => filter === "all" || row.tier === filter;
