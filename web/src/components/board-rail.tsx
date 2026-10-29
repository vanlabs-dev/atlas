"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { BOARDS } from "./boards";

// Data-terminal shell: an icon rail on desktop, a labelled bottom bar on a
// phone. The selection is a 1px gold line on the rail's edge, nothing else.
export function BoardRail() {
  const pathname = usePathname();
  return (
    <nav
      aria-label="Boards"
      className="fixed inset-x-0 bottom-0 z-20 bg-ground md:inset-y-0 md:left-0 md:right-auto md:w-14 md:border-r md:border-border" /* taste-skill-ignore: rail edge */
    >
      <Link
        href="/"
        aria-label="Atlas home"
        className="hidden h-14 items-center justify-center text-ink md:flex"
      >
        <span className="cell text-[28px]" aria-hidden="true" />
      </Link>
      <ul className="grid grid-cols-4 md:mt-6 md:block">
        {BOARDS.map(({ href, label, icon: Icon }) => {
          const active = pathname === href;
          return (
            <li key={href} className="group relative">
              <Link
                href={href}
                aria-label={label}
                aria-current={active ? "page" : undefined}
                className={`flex flex-col items-center gap-1 py-2 text-[13px] transition-colors md:h-11 md:justify-center md:py-0 ${
                  active ? "text-ink" : "text-muted hover:text-ink"
                }`}
              >
                <Icon size={18} strokeWidth={1.75} aria-hidden="true" />
                <span className="md:hidden">{label.split(" ")[0]}</span>
                {active ? (
                  <span
                    aria-hidden="true"
                    className="absolute inset-x-6 top-0 h-px bg-accent md:inset-x-auto md:inset-y-2 md:right-[-1px] md:h-auto md:w-px" /* taste-skill-ignore: selection line */
                  />
                ) : null}
              </Link>
              <span
                role="tooltip"
                className="pointer-events-none absolute left-full top-1/2 z-30 ml-2 hidden -translate-y-1/2 whitespace-nowrap bg-surface px-2 py-1 text-small text-ink opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100 md:block"
              >
                {label}
              </span>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
