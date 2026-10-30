import type { ReactNode } from "react";
import { DataAge } from "./data-age";

// Title of a board: what it is, its one finding, and the data age.
export function BoardHeader({ title, finding, at, children }: { title: string; finding: string; at: string; children?: ReactNode }) {
  return (
    <header className="pb-12 pt-[clamp(48px,8vw,112px)]">
      <h1 className="font-display text-section leading-none tracking-[-0.02em]">{title}</h1>
      <p className="mt-5 max-w-[52ch] text-lead text-ink-2">{finding}</p>
      <div className="mt-4">
        <DataAge at={at} />
      </div>
      {children}
    </header>
  );
}
