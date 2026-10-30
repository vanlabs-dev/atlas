"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { BOARDS } from "./boards";

export function SiteNav() {
  const pathname = usePathname();
  return (
    <nav aria-label="Boards">
      <ul className="flex flex-wrap gap-x-7 gap-y-1 text-body">
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
                {on ? <span aria-hidden="true" className="absolute inset-x-0 bottom-0 h-px bg-accent" /* taste-skill-ignore: 1px accent tab line (DESIGN.md) */ /> : null}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
