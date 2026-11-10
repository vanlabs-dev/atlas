// Second check on published site data, after the allowlist. Flags anything
// shaped like a secret, a private address, an internal host detail, a
// dropped or rent-bounding field, or an em dash. The rules live in
// sitedata/scrub.json, which the Pi publisher applies to every board
// before upload (change: supabase-data-layer).

import contract from "../../sitedata/scrub.json" with { type: "json" };

/** SS58 addresses that may appear. None today: owner addresses are private. */
export const PUBLIC_ADDRESSES: ReadonlySet<string> = new Set(contract.public_addresses as string[]);

const RULES: [string, RegExp][] = contract.rules.map((r) => [r.kind, new RegExp(r.pattern, `g${r.flags}`)]);

const SS58 = new RegExp(contract.ss58, "g");

export function findLeaks(text: string): string[] {
  const found: string[] = [];
  for (const [kind, rule] of RULES) {
    for (const match of text.matchAll(rule)) found.push(`${kind}: ${match[0]}`);
  }
  for (const match of text.matchAll(SS58)) {
    if (!PUBLIC_ADDRESSES.has(match[0])) found.push(`address: ${match[0]}`);
  }
  return found;
}
