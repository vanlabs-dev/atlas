import type { Board, Fleet, FleetCounts } from "./types";
import { FIELDS, only, onlyAll, publicSignals } from "./fields";
import fixture from "./fixtures/fleet.json";

// Fixture source. A live source replaces this body and keeps the signature.
// Records are projected to the typed fields: nothing else reaches a page.
export async function getFleet(): Promise<Board<Fleet>> {
  const d = fixture.data as Record<string, unknown>;
  return {
    generatedAt: fixture.generatedAt,
    data: {
      rows: onlyAll(FIELDS.fleet, d.rows),
      counts: only<FleetCounts>(FIELDS.fleetCounts, d.counts),
      signals: publicSignals(onlyAll(FIELDS.signal, d.signals)),
      activity: onlyAll(FIELDS.activity, d.activity),
    },
  };
}
