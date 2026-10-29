"use client";

import { MotionConfig } from "motion/react";
import { usePathname } from "next/navigation";
import { useEffect, type ReactNode } from "react";

// reducedMotion="user" drops transform travel when the visitor asks for less
// motion. Entrances are CSS (globals.css, [data-reveal]): content is visible
// without script, and only hidden once the `js` class is on <html>.
export function Motion({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  useEffect(() => {
    const items = document.querySelectorAll<HTMLElement>("[data-reveal]:not(.in)");
    const io = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          entry.target.classList.add("in");
          io.unobserve(entry.target);
        }
      },
      { rootMargin: "0px 0px -8% 0px" },
    );
    items.forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, [pathname]);
  return <MotionConfig reducedMotion="user">{children}</MotionConfig>;
}

/** One part of a section that rises into place; `step` staggers by 75ms. */
export function Reveal({
  children,
  step = 0,
  className,
}: {
  children: ReactNode;
  step?: number;
  className?: string;
}) {
  return (
    <div data-reveal="" className={className} style={{ transitionDelay: `${step * 75}ms` }}>
      {children}
    </div>
  );
}
