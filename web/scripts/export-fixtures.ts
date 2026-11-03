// Fixture export from the live Atlas stores on the Pi.
//
//   node scripts/export-fixtures.ts [--out <dir>] [ssh-target]
//
// Read-only on the Pi (see export-remote.ts). Records are built here from
// the field allowlist and rounded to four significant digits. Without
// --out it writes the committed fixtures, which publish to subnt.dev from
// main: run `npm test` and `npm run test:build` before committing them.
// With --out it writes a rehearsal there and never touches the fixtures.

import { execFileSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { pick, type Kind } from "./allowlist.ts";
import { binDaily } from "./bins.ts";
import { parseArgs } from "./export-args.ts";
import { DAYS, REMOTE } from "./export-remote.ts";

const args = parseArgs(process.argv.slice(2));
const KEY = join(process.env.HOME ?? "", ".ssh/id_ed25519_pi5");

type Source = Record<string, unknown>;

const raw = execFileSync(
  "ssh",
  ["-i", KEY, "-o", "BatchMode=yes", args.target, "cd ~/atlas && python3 -"],
  { input: REMOTE, maxBuffer: 64 * 1024 * 1024, encoding: "utf8" },
);
const src = JSON.parse(raw);
const all = (kind: Kind, list: Source[]) => list.map((r) => pick(kind, r));
const board = (generatedAt: string, data: unknown) => ({ generatedAt, data });
const activity = (src.activity as { netuid: number; ages: number[] | null }[]).map((a) => ({
  netuid: a.netuid,
  daily: a.ages === null ? null : binDaily(a.ages, DAYS),
}));

const fixtures = {
  mining: board(src.mining_at, all("mining", src.mining)),
  fleet: board(src.fleet_at, {
    rows: all("fleet", src.fleet),
    counts: pick("fleetCounts", src.counts),
    signals: all("signal", src.signals),
    activity: all("activity", activity),
  }),
  network: board(src.network_at, {
    vitals: all("vitals", src.vitals),
    gate: src.gate ? pick("gate", src.gate) : null,
    rotations: all("rotation", src.rotations),
    params: all("param", src.params),
  }),
  upgrades: board(src.now, {
    events: all("upgrade", src.upgrades),
    job: pick("upgradeJob", src.job),
  }),
};

// Day series stay on one line each; everything else is indented as usual.
const flat = (text: string) => text.replace(/\[\s+([\d,\s]+?)\s+\]/g, (_, xs: string) => `[${xs.split(/,\s*/).join(", ")}]`);

mkdirSync(args.out, { recursive: true });
for (const [name, value] of Object.entries(fixtures)) {
  writeFileSync(join(args.out, `${name}.json`), flat(JSON.stringify(value, null, 2)) + "\n");
  console.log(`wrote ${args.rehearsal ? args.out : "fixtures"}/${name}.json`);
}
