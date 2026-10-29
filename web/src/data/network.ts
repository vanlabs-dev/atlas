import type { Board, Network } from "./types";
import fixture from "./fixtures/network.json";

// Fixture source. A live source replaces this body and keeps the signature.
export async function getNetwork(): Promise<Board<Network>> {
  return fixture as Board<Network>;
}
