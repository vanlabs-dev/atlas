// Fallback fixture refresh from the live Atlas stores on the Pi.
//
//   node scripts/export-fixtures.ts [--out <dir>] [ssh-target]
//
// The site reads its boards from Supabase (change: supabase-data-layer);
// these fixtures are only the fallback for when that store is down or not
// configured. The boards come from sitedata/atlas_sitedata.py, run on the
// Pi's checkout, so they are the same boards the Pi publisher uploads:
// the Pi must be on a commit that has sitedata/. Read-only on the Pi.
// Without --out it writes the committed fixtures: run `npm test` and
// `npm run test:build` before committing them. With --out it writes a
// rehearsal there and never touches the fixtures.

import { execFileSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { parseArgs } from "./export-args.ts";

const BOARDS = ["mining", "fleet", "network", "upgrades"] as const;

const args = parseArgs(process.argv.slice(2));
const KEY = join(process.env.HOME ?? "", ".ssh/id_ed25519_pi5");

const raw = execFileSync(
  "ssh",
  ["-i", KEY, "-o", "BatchMode=yes", args.target, "cd atlas && python3 sitedata/atlas_sitedata.py compose"],
  { maxBuffer: 64 * 1024 * 1024, encoding: "utf8" },
);
const boards = JSON.parse(raw) as Record<string, unknown>;

// Day series stay on one line each; everything else is indented as usual.
const flat = (text: string) => text.replace(/\[\s+([\d,\s]+?)\s+\]/g, (_, xs: string) => `[${xs.split(/,\s*/).join(", ")}]`);

mkdirSync(args.out, { recursive: true });
for (const name of BOARDS) {
  if (!boards[name]) throw new Error(`compose printed no ${name} board`);
  writeFileSync(join(args.out, `${name}.json`), flat(JSON.stringify(boards[name], null, 2)) + "\n");
  console.log(`wrote ${args.rehearsal ? args.out : "fixtures"}/${name}.json`);
}
