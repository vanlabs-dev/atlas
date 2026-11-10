import { test } from "node:test";
import assert from "node:assert/strict";
import { join } from "node:path";
import contract from "../../sitedata/allowlist.json" with { type: "json" };
import { FIXTURES, parseArgs } from "../scripts/export-args.ts";
import { PUBLIC_SIGNAL_CLASSES } from "../src/data/fields.ts";

// Composition, pick, rounding, binning and the read-only and no-age-limit
// rules are tested in sitedata/tests (change: supabase-data-layer).

test("composer signal classes match the site's", () => {
  assert.deepEqual([...contract.signal_classes].sort(), [...PUBLIC_SIGNAL_CLASSES].sort());
});

test("--out never targets the committed fixtures", () => {
  assert.deepEqual(parseArgs([]), { target: "pi@192.168.0.150", out: FIXTURES, rehearsal: false });
  assert.equal(parseArgs(["--out", "/tmp/x", "pi@h"]).out, "/tmp/x");
  assert.equal(parseArgs(["--out", "/tmp/x", "pi@h"]).target, "pi@h");
  assert.throws(() => parseArgs(["--out", FIXTURES]));
  assert.throws(() => parseArgs(["--out", join(FIXTURES, "sub")]));
  assert.throws(() => parseArgs(["--out", join(FIXTURES, "../fixtures/")]));
  assert.throws(() => parseArgs(["--out"]));
});
