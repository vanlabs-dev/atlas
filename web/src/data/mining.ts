import type { Board, MiningRow } from "./types";
import fixture from "./fixtures/mining.json";

// Fixture source. A live source replaces this body and keeps the signature.
export async function getMining(): Promise<Board<MiningRow[]>> {
  return fixture as Board<MiningRow[]>;
}
