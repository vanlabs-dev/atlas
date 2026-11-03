import type { Board, UpgradeJob, Upgrades } from "./types";
import { FIELDS, only, onlyAll } from "./fields";
import fixture from "./fixtures/upgrades.json";

// Fixture source. A live source replaces this body and keeps the signature.
// Records are projected to the typed fields: nothing else reaches a page.
export async function getUpgrades(): Promise<Board<Upgrades>> {
  const d = fixture.data as Record<string, unknown>;
  return {
    generatedAt: fixture.generatedAt,
    data: {
      events: onlyAll(FIELDS.upgrade, d.events),
      job: d.job ? only<UpgradeJob>(FIELDS.upgradeJob, d.job) : null,
    },
  };
}
