"use client";

import { useRef } from "react";

// Text tabs that pick one option (a radio group). The chosen one is marked by a 1px
// accent line exactly as wide as its label, on the bottom edge. Arrow keys move the
// choice, as in any radio group. On a phone the row scrolls sideways inside itself
// and sticks to the top while the list below it scrolls (boards.css).
export function FilterTabs<T extends string>({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: { value: T; label: string; count: number }[];
  value: T;
  onChange: (v: T) => void;
}) {
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);
  const move = (from: number, key: string) => {
    const last = options.length - 1;
    const to =
      key === "ArrowRight" || key === "ArrowDown" ? (from === last ? 0 : from + 1)
      : key === "ArrowLeft" || key === "ArrowUp" ? (from === 0 ? last : from - 1)
      : key === "Home" ? 0
      : key === "End" ? last
      : null;
    if (to === null) return false;
    onChange(options[to].value);
    buttons.current[to]?.focus();
    buttons.current[to]?.scrollIntoView({ block: "nearest", inline: "nearest" });
    return true;
  };
  return (
    <div role="radiogroup" aria-label={label} className="filter-tabs text-body">
      {options.map((o, i) => {
        const on = o.value === value;
        return (
          <button
            key={o.value}
            ref={(b) => { buttons.current[i] = b; }}
            type="button"
            role="radio"
            aria-checked={on}
            tabIndex={on ? 0 : -1}
            onClick={() => onChange(o.value)}
            onKeyDown={(e) => { if (move(i, e.key)) e.preventDefault(); }}
            className={`relative py-1.5 transition-colors duration-150 ${on ? "text-ink" : "text-ink-2 hover:text-ink"}`}
          >
            {o.label} <span className="num text-ink-3">{o.count}</span>
            {on ? <span aria-hidden="true" className="absolute inset-x-0 bottom-0 h-px bg-accent" /* taste-skill-ignore: 1px accent tab line (DESIGN.md) */ /> : null}
          </button>
        );
      })}
    </div>
  );
}

/**
 * For a list under sticky FilterTabs: after a new choice, brings the top of the list back
 * into view when it has scrolled past, so a shorter list is not left off screen.
 */
export function useListTop<E extends HTMLElement>() {
  const ref = useRef<E>(null);
  const reset = () => {
    const el = ref.current;
    if (el && el.getBoundingClientRect().top < 0) el.scrollIntoView({ block: "start" });
  };
  return [ref, reset] as const;
}
