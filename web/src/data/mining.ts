import type { Board, MiningRow } from "./types";
import { FIELDS, onlyAll } from "./fields";
import fixture from "./fixtures/mining.json";
import { readBoard } from "./source";

// Live source: the published board from Supabase, else the committed
// fixture (src/data/source.ts). Records are projected to the typed fields:
// nothing else reaches a page, whatever the stored board holds.
export async function getMining(): Promise<Board<MiningRow[]>> {
  const board = await readBoard("mining", fixture);
  return { generatedAt: board.generatedAt, readAt: board.readAt, data: onlyAll<MiningRow>(FIELDS.mining, board.data) };
}
