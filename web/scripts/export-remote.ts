// The program the fixture export runs on the Pi, over ssh, from the live
// Atlas checkout. It is sitedata/compose.py (change: supabase-data-layer),
// sent on stdin with its signal classes inlined, so the Pi needs no
// matching checkout. Read-only: see compose.py.

import { readFileSync } from "node:fs";
import { join } from "node:path";
import contract from "../../sitedata/allowlist.json" with { type: "json" };

/** Signal classes the site names; anything else stays on the Pi. */
export const SIGNAL_CLASSES: string[] = contract.signal_classes;

export const DAYS = 90;

const COMPOSE = readFileSync(join(import.meta.dirname, "../../sitedata/compose.py"), "utf8");
const LOAD = /with open\(os\.path\.join\(HERE, "allowlist\.json"\)[\s\S]*?\n {4}SIGNAL_CLASSES = json\.load\(_handle\)\["signal_classes"\]\n/;
if (!LOAD.test(COMPOSE)) throw new Error("compose.py no longer loads its signal classes as expected");

export const REMOTE =
  COMPOSE.replace(LOAD, `SIGNAL_CLASSES = ${JSON.stringify(SIGNAL_CLASSES)}\n`)
    .replace('HERE = os.path.dirname(os.path.abspath(__file__))', 'HERE = os.path.abspath("sitedata")') +
  "\nprint(json.dumps(raw()))\n";
