// Runs against the real build output (`npm run test:build`): every file a
// visitor can receive, HTML, RSC payloads and client chunks, must be free
// of the fields the site dropped (change: subnt-site-honesty).
import { test } from "node:test";
import assert from "node:assert/strict";
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

const NEXT = join(import.meta.dirname, "../../.next");
const BANNED = /cueKind|cue_kind|netTaoMonth|net_tao_month|gateState|gate_state|"confidence"|paybackDays|requiredBand|rent_tao|ranks ahead of|"dn"|"amb"/;

function walk(dir: string, out: string[] = []): string[] {
  if (!existsSync(dir)) return out;
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p, out);
    else if (/\.(html|rsc|txt|js|json|meta|body)$/.test(name) || !name.includes(".")) out.push(p);
  }
  return out;
}

test("build output exists", () => {
  assert.ok(existsSync(join(NEXT, "BUILD_ID")), "run next build first");
});

test("served files carry no dropped field", () => {
  const served = [...walk(join(NEXT, "server/app")), ...walk(join(NEXT, "static"))].filter(
    (p) => !p.endsWith(".nft.json") && !/server\/app\/.*\.js$/.test(p),
  );
  assert.ok(served.some((p) => p.endsWith(".html")), "no prerendered HTML found");
  const hits = served.filter((p) => BANNED.test(readFileSync(p, "utf8"))).map((p) => p.slice(NEXT.length));
  assert.deepEqual(hits, []);
});
