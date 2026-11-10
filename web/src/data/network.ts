import type { Board, Gate, Network } from "./types";
import { FIELDS, only, onlyAll } from "./fields";
import fixture from "./fixtures/network.json";
import { readBoard } from "./source";

// Live source: the published board from Supabase, else the committed
// fixture (src/data/source.ts). Records are projected to the typed fields:
// nothing else reaches a page, whatever the stored board holds.
export async function getNetwork(): Promise<Board<Network>> {
  const board = await readBoard("network", fixture);
  const d = board.data as Record<string, unknown>;
  return {
    generatedAt: board.generatedAt,
    readAt: board.readAt,
    data: {
      vitals: onlyAll(FIELDS.vitals, d.vitals),
      gate: d.gate ? only<Gate>(FIELDS.gate, d.gate) : null,
      crossings: onlyAll(FIELDS.crossing, d.crossings),
      emission: onlyAll(FIELDS.emission, d.emission),
      emissionSince: typeof d.emissionSince === "string" ? d.emissionSince : null,
      params: onlyAll(FIELDS.param, d.params),
    },
  };
}
