"use client";

import Link from "next/link";
import { useState, type ReactNode } from "react";

export interface ShowcaseItem {
  href: string;
  label: string;
  fact: string;
  fragment: ReactNode;
}

// "Object on a disc", with the disc swapped for the square cell. The list of
// boards is a tab list; each tab shows a real fragment of that board.
export function Showcase({ items }: { items: ShowcaseItem[] }) {
  const [active, setActive] = useState(0);
  const item = items[active];

  return (
    <div className="grid gap-10 lg:grid-cols-12 lg:items-end">
      <div className="lg:col-span-5">
        <h2 id="boards-title" className="text-[clamp(28px,7vw,44px)] font-bold leading-[1.15] text-muted lg:text-[clamp(28px,2.9vw,44px)]">
          The four boards
        </h2>
        <div role="tablist" aria-label="Boards" aria-orientation="vertical" className="flex flex-col items-start">
          {items.map((it, i) => (
            <button
              key={it.href}
              id={`showcase-tab-${i}`}
              role="tab"
              type="button"
              aria-selected={i === active}
              aria-controls="showcase-panel"
              tabIndex={i === active ? 0 : -1}
              onClick={() => setActive(i)}
              onKeyDown={(e) => {
                const step = e.key === "ArrowDown" || e.key === "ArrowRight" ? 1 : e.key === "ArrowUp" || e.key === "ArrowLeft" ? -1 : 0;
                if (!step) return;
                e.preventDefault();
                const next = (i + step + items.length) % items.length;
                setActive(next);
                document.getElementById(`showcase-tab-${next}`)?.focus();
              }}
              className={`flex items-center gap-3 text-left text-[clamp(28px,7vw,44px)] font-bold leading-[1.15] transition-colors lg:text-[clamp(28px,2.9vw,44px)] ${
                i === active ? "text-ink" : "text-muted hover:text-ink"
              }`}
            >
              {i === active ? <span className="cell text-[0.5em]" aria-hidden="true" /> : null}
              {it.label}
            </button>
          ))}
        </div>
        <Link
          href={item.href}
          className="mt-8 inline-block bg-accent px-4 py-2 text-[16px] font-medium text-accent-ink transition-transform hover:-translate-y-px active:translate-y-px"
        >
          Open {item.label.toLowerCase()}
        </Link>
      </div>

      <div className="lg:col-span-7 lg:col-start-6">
        <div className="lg:relative lg:mx-auto lg:aspect-square lg:w-full lg:max-w-[64vh] lg:bg-surface">
          <div
            key={active}
            className="animate-in fade-in duration-300 lg:absolute lg:inset-x-[7%] lg:-top-[6%] lg:bottom-[11%] lg:overflow-hidden"
            role="tabpanel"
            id="showcase-panel"
            aria-labelledby={`showcase-tab-${active}`}
          >
            {item.fragment}
          </div>
        </div>
        <p className="mt-4 text-body lg:mx-auto lg:max-w-[64vh]">{item.fact}</p>
      </div>
    </div>
  );
}
