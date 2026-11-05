import type { Board, Gate, Network } from "./types";
import { FIELDS, only, onlyAll } from "./fields";
import fixture from "./fixtures/network.json";

// Fixture source. A live source replaces this body and keeps the signature.
// Records are projected to the typed fields: nothing else reaches a page.
export async function getNetwork(): Promise<Board<Network>> {
  const d = fixture.data as Record<string, unknown>;
  return {
    generatedAt: fixture.generatedAt,
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
