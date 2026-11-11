"use client";

import { useEffect, useRef, useState, type ElementType, type ReactNode } from "react";

/**
 * Runs a part's motion once, as it enters the screen. Three states, on
 * data-reveal:
 *   (no attribute)  the server markup, which is the finished state;
 *   "armed"         the start state, set only for a part still below the fold;
 *   "shown"         set when it arrives; final.
 * A part already on screen at load never arms. CSS in home.css does the
 * moving, and reduced motion keeps the finished state.
 */
export type RevealState = "armed" | "shown";
const set = (el: HTMLElement, state: RevealState) => el.setAttribute("data-reveal", state);

export function Reveal({
  as: Tag = "div",
  className,
  children,
  threshold = 0.3,
}: {
  as?: ElementType;
  className?: string;
  children: ReactNode;
  threshold?: number;
}) {
  const ref = useRef<HTMLElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el || !("IntersectionObserver" in window)) return;
    // "shown" is final: Next re-runs this effect when it brings the page back, and a part must not re-arm.
    if (el.getAttribute("data-reveal") === "shown" || el.getBoundingClientRect().top < innerHeight) return;
    set(el, "armed");
    const io = new IntersectionObserver(
      ([e]) => {
        if (!e.isIntersecting) return;
        io.disconnect();
        set(el, "shown");
      },
      { threshold },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [threshold]);
  return (
    <Tag ref={ref} className={className}>
      {children}
    </Tag>
  );
}

const ease = (t: number) => (t === 1 ? 1 : 1 - Math.pow(2, -10 * t));

/** A figure that counts up once as it enters. The server renders the final value. */
export function CountUp({ value, ms = 1200 }: { value: number; ms?: number }) {
  const ref = useRef<HTMLSpanElement>(null);
  // Two states: resting on the final value (null), or counting (the number on show).
  const [shown, setShown] = useState<number | null>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    if (el.getBoundingClientRect().top < innerHeight) return;
    let raf = 0;
    const io = new IntersectionObserver(([e]) => {
      if (!e.isIntersecting) return;
      io.disconnect();
      const t0 = performance.now();
      const step = (now: number) => {
        const k = Math.min(1, (now - t0) / ms);
        setShown(k < 1 ? Math.round(value * ease(k)) : null);
        if (k < 1) raf = requestAnimationFrame(step);
      };
      raf = requestAnimationFrame(step);
    });
    io.observe(el);
    return () => {
      io.disconnect();
      cancelAnimationFrame(raf);
    };
  }, [value, ms]);
  return <span ref={ref}>{(shown ?? value).toLocaleString("en-GB")}</span>;
}
