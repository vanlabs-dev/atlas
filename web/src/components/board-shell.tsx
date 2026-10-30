import type { ReactNode } from "react";

// A board's parts. Surfaces separate by tone, not border; rules only in tables.
export function Panel({ title, children, className = "" }: { title: string; children: ReactNode; className?: string }) {
  return (
    <section aria-label={title} className={`min-w-0 rounded-[10px] bg-s1 p-5 sm:p-6 ${className}`}>
      <h2 className="pb-4 text-small text-ink-3">{title}</h2>
      {children}
    </section>
  );
}

/** Large Newsreader figures with a plain label, for a board's counts. */
export function Figures({ items }: { items: { value: ReactNode; label: string }[] }) {
  return (
    <dl className="grid gap-7">
      {items.map((k) => (
        <div key={k.label} className="grid grid-cols-[minmax(96px,auto)_1fr] items-baseline gap-4">
          <dd className="num font-display text-[clamp(44px,5vw,64px)] leading-[0.9]">{k.value}</dd>
          <dt className="text-body text-ink-2">{k.label}</dt>
        </div>
      ))}
    </dl>
  );
}

export const table = "w-full border-collapse text-body";
export const th = "whitespace-nowrap px-3.5 pb-3.5 text-left text-small font-normal text-ink-3";
export const td = "whitespace-nowrap border-t border-rule px-3.5 py-4 align-middle"; // taste-skill-ignore: rules only in real tables (DESIGN.md)
export const row = "transition-colors duration-150 hover:bg-s1 target:bg-s2";
