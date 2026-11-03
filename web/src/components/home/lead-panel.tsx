"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore } from "react";
import { signed } from "@/lib/format";
import { gapPlaces, whyText } from "@/lib/fleet";

export interface LeadRow {
  n: number;
  name: string | null;
  score: number;
  why: string | null;
  daily: number[] | null;
  c7: number | null;
  c30: number | null;
  a30: number | null;
  dsc: number | null;
  m7: number | null;
  m30: number | null;
  /** Code-activity rank minus 7-day price rank, in places out of 100. Shown unsigned. */
  gap: number | null;
}

const W = 900;
const H = 220;
const BW = W / 90;
const CYCLE_MS = 8000;
const short = (t: number) => new Date(t).toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });
const sum = (a: number[]) => a.reduce((x, y) => x + y, 0);
const tone = (v: number | null) => (v === null || v === 0 ? "" : v < 0 ? "dn" : "up");
const arrow = (v: number | null) => (v === null || v === 0 ? "" : v < 0 ? "▼ " : "▲ ");

/**
 * The head of the fleet board, one tab per subnet. Tabs advance on their own
 * every 8 s while the panel is in view, until the visitor takes a tab, points
 * at the panel or focuses inside it. Pointing at the chart reads one day.
 */
export function LeadPanel({ heads, generatedAt }: { heads: LeadRow[]; generatedAt: string }) {
  const [cur, setCur] = useState(0);
  const [auto, setAuto] = useState(true);
  const [inView, setInView] = useState(false);
  const [paused, setPaused] = useState(false);
  const panel = useRef<HTMLElement>(null);
  const bars = useRef<SVGGElement>(null);
  const cum = useRef<SVGPathElement>(null);
  const readout = useRef<HTMLDivElement>(null);
  const tabs = useRef<(HTMLButtonElement | null)[]>([]);
  const end = Date.parse(generatedAt);
  const dateOf = (d: number) => end - (89 - d) * 864e5;


  useEffect(() => {
    const el = panel.current;
    if (!el) return;
    const io = new IntersectionObserver(([e]) => setInView(e.isIntersecting), { threshold: 0.35 });
    io.observe(el);
    return () => io.disconnect();
  }, []);

  const reduce = useReducedMotion();
  const running = auto && !reduce && inView && !paused;
  useEffect(() => {
    if (!running) return;
    const id = setTimeout(() => setCur((c) => (c + 1) % heads.length), CYCLE_MS);
    return () => clearTimeout(id);
  }, [running, cur, heads.length]);

  // Each switch: the bars rise and the running total draws. Layout effect, so the start state is set before paint.
  useLayoutEffect(() => {
    const g = bars.current, p = cum.current;
    if (!g || !p) return;
    g.setAttribute("data-pre", "");
    p.setAttribute("data-pre", "");
    g.getBoundingClientRect();
    const raf = requestAnimationFrame(() => {
      g.removeAttribute("data-pre");
      p.removeAttribute("data-pre");
    });
    return () => cancelAnimationFrame(raf);
  }, [cur, inView]);

  const take = useCallback((i: number, focus = false) => {
    setAuto(false);
    setCur(i);
    if (focus) tabs.current[i]?.focus();
  }, []);

  const s = heads[cur];
  const d = s.daily ?? [];
  const mx = Math.max(1, ...d);
  const tot = sum(d) || 1;
  const running30 = d.reduce<number[]>((a, c) => [...a, (a[a.length - 1] ?? 0) + c], []);
  const line = running30.map((v, i) => `${i ? "L" : "M"}${(i * BW + BW / 2).toFixed(1)} ${(H - 2 - (v / tot) * (H - 30)).toFixed(1)}`).join("");

  function onMove(e: React.PointerEvent<SVGSVGElement>) {
    const r = e.currentTarget.getBoundingClientRect();
    const day = Math.max(0, Math.min(89, Math.floor(((e.clientX - r.left) / r.width) * 90)));
    const c = d[day] ?? 0;
    const ro = readout.current!;
    ro.textContent = `${short(dateOf(day))}: ${c} ${c === 1 ? "commit" : "commits"}`;
    ro.style.left = `${Math.min(r.width - ro.offsetWidth, Math.max(0, e.clientX - r.left - ro.offsetWidth / 2))}px`;
    ro.classList.add("on");
    bars.current?.querySelectorAll(".hl").forEach((x) => x.classList.remove("hl"));
    bars.current?.querySelector(`[data-d="${day}"]`)?.classList.add("hl");
  }
  function onLeave() {
    readout.current?.classList.remove("on");
    bars.current?.querySelectorAll(".hl").forEach((x) => x.classList.remove("hl"));
  }

  const last = s.dsc === null ? "-" : `${s.dsc} d`;
  const gap = gapPlaces(s.gap);
  const tiles: [string, string, string, string][] = [
    [String(s.c7 ?? "-"), "Commits, 7 days", "to the data day", ""],
    [String(s.c30 ?? "-"), "Commits, 30 days", `of ${sum(d).toLocaleString("en-GB")} in 90 days`, ""],
    [String(s.a30 ?? "-"), "Authors, 30 days", "people pushing code", ""],
    [last, "Last commit", s.dsc === null ? "no commits read" : "before this data", ""],
    [gap === null ? "-" : String(gap), "Code vs price", gap === null ? "no price to rank" : "places apart, of 100", ""],
  ];

  return (
    <article
      ref={panel}
      className="leadp"
      data-ui=""
      aria-label="Head of the fleet board"
      onPointerEnter={() => setPaused(true)}
      onPointerLeave={() => setPaused(false)}
      onFocus={() => setAuto(false)}
    >
      <div className="tabs" role="tablist" aria-label="Head of the fleet board" data-auto={running ? "" : undefined}>
        {heads.map((h, i) => (
          <button
            key={h.n}
            ref={(b) => { tabs.current[i] = b; }}
            type="button"
            role="tab"
            id={`lead-tab-${i}`}
            aria-selected={i === cur}
            aria-controls="lead-panel"
            tabIndex={i === cur ? 0 : -1}
            onClick={() => take(i)}
            onKeyDown={(e) => {
              const k = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
              if (!k) return;
              e.preventDefault();
              take((cur + k + heads.length) % heads.length, true);
            }}
          >
            {h.name} · score {h.score}
            <i key={running ? `run-${cur}` : "still"} />
          </button>
        ))}
      </div>
      <div id="lead-panel" role="tabpanel" aria-labelledby={`lead-tab-${cur}`}>
        <div className="lh">
          <div>
            <h3>
              {s.name}
              <span>SN {s.n}</span>
            </h3>
            <p>
              {whyText(s.why, s.gap)}. Score {s.score} of 100.
            </p>
          </div>
          <div className="k">
            <b className={`fig ${tone(s.m7)}`}>
              {arrow(s.m7)}
              {signed(s.m7, 1, "%")}
            </b>
            <span>alpha price in TAO, 7 days ({signed(s.m30, 1, "%")} over 30)</span>
          </div>
        </div>
        <div className="chart">
          <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label={`Daily commits for ${s.name} over 90 days`} onPointerMove={onMove} onPointerLeave={onLeave}>
            <g ref={bars} className="bars" key={`b-${s.n}`}>
              {d.map((c, i) => {
                if (!c) return null;
                const h = Math.max(3, (c / mx) * (H - 24));
                return (
                  <rect
                    key={i}
                    data-d={i}
                    x={(i * BW + 1).toFixed(1)}
                    y={(H - h).toFixed(1)}
                    width={(BW - 2.4).toFixed(1)}
                    height={h.toFixed(1)}
                    fill={i >= 60 ? "var(--accent)" : "var(--ink-3)"}
                    style={{ transitionDelay: `${i * 6}ms` }}
                  />
                );
              })}
            </g>
            <path ref={cum} key={`c-${s.n}`} className="cum" d={line} pathLength={1} />
          </svg>
          <div ref={readout} className="readout" aria-hidden="true" />
          <div className="ax">
            <span>{short(dateOf(0))}</span>
            <span>{short(dateOf(30))}</span>
            <span>{short(dateOf(60))}</span>
            <span>{short(dateOf(89))}, data day</span>
          </div>
          <div className="legend">
            <span><i style={{ background: "var(--accent)" }} />Commits per day, last 30 days</span>
            <span><i style={{ background: "var(--ink-3)" }} />Earlier</span>
            <span><i style={{ height: 2, width: 14, background: "var(--ink)" }} />Running total, 90 days</span>
          </div>
        </div>
        <div className="tiles">
          {tiles.map(([v, h, t, c]) => (
            <div key={h}>
              <div className={`v fig ${c}`}>{v}</div>
              <div className="h">{h}</div>
              <div className="t">{t}</div>
            </div>
          ))}
        </div>
      </div>
    </article>
  );
}

const RM = "(prefers-reduced-motion: reduce)";
function useReducedMotion() {
  return useSyncExternalStore(
    (cb) => {
      const m = matchMedia(RM);
      m.addEventListener("change", cb);
      return () => m.removeEventListener("change", cb);
    },
    () => matchMedia(RM).matches,
    () => false,
  );
}
