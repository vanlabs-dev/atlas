import type { Board, Fleet } from "./types";
import fixture from "./fixtures/fleet.json";

// Fixture source. A live source replaces this body and keeps the signature.
export async function getFleet(): Promise<Board<Fleet>> {
  return fixture as Board<Fleet>;
}
