import Link from "next/link";
import type { BlockAnchor } from "@/data/chain";
import { HeaderClock } from "./block-clock";
import { SiteNav } from "./site-nav";

// Slim top bar: wordmark, the four boards, the block readout. A fixed height,
// so the home page can lift its field under it. On a phone it stays one row.
export function SiteHeader({ anchor }: { anchor: BlockAnchor | null }) {
  return (
    <header className="relative z-10">
      <div className="wrap flex h-16 items-center gap-x-5 md:h-[76px] md:gap-x-10">
        <Link href="/" className="font-display text-[26px] leading-none tracking-[-0.04em] md:text-[28px]" aria-label="Atlas, home">
          Atlas<span className="text-accent">.</span>
        </Link>
        <SiteNav />
        <div className="ml-auto hidden md:block">
          <HeaderClock anchor={anchor} />
        </div>
      </div>
    </header>
  );
}
