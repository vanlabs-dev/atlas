import { test } from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { join } from "node:path";
import { binDaily } from "../scripts/bins.ts";
import { FIXTURES, parseArgs } from "../scripts/export-args.ts";
import { REMOTE, SIGNAL_CLASSES } from "../scripts/export-remote.ts";
import { PUBLIC_SIGNAL_CLASSES } from "../src/data/fields.ts";

const sum = (xs: number[]) => xs.reduce((a, b) => a + b, 0);

test("a commit exactly 7.0 days old is in the 7-day bins", () => {
  const d = binDaily([7.0, 7.000001, 0.2, -0.1, 30, 30.5, 90, 90.1]);
  assert.equal(d.length, 90);
  assert.equal(sum(d.slice(-7)), 3); // 7.0, 0.2 and the clock-skewed -0.1
  assert.equal(sum(d.slice(-30)), 5); // plus 7.000001 and 30
  assert.equal(sum(d), 7); // 90.1 drops
});

test("bins agree with the activity metric's windows", () => {
  // Same commits through fleet/atlas_fleet_metrics.compute_activity, bot
  // patterns included, so the bins match c7 and c30 by construction.
  const ages = [0, 0.5, 6.99, 7, 7.01, 13, 29.999, 30, 30.0001, 45, 89, 90];
  const py = String.raw`
import datetime, json, sys
sys.path.insert(0, "fleet")
import atlas_fleet_metrics as m
now = datetime.datetime(2026, 11, 4, tzinfo=datetime.timezone.utc)
ages = json.loads(sys.argv[1])
commits = [(now - datetime.timedelta(days=a), "dev@example.org") for a in ages]
commits.append((now - datetime.timedelta(days=1), "41898282+github-actions[bot]@users.noreply.github.com"))
bots = m.compile_bot_patterns(m.DEFAULT_METRICS_CFG["bot_author_patterns"])
act = m.compute_activity(commits, [7, 30, 90], now, bots)
print(json.dumps(act["windows"]))
`;
  const out = execFileSync("python3", ["-c", py, JSON.stringify(ages)], {
    cwd: join(import.meta.dirname, "../.."),
    encoding: "utf8",
  });
  const w = JSON.parse(out);
  const d = binDaily(ages);
  assert.equal(sum(d.slice(-7)), w["7"]);
  assert.equal(sum(d.slice(-30)), w["30"]);
  assert.equal(sum(d), w["90"]);
});

test("export leaves out bot authors and post-pass commits", () => {
  assert.match(REMOTE, /is_bot_author\(email, bots\) or when > anchor/);
  assert.match(REMOTE, /metrics\._commit_log/);
  assert.doesNotMatch(REMOTE, /--format=%cI"/);
});

test("fleet board is stamped with its activity pass, not compose time", () => {
  assert.match(REMOTE, /fleet_at = max\(passes\.values\(\)\)/);
  assert.match(REMOTE, /"fleet_at": fleet_at/);
});

test("export has no age cutoff", () => {
  assert.doesNotMatch(REMOTE, /cutoff|AGE_DAYS|<= \?/);
  assert.match(REMOTE, /latest_feasibility/);
});

test("export signal classes match the site's", () => {
  assert.deepEqual([...SIGNAL_CLASSES].sort(), [...PUBLIC_SIGNAL_CLASSES].sort());
  assert.match(REMOTE, /tier != 'shadow'/);
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
