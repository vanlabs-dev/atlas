"use client";

// Data-terminal selection: the chosen option is marked by a 1px accent line
// exactly as wide as its label, on the bottom edge. Nothing else changes.
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
  return (
    <div role="radiogroup" aria-label={label} className="flex flex-wrap gap-x-6 gap-y-2 text-small">
      {options.map((o) => {
        const on = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={on}
            onClick={() => onChange(o.value)}
            className={`relative py-1.5 transition-colors ${on ? "text-ink" : "text-muted hover:text-ink"}`}
          >
            {o.label} <span className="text-muted">{o.count}</span>
            {on ? <span aria-hidden="true" className="absolute inset-x-0 bottom-0 h-px bg-accent" /* taste-skill-ignore: selection line */ /> : null}
          </button>
        );
      })}
    </div>
  );
}
