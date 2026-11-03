import { test } from "node:test";
import assert from "node:assert/strict";
import { ALLOWLIST, bannedFields } from "../scripts/allowlist.ts";
import { FIELDS, only, onlyAll, publicSignals } from "../src/data/fields.ts";

test("allowlist maps no banned source field", () => {
  assert.deepEqual(bannedFields(), []);
});

test("banned-field guard catches a planted rent field", () => {
  for (const from of ["net_tao_month", "rent_band", "payback_days", "required_band", "band_assumed", "cut_detail", "cue_kind", "confidence", "gate_state"]) {
    const planted = { ...ALLOWLIST, mining: { ...ALLOWLIST.mining, leak: from } };
    assert.deepEqual(bannedFields(planted), [`mining.${from}`], from);
  }
});

test("allowlist and site field lists name the same fields", () => {
  for (const kind of ["mining", "fleet", "fleetCounts", "signal", "activity", "vitals", "gate", "rotation", "param", "upgrade", "upgradeJob"] as const) {
    assert.deepEqual(Object.keys(ALLOWLIST[kind]).sort(), [...FIELDS[kind]].sort(), kind);
  }
});

test("projection drops a field the type does not declare", () => {
  const row = only(FIELDS.fleet, { netuid: 4, cueKind: "up", score: 90 }) as Record<string, unknown>;
  assert.ok(!("cueKind" in row));
  assert.equal(row.netuid, 4);
  assert.equal(row.why, null);
  assert.deepEqual(onlyAll(FIELDS.mining, null), []);
});

test("only named, non-shadow signal classes pass", () => {
  const at = "2026-11-01T00:00:00Z";
  const kept = publicSignals([
    { class: "econ-code", tier: "instant", netuid: 1, createdAt: at },
    { class: "watchlist", tier: "instant", netuid: 2, createdAt: at },
    { class: "econ-code-minor", tier: "shadow", netuid: 3, createdAt: at },
    { class: "econ-code", tier: "shadow", netuid: 4, createdAt: at },
  ]);
  assert.deepEqual(kept.map((s) => s.netuid), [1]);
});
