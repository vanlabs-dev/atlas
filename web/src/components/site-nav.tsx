import Link from "next/link";
import { BOARDS } from "./boards";
import { Wordmark } from "./wordmark";

export function SiteNav() {
  return (
    <header className="mx-auto flex max-w-[1440px] flex-wrap items-baseline justify-between gap-x-8 gap-y-3 px-4 pt-7 sm:px-10">
      <Wordmark />
      <nav aria-label="Boards">
        <ul className="flex flex-wrap gap-x-6 gap-y-2 text-[16px]">
          {BOARDS.map((b) => (
            <li key={b.href}>
              <Link href={b.href} className="underline-offset-4 hover:underline">
                {b.label.split(" ")[0]}
              </Link>
            </li>
          ))}
        </ul>
      </nav>
    </header>
  );
}
