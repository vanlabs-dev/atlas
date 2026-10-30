import Link from "next/link";
import type { BlockAnchor } from "@/data/chain";
import { BlockClock } from "./block-clock";
import { SiteNav } from "./site-nav";

// Slim top bar: wordmark, the four boards, the block readout. On a phone
// the links wrap to their own row and stay visible.
export function SiteHeader({ anchor }: { anchor: BlockAnchor | null }) {
  return (
    <header className="relative z-10">
      <div className="mx-auto flex max-w-[1320px] flex-wrap items-center gap-x-9 gap-y-2 px-4 py-4 sm:px-8 md:h-[72px] md:py-0">
        <Link href="/" className="font-display text-[24px] leading-none tracking-[-0.01em]">
          Atlas
        </Link>
        <SiteNav />
        <div className="ml-auto hidden md:block">
          <BlockClock anchor={anchor} />
        </div>
      </div>
    </header>
  );
}
