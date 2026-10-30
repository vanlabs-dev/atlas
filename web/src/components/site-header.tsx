import Link from "next/link";
import type { BlockAnchor } from "@/data/chain";
import { HeaderClock } from "./block-clock";
import { SiteNav } from "./site-nav";

// Slim top bar: wordmark, the four boards, the block readout. On a phone
// the links wrap to their own row and stay visible.
export function SiteHeader({ anchor }: { anchor: BlockAnchor | null }) {
  return (
    <header className="relative z-10">
      <div className="wrap flex flex-wrap items-center gap-x-9 gap-y-2 py-4 md:h-[72px] md:py-0">
        <Link href="/" className="font-display text-[24px] leading-none tracking-[-0.01em]">
          Atlas
        </Link>
        <SiteNav />
        <div className="ml-auto hidden md:block">
          <HeaderClock anchor={anchor} />
        </div>
      </div>
    </header>
  );
}
