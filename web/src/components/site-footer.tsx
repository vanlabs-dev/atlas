import Link from "next/link";
import { BOARDS, SOURCE } from "./boards";

export function SiteFooter() {
  return (
    <footer className="mt-[clamp(96px,12vw,160px)] bg-s1">
      <div className="mx-auto grid max-w-[1320px] gap-10 px-4 pb-10 pt-14 text-[15px] sm:px-8 md:grid-cols-12">
        <div className="md:col-span-4">
          <Link href="/" className="font-display text-[32px] leading-none">
            Atlas
          </Link>
          <p className="mt-4 max-w-[34ch] text-ink-2">
            Read-only from public chain data and public repositories. No wallet, no tracking, no advice.
          </p>
        </div>
        <nav aria-label="Boards, footer" className="md:col-span-3 md:col-start-7">
          <h2 className="pb-3 text-small text-ink-3">Boards</h2>
          <ul className="space-y-2">
            {BOARDS.map((b) => (
              <li key={b.href}>
                <Link href={b.href} className="transition-colors duration-150 hover:text-accent-2">
                  {b.label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
        <div className="md:col-span-3">
          <h2 className="pb-3 text-small text-ink-3">Source</h2>
          <ul className="space-y-2">
            <li>
              <a href={SOURCE} className="transition-colors duration-150 hover:text-accent-2">
                vanlabs-dev/atlas on GitHub
              </a>
            </li>
            <li>
              <a href={`${SOURCE}/blob/main/LICENSE`} className="transition-colors duration-150 hover:text-accent-2">
                MIT licence
              </a>
            </li>
          </ul>
        </div>
        <p className="text-small text-ink-3 md:col-span-12">&copy; 2026 vaNlabs</p>
      </div>
    </footer>
  );
}
