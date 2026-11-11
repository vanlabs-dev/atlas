"use client";

import { useCallback, useEffect, useLayoutEffect, useReducer, useRef, useSyncExternalStore } from "react";
import { signed } from "@/lib/format";
import { gapPlaces, whyText } from "@/lib/fleet";
import { CYCLE_MS, CYCLE_START, cyclePhase, cycleStep } from "@/state/lead-cycle";

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
const short = (t: number) => new Date(t).toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });
const sum = (a: number[]) => a.reduce((x, y) => x + y, 0);
const tone = (v: number | null) => (v === null || v === 0 ? "" : v < 0 ? "dn" : "up");
const arrow = (v: number | null) => (v === null || v === 0 ? "" : v < 0 ? "▼ " : "▲ ");

/**
 * The head of the fleet board, one tab per subnet. Tabs advance on their own
 * every 8 s while the panel is in view, until the visitor takes a tab or
 * focuses inside it; a pointer resting on the panel makes the timer wait.
 * The rules are the reducer in src/state/lead-cycle.ts, and the phase it
 * gives is on the panel as data-cycle (cycling, held, offscreen, taken,
 * still). Pointing at the chart, or dragging a thumb across it, reads one day.
 */
export function LeadPanel({ heads, generatedAt }: { heads: LeadRow[]; generatedAt: string }) {
  const [cycle, send] = useReducer(cycleStep, CYCLE_START);
  const cur = cycle.tab;
  const panel = useRef<HTMLElement>(null);
  const chart = useRef<HTMLDivElement>(null);
  const bars = useRef<SVGGElement>(null);
  const readout = useRef<HTMLDivElement>(null);
  const tabs = useRef<(HTMLButtonElement | null)[]>([]);
  const end = Date.parse(generatedAt);
  const dateOf = (d: number) => end - (89 - d) * 864e5;


  useEffect(() => {
    const el = panel.current;
    if (!el) return;
    const io = new IntersectionObserver(([e]) => send({ type: e.isIntersecting ? "enter" : "leave" }), { threshold: 0.35 });
    io.observe(el);
    return () => io.disconnect();
  }, []);

  const phase = cyclePhase(cycle, useReducedMotion());
  useEffect(() => {
    if (phase !== "cycling") return;
    const id = setTimeout(() => send({ type: "tick", tabs: heads.length }), CYCLE_MS);
    return () => clearTimeout(id);
  }, [phase, cur, heads.length]);

  // Each switch, and each return to the screen: the bars rise and the running total draws. The chart is
  // put in its start state (data-draw="pre") before paint and released on the next frame.
  useLayoutEffect(() => {
    const c = chart.current;
    if (!c) return;
    c.setAttribute("data-draw", "pre");
    c.getBoundingClientRect();
    const raf = requestAnimationFrame(() => c.removeAttribute("data-draw"));
    return () => {
      cancelAnimationFrame(raf);
      c.removeAttribute("data-draw");
    };
  }, [cur, cycle.inView]);

  const take = useCallback((i: number, focus = false) => {
    send({ type: "take", tab: i });
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
      data-cycle={phase}
      onPointerEnter={() => send({ type: "hold" })}
      onPointerLeave={() => send({ type: "release" })}
      onFocus={() => send({ type: "focus" })}
    >
      <div className="tabs" role="tablist" aria-label="Head of the fleet board">
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
            {h.name}
            <span className="sc"> · score {h.score}</span>
            <i key={phase === "cycling" ? `run-${cur}` : "rest"} />
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
        <div className="chart" ref={chart}>
          <svg
            viewBox={`0 0 ${W} ${H}`}
            preserveAspectRatio="none"
            role="img"
            aria-label={`Daily commits for ${s.name} over 90 days`}
            onPointerDown={onMove}
            onPointerMove={onMove}
            onPointerLeave={onLeave}
            onPointerCancel={onLeave}
          >
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
            <path key={`c-${s.n}`} className="cum" d={line} pathLength={1} />
          </svg>
          {sum(d) === 0 ? <p className="none">No commits in the 90 days to {short(end)}.</p> : null}
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
