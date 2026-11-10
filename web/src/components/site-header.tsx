import Link from "next/link";
import type { BlockAnchor } from "@/data/block";
import { HeaderClock } from "./block-clock";
import { SiteNav } from "./site-nav";

// Slim top bar: the subnt.dev wordmark, the four boards, the block readout. A fixed height,
// so the home page can lift its field under it: two rows on a phone, one from md up.
export function SiteHeader({ anchor }: { anchor: BlockAnchor | null }) {
  return (
    <header className="relative z-10">
      <div className="wrap flex h-[92px] flex-wrap content-center items-center gap-x-5 gap-y-2.5 md:h-[76px] md:flex-nowrap md:gap-x-10">
        <Link href="/" className="w-full font-display text-[26px] leading-none tracking-[-0.04em] md:w-auto md:text-[28px]" aria-label="subnt.dev, home">
          subnt<span className="text-accent">.</span>dev
        </Link>
        <SiteNav />
        <div className="ml-auto hidden md:block">
          <HeaderClock anchor={anchor} />
        </div>
      </div>
    </header>
  );
}
