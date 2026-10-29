// Second check on committed fixtures, after the allowlist. Flags anything
// shaped like a secret, a private address, or an internal host detail.

/** SS58 addresses that may appear. None today: owner addresses are private. */
export const PUBLIC_ADDRESSES: ReadonlySet<string> = new Set();

const RULES: [string, RegExp][] = [
  ["token", /\b(?:sk|pk|rk|ghp|gho|ghs|github_pat|xox[abpr])[-_][A-Za-z0-9_-]{10,}/g],
  ["token", /\b\d{8,10}:[A-Za-z0-9_-]{35}\b/g],
  ["token", /\beyJ[\w-]{8,}\.[\w-]{8,}\./g],
  ["token", /\b[A-Za-z0-9+/_-]{40,}={0,2}/g],
  ["ip", /\b(?:\d{1,3}\.){3}\d{1,3}\b/g],
  ["host", /\b(?:localhost|raspberrypi|[a-z0-9-]+\.(?:local|lan|internal|home|arpa))\b/gi],
  ["host", /(?:\/home\/|~\/atlas|\bpi@)/g],
];

const SS58 = /\b5[1-9A-HJ-NP-Za-km-z]{46,47}\b/g;

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
