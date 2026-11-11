import Link from "next/link";
import type { BlockAnchor } from "@/data/block";
import { HeaderClock } from "./block-clock";
import { SiteNav } from "./site-nav";

// Slim top bar, one row at every width: the subnt.dev wordmark, the block readout, and from md up
// the four boards. On a phone the boards are in the bottom bar (SiteTabs). The height is
// --header-h, so the home page can lift its field under it.
export function SiteHeader({ anchor }: { anchor: BlockAnchor | null }) {
  return (
    <header className="relative z-10">
      <div className="wrap flex h-(--header-h) items-center gap-x-10">
        <Link href="/" className="-my-2 py-2 font-display text-[24px] leading-none tracking-[-0.04em] md:text-[28px]" aria-label="subnt.dev, home">
          subnt<span className="text-accent">.</span>dev
        </Link>
        <div className="hidden md:block">
          <SiteNav />
        </div>
        <div className="ml-auto">
          <HeaderClock anchor={anchor} />
        </div>
      </div>
    </header>
  );
}
