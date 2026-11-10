import type { Board, UpgradeJob, Upgrades } from "./types";
import { FIELDS, only, onlyAll } from "./fields";
import fixture from "./fixtures/upgrades.json";
import { readBoard } from "./source";

// Live source: the published board from Supabase, else the committed
// fixture (src/data/source.ts). Records are projected to the typed fields:
// nothing else reaches a page, whatever the stored board holds.
export async function getUpgrades(): Promise<Board<Upgrades>> {
  const board = await readBoard("upgrades", fixture);
  const d = board.data as Record<string, unknown>;
  return {
    generatedAt: board.generatedAt,
    readAt: board.readAt,
    data: {
      events: onlyAll(FIELDS.upgrade, d.events),
      releases: onlyAll(FIELDS.release, d.releases),
      job: d.job ? only<UpgradeJob>(FIELDS.upgradeJob, d.job) : null,
    },
  };
}
