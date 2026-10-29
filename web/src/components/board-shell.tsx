import type { ReactNode } from "react";

// Canvas of a board: one left edge, one right edge, gutters that match the
// home page.
export function BoardShell({ children }: { children: ReactNode }) {
  return <div className="mx-auto max-w-[1360px] px-4 pb-16 sm:px-8">{children}</div>;
}

export function Block({ title, children, className = "" }: { title: string; children: ReactNode; className?: string }) {
  return (
    <section aria-label={title} className={`min-w-0 bg-card p-5 ${className}`}>
      <h2 className="pb-4 text-[16px] font-medium">{title}</h2>
      {children}
    </section>
  );
}

export const th = "pb-2 text-small font-normal text-muted";
export const td = "h-[42px] border-t border-border align-middle"; // taste-skill-ignore: real table rows carry a rule
