import type { Board, Upgrades } from "./types";
import fixture from "./fixtures/upgrades.json";

// Fixture source. A live source replaces this body and keeps the signature.
export async function getUpgrades(): Promise<Board<Upgrades>> {
  return fixture as Board<Upgrades>;
}
