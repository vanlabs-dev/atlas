import type { Board, Fleet, FleetCounts } from "./types";
import { FIELDS, only, onlyAll, publicSignals } from "./fields";
import fixture from "./fixtures/fleet.json";
import { readBoard } from "./source";

// Live source: the published board from Supabase, else the committed
// fixture (src/data/source.ts). Records are projected to the typed fields:
// nothing else reaches a page, whatever the stored board holds.
export async function getFleet(): Promise<Board<Fleet>> {
  const board = await readBoard("fleet", fixture);
  const d = board.data as Record<string, unknown>;
  return {
    generatedAt: board.generatedAt,
    readAt: board.readAt,
    data: {
      rows: onlyAll(FIELDS.fleet, d.rows),
      counts: only<FleetCounts>(FIELDS.fleetCounts, d.counts),
      signals: publicSignals(onlyAll(FIELDS.signal, d.signals)),
      activity: onlyAll(FIELDS.activity, d.activity),
    },
  };
}
