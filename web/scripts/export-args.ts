// Command line of the fixture export.
//
//   node scripts/export-fixtures.ts [--out <dir>] [ssh-target]
//
// Without --out the export writes the committed fixtures. With --out it
// writes only there, and never into the committed fixture directory, so a
// rehearsal cannot overwrite what the site serves.

import { resolve } from "node:path";

export const FIXTURES = resolve(import.meta.dirname, "../src/data/fixtures");
export const DEFAULT_TARGET = "pi@192.168.0.150";

export interface ExportArgs {
  target: string;
  out: string;
  rehearsal: boolean;
}

export function parseArgs(argv: string[]): ExportArgs {
  let out: string | null = null;
  let target = DEFAULT_TARGET;
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === "--out") {
      out = argv[++i] ?? "";
      if (!out) throw new Error("--out needs a directory");
    } else {
      target = argv[i];
    }
  }
  if (out === null) return { target, out: FIXTURES, rehearsal: false };
  const dir = resolve(out);
  if (dir === FIXTURES || dir.startsWith(FIXTURES + "/")) {
    throw new Error("--out may not be the committed fixture directory");
  }
  return { target, out: dir, rehearsal: true };
}
