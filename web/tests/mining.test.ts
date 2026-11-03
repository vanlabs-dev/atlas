import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import type { MiningRow } from "../src/data/types.ts";
import { CUT, UNNAMED_CUT, UNRATED, VERDICT, codeText, headline, order, readBlock, reason } from "../src/lib/mining.ts";

const base: MiningRow = {
  netuid: 0, name: null, rank: null, verdict: null, gpuFloor: null, vramGb: null, gpuMentionFiles: null,
  cutReason: null, unratedReason: null, minerBurnPct: null, earnerCount: null, top1SharePct: null,
  top10SharePct: null, regCostTao: null, blockRef: null,
};
const r = (o: Partial<MiningRow>): MiningRow => ({ ...base, ...o });

test("a cut subnet comes after every ranked one", () => {
  // SN110 had the largest raw figure in the audit and was listed first.
  const rows = order([
    r({ netuid: 110, name: "Green", cutReason: "winner-take-all" }),
    r({ netuid: 9, name: "iota", rank: 2 }),
    r({ netuid: 4, name: "Targon", rank: 1 }),
    r({ netuid: 5, name: "x" }),
  ]);
  assert.deepEqual(rows.map((x) => x.netuid), [4, 9, 110, 5]);
  const h = headline(rows);
  assert.match(h, /First is SN4 Targon/);
  assert.doesNotMatch(h, /SN110|TAO/);
});

test("no rank-1 subnet means no head is named", () => {
  assert.match(headline([r({ netuid: 1, cutReason: "owner-capture" })]), /ranks none/);
});

test("every cut rung of the mining writer has public wording", () => {
  const src = readFileSync(join(import.meta.dirname, "../../fleet/atlas_fleet_mining.py"), "utf8");
  const cuts = [...src.matchAll(/^CUT_\w+ = "([^"]+)"/gm)].map((m) => m[1]);
  const unrated = [...src.matchAll(/^UNRATED_\w+ = "([^"]+)"/gm)].map((m) => m[1]);
  assert.ok(cuts.includes("above-budget-band") && cuts.includes("prune-risk"));
  for (const c of cuts) assert.ok(CUT[c], c);
  for (const u of unrated) assert.ok(UNRATED[u], u);
});

test("a hardware cut names no band and an unknown cut no code", () => {
  assert.equal(reason(r({ cutReason: "above-budget-band" })), "Needs a larger GPU");
  assert.doesNotMatch(Object.values(CUT).join(" "), /band|consumer|rent|\d+ ?GB/i);
  assert.equal(reason(r({ cutReason: "some-new-rung" })), UNNAMED_CUT);
  assert.equal(reason(r({ rank: 3 })), null);
});

test("no GPU code found, never a CPU claim or a VRAM figure", () => {
  assert.equal(codeText(r({ verdict: "possible", gpuMentionFiles: 3, gpuFloor: "0 GB VRAM (min_vram)", vramGb: 0 })), "No GPU code found; GPU mentioned in 3 files");
  assert.equal(codeText(r({ verdict: "possible", gpuMentionFiles: 1 })), "No GPU code found; GPU mentioned in 1 file");
  assert.equal(codeText(r({ verdict: "possible" })), "No GPU code found");
  assert.equal(codeText(r({ verdict: "needs-gpu", gpuFloor: "24 GB VRAM (min_vram)" })), "Needs a GPU, 24 GB VRAM");
  assert.equal(codeText(r({})), "Not scanned");
  assert.doesNotMatch(Object.values(VERDICT).join(" "), /CPU/);
});

test("read block is the one most rows carry", () => {
  assert.equal(readBlock([r({ blockRef: 5 }), r({ blockRef: 7 }), r({ blockRef: 7 })]), 7);
  assert.equal(readBlock([r({})]), null);
});
