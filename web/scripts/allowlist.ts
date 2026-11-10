// Field allowlist for published site data. Each record is built from these
// names only, so a field the stores add later cannot flow to the site.
// The list lives in sitedata/allowlist.json, which the Pi publisher reads
// too (change: supabase-data-layer). Map: site field -> source field.
// Owner-specific data (holdings, hotkeys, wallets, rotation decisions) is
// never listed. Addresses are never listed.

import contract from "../../sitedata/allowlist.json" with { type: "json" };

export const ALLOWLIST = contract.kinds;

export type Kind = keyof typeof ALLOWLIST;

/**
 * Source fields that must never be listed. Net income, rent and payback let
 * a reader derive rent; the required band and its assumed flag are the
 * hardware rung; cut detail names the band; the cue, confidence and gate
 * state were dropped from the site (change: subnt-site-honesty). Income
 * and price figures are banned too: Atlas ranks by net income, so an
 * income figure beside the rank bounds the rent (rehearsal 2026-11-04:
 * 1.435 to 1.520 TAO a month).
 */
export const BANNED_SOURCE = new RegExp(contract.banned_source);

/** Source fields in the allowlist that match the banned pattern. */
export function bannedFields(list: Record<string, Record<string, string>> = ALLOWLIST): string[] {
  return Object.entries(list).flatMap(([kind, map]) =>
    Object.values(map).filter((from) => BANNED_SOURCE.test(from)).map((from) => `${kind}.${from}`),
  );
}

type Value = string | number | boolean | null | number[];

/** Fields that hold a day series, oldest first. Every other field is scalar. */
export const SERIES: Record<string, number> = contract.series;

/** Four significant digits: values are rounded, never exact live state. */
export function round(value: number): number {
  return Number.isInteger(value) ? value : Number(value.toPrecision(4));
}

function clean(value: unknown): Value {
  if (value === null || value === undefined) return null;
  if (typeof value === "number") return round(value);
  if (typeof value === "boolean") return value;
  // House style bans em dashes, and source prose carries some.
  if (typeof value === "string") return value.replace(/\u2014/g, "-");
  throw new Error(`non-scalar value ${JSON.stringify(value)}`);
}

function series(field: string, value: unknown): number[] | null {
  if (value === null || value === undefined) return null;
  const ok =
    Array.isArray(value) &&
    value.length === SERIES[field] &&
    value.every((v) => Number.isInteger(v) && v >= 0);
  if (!ok) throw new Error(`${field} must be ${SERIES[field]} non-negative integers`);
  return value as number[];
}

/** Build a record from the allowlist alone. Unlisted source fields drop. */
export function pick(kind: Kind, source: Record<string, unknown>): Record<string, Value> {
  const out: Record<string, Value> = {};
  for (const [field, from] of Object.entries(ALLOWLIST[kind])) {
    out[field] = field in SERIES ? series(field, source[from]) : clean(source[from]);
  }
  return out;
}
