"use client";

import { usePathname } from "next/navigation";
import { useSyncExternalStore } from "react";
import { BLOCK_MS, type BlockAnchor } from "@/data/chain";

// One clock for the header readout and the strata seal line. It is an
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
    () => (anchor ? Math.floor(((Date.now() - Date.parse(anchor.at)) / BLOCK_MS) * 50) / 50 : null),
    () => null,
  );
}

export function BlockClock({ anchor }: { anchor: BlockAnchor | null }) {
  const elapsed = useBlocks(anchor);
  if (!anchor) return null;
  const block = anchor.block + Math.floor(elapsed ?? 0);
  return (
    <p className="flex items-baseline gap-2.5 text-small text-ink-3" aria-live="off">
      est. block{" "}
      <b className="num font-medium text-ink-2">{elapsed === null ? "-" : block.toLocaleString("en-GB")}</b>
      <span aria-hidden="true" className="relative top-[-3px] inline-block h-0.5 w-[46px] overflow-hidden bg-rule motion-reduce:hidden">
        <span
          className="absolute inset-0 origin-left bg-accent"
          style={{ transform: `scaleX(${elapsed === null ? 0 : elapsed % 1})` }}
        />
      </span>
    </p>
  );
}

/** The header readout, on the boards only: the home field carries its own. */
export function HeaderClock({ anchor }: { anchor: BlockAnchor | null }) {
  return usePathname() === "/" ? null : <BlockClock anchor={anchor} />;
}
