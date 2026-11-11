"use client";

import { usePathname } from "next/navigation";
import { useSyncExternalStore } from "react";
import { blockReading, blocksSince, blockText, type BlockAnchor, type BlockReading } from "@/data/block";

// One clock for the header readout, the home field's today edge and the band. It is an
// estimate from the last block Atlas saw, so the text says "est.".
const listeners = new Set<() => void>();
let timer: ReturnType<typeof setInterval> | undefined;

function subscribe(cb: () => void) {
  listeners.add(cb);
  timer ??= setInterval(() => listeners.forEach((l) => l()), 250);
  return () => {
    listeners.delete(cb);
    if (!listeners.size) {
      clearInterval(timer);
      timer = undefined;
    }
  };
}

/** Elapsed blocks since the anchor, fractional; null before hydration. */
export function useBlocks(anchor: BlockAnchor | null): number | null {
  return useSyncExternalStore(
    subscribe,
    () => (anchor ? blocksSince(anchor, Date.now()) : null),
    () => null,
  );
}

/** The clock as a named state: none, pending or ticking (src/data/block.ts). */
export function useBlockReading(anchor: BlockAnchor | null): BlockReading {
  return blockReading(anchor, useBlocks(anchor));
}

export function BlockClock({ anchor }: { anchor: BlockAnchor | null }) {
  const reading = useBlockReading(anchor);
  if (reading.state === "none") return null;
  return (
    <p className="flex items-baseline gap-2.5 text-small text-ink-3" aria-live="off" data-clock={reading.state}>
      est. block{" "}
      <b className="num font-medium text-ink-2">{blockText(reading)}</b>
      <span aria-hidden="true" className="relative top-[-3px] inline-block h-0.5 w-[46px] overflow-hidden bg-rule motion-reduce:hidden">
        <span
          className="absolute inset-0 origin-left bg-accent"
          style={{ transform: `scaleX(${reading.state === "ticking" ? reading.fraction : 0})` }}
        />
      </span>
    </p>
  );
}

/** The header readout, on the boards only: the home field carries its own. */
export function HeaderClock({ anchor }: { anchor: BlockAnchor | null }) {
  return usePathname() === "/" ? null : <BlockClock anchor={anchor} />;
}
