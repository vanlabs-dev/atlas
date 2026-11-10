"use client";

import type { BlockAnchor } from "@/data/block";
import { useBlocks } from "@/components/block-clock";

/** The estimated block in the band, from the same clock as the field's today edge. */
export function BandBlock({ anchor }: { anchor: BlockAnchor | null }) {
  const elapsed = useBlocks(anchor);
  if (!anchor || elapsed === null) return <>-</>;
  return <>{(anchor.block + Math.floor(elapsed)).toLocaleString("en-GB")}</>;
}
