"use client";

import { blockText, type BlockAnchor } from "@/data/block";
import { useBlockReading } from "@/components/block-clock";

/** The estimated block in the band, from the same clock as the field's today edge. */
export function BandBlock({ anchor }: { anchor: BlockAnchor | null }) {
  return <>{blockText(useBlockReading(anchor))}</>;
}
