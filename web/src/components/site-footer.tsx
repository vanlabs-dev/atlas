import Link from "next/link";
import { BOARDS, SOURCE } from "./boards";
import { FootMark } from "./foot-mark";

// The close: the name returns at full width, then the boards, the source and the notes.
export function SiteFooter() {
  return (
    <footer className="mt-[clamp(120px,13vw,200px)] overflow-x-clip">
      <div className="wrap">
        <FootMark />
      </div>
      <div className="wrap grid gap-10 pb-10 pt-14 text-body md:grid-cols-12">
        <p className="max-w-[34ch] text-ink-2 md:col-span-4">
          Read-only from public chain data and public repositories. No wallet, no tracking, no advice.
        </p>
        <nav aria-label="Boards, footer" className="md:col-span-3 md:col-start-7">
          <h2 className="pb-3 text-small text-ink-3">Boards</h2>
          <ul className="space-y-2">
            {BOARDS.map((b) => (
              <li key={b.href}>
                <Link href={b.href} className="font-semibold transition-colors duration-150 hover:text-accent-2">
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
              <a href={SOURCE} className="font-semibold transition-colors duration-150 hover:text-accent-2">
                vanlabs-dev/atlas on GitHub
              </a>
            </li>
            <li>
              <a href={`${SOURCE}/blob/main/LICENSE`} className="font-semibold transition-colors duration-150 hover:text-accent-2">
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
