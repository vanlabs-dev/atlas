import type { Board, MiningRow } from "./types";
import { FIELDS, onlyAll } from "./fields";
import fixture from "./fixtures/mining.json";

// Fixture source. A live source replaces this body and keeps the signature.
// Records are projected to the typed fields: nothing else reaches a page.
export async function getMining(): Promise<Board<MiningRow[]>> {
  return { generatedAt: fixture.generatedAt, data: onlyAll<MiningRow>(FIELDS.mining, fixture.data) };
}
