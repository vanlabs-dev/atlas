import type { BlockAnchor } from "./block";
import { getNetwork } from "./network";
import { getUpgrades } from "./upgrades";

export { BLOCK_MS, type BlockAnchor } from "./block";

export async function getBlockAnchor(): Promise<BlockAnchor | null> {
  const [network, upgrades] = await Promise.all([getNetwork(), getUpgrades()]);
  const seen = [...network.data.params, ...upgrades.data.events]
    .filter((e) => e.block !== null)
    .map((e) => ({ block: e.block as number, at: e.observedAt }))
    .sort((a, b) => Date.parse(b.at) - Date.parse(a.at));
  return seen[0] ?? null;
}
