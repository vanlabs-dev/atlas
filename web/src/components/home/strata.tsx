"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { BLOCK_MS, type BlockAnchor } from "@/data/chain";
import { polarity, signed } from "@/lib/format";
import { TIER, WHY } from "@/lib/words";

export interface StrataSlot {
  netuid: number;
  name: string | null;
  tier: "head" | "mid" | "quiet" | null;
  why: string | null;
  divergence: number | null;
  momentum30d: number | null;
  daily: number[] | null;
}

const DAYS = 90;
const SUBNETS = 128;
const sum = (xs: number[]) => xs.reduce((a, b) => a + b, 0);

/** Field geometry; the top inset clears the header on wide screens. */
function frame(w: number, h: number) {
  const top = w >= 768 ? 96 : 20;
  const bottom = 24;
  return { top, rh: (h - top - bottom) / SUBNETS, cw: w / DAYS };
}

function readInks(el: Element) {
  const css = getComputedStyle(el);
  const v = (name: string) => css.getPropertyValue(name).trim();
  return { ink: v("--field-ink"), head: v("--field-head"), on: v("--field-on"), line: v("--field-line") };
}

// The strata: one line per subnet, one column per day, newest on the right.
// The data never moves. Each 12 s block lights a seal line on the newest
// column; with reduced motion the line stays steady.
export function Strata({
  slots,
  initial,
  anchor,
  children,
}: {
  slots: StrataSlot[];
  initial: number;
  anchor: BlockAnchor | null;
  children: ReactNode;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [selected, setSelected] = useState(initial);
  const [hover, setHover] = useState<number | null>(null);
  const flash = useRef(0);
  const shown = slots[(hover ?? selected) - 1];

  const draw = useCallback(() => {
    const cv = canvas.current;
    if (!cv) return;
    const cx = cv.getContext("2d");
    if (!cx) return;
    const W = cv.clientWidth;
    const H = cv.clientHeight;
    const { top, rh, cw } = frame(W, H);
    const ink = readInks(cv);
    cx.clearRect(0, 0, W, H);
    for (let i = 0; i < SUBNETS; i++) {
      const s = slots[i];
      const y = top + i * rh + rh / 2;
      const on = s.netuid === selected || s.netuid === hover;
      cx.fillStyle = `rgba(${ink.line}, ${on ? 0.07 : 0.025})`;
      cx.fillRect(0, y - 0.5, W, 1);
      if (!s.daily) continue;
      for (let d = 0; d < DAYS; d++) {
        const v = s.daily[d];
        if (!v) continue;
        const a = Math.min(1, Math.log1p(v) / 2.2);
        cx.fillStyle = on
          ? `rgba(${ink.on}, ${0.35 + a * 0.65})`
          : s.tier === "head"
            ? `rgba(${ink.head}, ${0.25 + a * 0.7})`
            : `rgba(${ink.ink}, ${0.08 + a * 0.42})`;
        const mh = Math.max(1, rh * 0.64 * a);
        cx.fillRect(d * cw + 1, y - mh / 2, Math.max(1, cw - 2), mh);
      }
    }
    // The newest column, sealed by the last block.
    cx.fillStyle = `rgba(${ink.head}, ${0.5 + flash.current * 0.5})`;
    cx.fillRect(W - cw - 1, top, 1 + flash.current, H - top - 24);
  }, [slots, selected, hover]);

  // Size to the element at device pixels, and redraw on resize or scheme.
  useEffect(() => {
    const cv = canvas.current;
    if (!cv) return;
    const fit = () => {
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      cv.width = cv.clientWidth * dpr;
      cv.height = cv.clientHeight * dpr;
      cv.getContext("2d")?.setTransform(dpr, 0, 0, dpr, 0, 0);
      draw();
    };
    fit();
    const ro = new ResizeObserver(fit);
    ro.observe(cv);
    const scheme = matchMedia("(prefers-color-scheme: dark)");
    scheme.addEventListener("change", draw);
    return () => {
      ro.disconnect();
      scheme.removeEventListener("change", draw);
    };
  }, [draw]);

  // Block tick: the seal line flares and fades over 600 ms.
  useEffect(() => {
    if (!anchor) return;
    const reduce = matchMedia("(prefers-reduced-motion: reduce)");
    const t0 = Date.parse(anchor.at);
    let last = Math.floor((Date.now() - t0) / BLOCK_MS);
    let raf = 0;
    const id = setInterval(() => {
      const now = Math.floor((Date.now() - t0) / BLOCK_MS);
      if (now === last) return;
      last = now;
      if (reduce.matches) return;
      const start = performance.now();
      const step = (t: number) => {
        const p = Math.min(1, (t - start) / 600);
        flash.current = 1 - (1 - (1 - p) ** 3);
        draw();
        if (p < 1) raf = requestAnimationFrame(step);
      };
      raf = requestAnimationFrame(step);
    }, 250);
    return () => {
      clearInterval(id);
      cancelAnimationFrame(raf);
    };
  }, [anchor, draw]);

  const rowAt = (clientY: number) => {
    const cv = canvas.current;
    if (!cv) return null;
    const r = cv.getBoundingClientRect();
    const { top, rh } = frame(r.width, r.height);
    const i = Math.floor((clientY - r.top - top) / rh);
    return i >= 0 && i < SUBNETS ? i + 1 : null;
  };

  const choose = (n: number) => setSelected(Math.min(SUBNETS, Math.max(1, Math.round(n) || 1)));
  const c7 = shown.daily ? sum(shown.daily.slice(-7)) : null;
  const c30 = shown.daily ? sum(shown.daily.slice(-30)) : null;

  return (
    <section aria-labelledby="hero-title" className="relative flex min-h-[min(100svh,940px)] flex-col md:-mt-[72px] md:pt-[72px]">
      <canvas
        ref={canvas}
        aria-label="Commits per day for all 128 subnets over 90 days, one line per subnet, newest day on the right"
        role="img"
        className="absolute inset-0 block size-full cursor-crosshair"
        onMouseMove={(e) => setHover(rowAt(e.clientY))}
        onMouseLeave={() => setHover(null)}
        onClick={(e) => {
          const n = rowAt(e.clientY);
          if (n) setSelected(n);
        }}
      />
      <div className="pointer-events-none relative mx-auto grid w-full max-w-[1320px] flex-1 items-end gap-10 px-4 pb-16 sm:px-8 md:grid-cols-[7fr_1fr_4fr]">
        <div className="pointer-events-auto relative isolate max-w-[640px] pt-12 md:pt-[120px]">
          {/* One scrim behind the copy, for legibility over the field (DESIGN.md). */}
          <div
            aria-hidden="true"
            className="absolute -inset-y-24 -left-16 -right-24 -z-10 md:-left-[240px]"
            style={{ background: "radial-gradient(closest-side, rgba(var(--scrim), .92), rgba(var(--scrim), .75) 60%, transparent)" }} /* taste-skill-ignore: hero scrim allowed by DESIGN.md */
          />
          {children}
        </div>
        <aside
          aria-label="Selected subnet"
          className="pointer-events-auto relative rounded-[10px] bg-s1 p-6 md:col-start-3"
        >
          <div aria-live="polite">
            <h2 className="font-display text-[40px] leading-none">{shown.name ?? `SN${shown.netuid}`}</h2>
            <p className="mt-2 text-[15px] text-ink-2">
              Subnet {shown.netuid}, {shown.tier ? TIER[shown.tier] : "not on the fleet board"}.{" "}
              {shown.why
                ? `${WHY[shown.why] ?? shown.why}.`
                : shown.daily
                  ? "Atlas reads its code. Nothing flags it this month."
                  : "No public repository Atlas can read."}
            </p>
            <dl className="mt-5 grid grid-cols-2 gap-x-4 gap-y-4">
              <div>
                <dt className="text-small text-ink-3">Commits, 7 d</dt>
                <dd className="num mt-0.5 text-[22px]">{c7 ?? "-"}</dd>
              </div>
              <div>
                <dt className="text-small text-ink-3">Commits, 30 d</dt>
                <dd className="num mt-0.5 text-[22px]">{c30 ?? "-"}</dd>
              </div>
              {shown.tier ? (
                <>
                  <div>
                    <dt className="text-small text-ink-3">Code against price</dt>
                    <dd className="num mt-0.5 text-[22px]">{signed(shown.divergence)}</dd>
                  </div>
                  <div>
                    <dt className="text-small text-ink-3">Price, 30 d</dt>
                    <dd className={`num mt-0.5 text-[22px] ${polarity(shown.momentum30d)}`}>
                      {signed(shown.momentum30d, 1, "%")}
                    </dd>
                  </div>
                </>
              ) : null}
            </dl>
          </div>
          <div className="mt-5 flex items-center gap-3 text-small text-ink-3">
            <label htmlFor="subnet-pick">Subnet</label>
            <input
              id="subnet-pick"
              type="number"
              min={1}
              max={SUBNETS}
              value={selected}
              onChange={(e) => choose(Number(e.target.value))}
              className="num h-9 w-20 rounded-[4px] bg-s2 px-2.5 text-[15px] text-ink"
            />
            {shown.tier ? (
              <Link href={`/fleet#sn${shown.netuid}`} className="ml-auto text-ink underline decoration-ink-3 underline-offset-4 transition-colors duration-150 hover:text-accent-2">
                On the fleet board
              </Link>
            ) : null}
          </div>
          <p className="mt-4 text-small text-ink-3">Point at any line in the field, or type a number, to read that subnet.</p>
        </aside>
      </div>
    </section>
  );
}
