import Link from "next/link";
import type { BoardLink } from "./boards";

// The mark, built large: each letter knocked out of its own block.
const BLOCKS = [
  { letter: "A", height: 1 },
  { letter: "T", height: 0.78 },
  { letter: "L", height: 0.9 },
  { letter: "A", height: 0.64 },
  { letter: "S", height: 0.84 },
];
const W = 1000;
const H = 320;
const GAP = 4;
const BW = (W - GAP * (BLOCKS.length - 1)) / BLOCKS.length;

export function SiteFooter({ boards, source }: { boards: BoardLink[]; source: string }) {
  return (
    <footer className="mt-[clamp(72px,9vw,128px)] bg-surface px-4 pb-8 pt-16 sm:px-10">
      <div className="mx-auto max-w-[1440px]">
        <svg viewBox={`0 0 ${W} ${H}`} className="block h-auto w-full" role="img" aria-label="Atlas">
          {BLOCKS.map((b, i) => {
            const x = i * (BW + GAP);
            const h = H * b.height;
            return (
              <g key={i}>
                <rect x={x} y={H - h} width={BW} height={h} className="fill-ink" />
                <text x={x + BW / 2} y={H - 22} textAnchor="middle" className="fill-surface text-[150px] font-bold">
                  {b.letter}
                </text>
              </g>
            );
          })}
        </svg>
        <div className="mt-14 grid gap-10 text-[16px] md:grid-cols-12">
          <nav aria-label="Boards" className="md:col-span-4">
            <h2 className="pb-3 font-bold">Boards</h2>
            <ul className="space-y-2">
              {boards.map((b) => (
                <li key={b.href}>
                  <Link href={b.href} className="underline-offset-4 hover:underline">
                    {b.label}
                  </Link>
                </li>
              ))}
            </ul>
          </nav>
          <div className="md:col-span-4">
            <h2 className="pb-3 font-bold">Source</h2>
            <ul className="space-y-2">
              <li>
                <a href={source} className="underline-offset-4 hover:underline">
                  vanlabs-dev/atlas on GitHub
                </a>
              </li>
              <li>
                <a href={`${source}/blob/main/LICENSE`} className="underline-offset-4 hover:underline">
                  MIT licence
                </a>
              </li>
            </ul>
          </div>
          <div className="md:col-span-4">
            <h2 className="pb-3 font-bold">Data</h2>
            <p>Read-only from public chain data and public repositories. No wallet, no tracking, no advice.</p>
          </div>
        </div>
        <div className="mt-14 flex items-center justify-between gap-6 text-[16px]">
          <p>&copy; 2026 vaNlabs</p>
          <a href="#top" className="bg-ink px-3 py-1.5 font-medium text-surface transition-transform active:translate-y-px">
            Back to top
          </a>
        </div>
      </div>
    </footer>
  );
}
