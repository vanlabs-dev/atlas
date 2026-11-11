// Block timing the client clock needs. Import-free, so a client component
// can use it without pulling in the server data layer.

/** A block Atlas saw, and when. The site estimates the current block from it. */
export interface BlockAnchor {
  block: number;
  at: string;
}

// Bittensor seals a block every 12 seconds.
export const BLOCK_MS = 12_000;

/**
 * What the block clock can show.
 * none:    Atlas has no block to count from; the readout is left out.
 * pending: before the browser's clock is read (server HTML, first paint).
 * ticking: an estimate, with the fraction of the current block for the tick line.
 */
export type BlockReading =
  | { state: "none" }
  | { state: "pending" }
  | { state: "ticking"; block: number; fraction: number };

/** Blocks elapsed since the anchor at `nowMs`, in steps of 1/50 so a 250 ms timer re-renders only on change. */
export function blocksSince(anchor: BlockAnchor, nowMs: number): number {
  return Math.floor(((nowMs - Date.parse(anchor.at)) / BLOCK_MS) * 50) / 50;
}

export function blockReading(anchor: BlockAnchor | null, elapsed: number | null): BlockReading {
  if (!anchor) return { state: "none" };
  if (elapsed === null) return { state: "pending" };
  return { state: "ticking", block: anchor.block + Math.floor(elapsed), fraction: elapsed % 1 };
}

/** The block as text; a dash until the clock ticks. */
export const blockText = (r: BlockReading) => (r.state === "ticking" ? r.block.toLocaleString("en-GB") : "-");
