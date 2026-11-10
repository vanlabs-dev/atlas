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
