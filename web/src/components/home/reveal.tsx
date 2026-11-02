"use client";

import { useEffect, useRef, useState, type ElementType, type ReactNode } from "react";

/**
 * Runs a part's motion once, as it enters the screen. The server markup is
 * the finished state; the client arms the start state (data-armed) only for a
 * part still below the fold, then sets data-go when it arrives. CSS in
 * home.css does the moving, and reduced motion keeps the finished state.
 */
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
    if (el.getBoundingClientRect().top < innerHeight) return;
    el.setAttribute("data-armed", "");
    const io = new IntersectionObserver(
      ([e]) => {
        if (!e.isIntersecting) return;
        io.disconnect();
        el.setAttribute("data-go", "");
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
