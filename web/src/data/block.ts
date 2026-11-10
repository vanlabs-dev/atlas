// Block timing the client clock needs. Import-free, so a client component
// can use it without pulling in the server data layer.

/** A block Atlas saw, and when. The site estimates the current block from it. */
export interface BlockAnchor {
  block: number;
  at: string;
}

// Bittensor seals a block every 12 seconds.
export const BLOCK_MS = 12_000;
