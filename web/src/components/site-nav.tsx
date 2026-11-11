"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { BOARDS } from "./boards";

/** The four boards in the top bar, from md up. */
export function SiteNav() {
  const pathname = usePathname();
  return (
    <nav aria-label="Boards">
      <ul className="flex gap-x-7 text-[15px] font-semibold">
        {BOARDS.map((b) => {
          const on = pathname === b.href;
          return (
            <li key={b.href}>
              <Link
                href={b.href}
                aria-current={on ? "page" : undefined}
                className={`relative inline-block py-1 transition-colors duration-150 ${on ? "text-ink" : "text-ink-2 hover:text-ink"}`}
              >
                {b.short}
                {on ? <span aria-hidden="true" className="absolute inset-x-0 bottom-0 h-0.5 bg-accent" /* taste-skill-ignore: 2px accent tab line (DESIGN.md) */ /> : null}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

const TABS = [{ href: "/", short: "Home" }, ...BOARDS];

/**
 * The phone's bottom bar: home and the four boards, in thumb reach on every page. A plain
 * bar one tone above the page, text only; the accent line marks the page on show, as in the
 * top bar. Hidden from md up, where SiteNav takes over.
 */
export function SiteTabs() {
  const pathname = usePathname();
  return (
    <nav aria-label="Pages" className="fixed inset-x-0 bottom-0 z-30 bg-s2 pb-[env(safe-area-inset-bottom)] md:hidden">
      <ul className="mx-auto grid max-w-[560px] grid-cols-5 px-[max(10px,env(safe-area-inset-left))] text-[13px] font-semibold">
        {TABS.map((t) => {
          const on = pathname === t.href;
          return (
            <li key={t.href}>
              <Link
                href={t.href}
                aria-current={on ? "page" : undefined}
                className={`flex h-(--tabbar-h) items-stretch justify-center transition-colors duration-150 active:bg-rule ${on ? "text-ink" : "text-ink-2"}`}
              >
                <span className="relative flex items-center">
                  {t.short}
                  {on ? <span aria-hidden="true" className="absolute inset-x-0 top-0 h-0.5 bg-accent" /* taste-skill-ignore: 2px accent tab line (DESIGN.md) */ /> : null}
                </span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
