import { getNetwork } from "./network";
import { getUpgrades } from "./upgrades";

/** A block Atlas saw, and when. The site estimates the current block from it. */
export interface BlockAnchor {
  block: number;
  at: string;
}

// Bittensor seals a block every 12 seconds.
export const BLOCK_MS = 12_000;

export async function getBlockAnchor(): Promise<BlockAnchor | null> {
  const [network, upgrades] = await Promise.all([getNetwork(), getUpgrades()]);
  const seen = [...network.data.params, ...upgrades.data.events]
    .filter((e) => e.block !== null)
    .map((e) => ({ block: e.block as number, at: e.observedAt }))
    .sort((a, b) => Date.parse(b.at) - Date.parse(a.at));
  return seen[0] ?? null;
}
