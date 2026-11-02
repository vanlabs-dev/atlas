"use client";

import { useEffect, useRef } from "react";

/** The closing name. It widens on the Archivo width axis as it scrolls into view. */
export function FootMark() {
  const ref = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const set = () => {
      const top = el.getBoundingClientRect().top;
      const p = Math.min(1, Math.max(0, (innerHeight - top) / (innerHeight * 0.85)));
      el.style.fontStretch = `${(62 + 63 * p).toFixed(1)}%`;
    };
    set();
    addEventListener("scroll", set, { passive: true });
    addEventListener("resize", set);
    return () => {
      removeEventListener("scroll", set);
      removeEventListener("resize", set);
    };
  }, []);
  return (
    <span
      ref={ref}
      aria-hidden="true"
      className="block whitespace-nowrap text-[clamp(96px,21vw,360px)] font-[880] leading-[0.8] tracking-[-0.05em] [font-stretch:125%] -ml-[0.04em]"
    >
      Atlas<span className="text-accent">.</span>
    </span>
  );
}
