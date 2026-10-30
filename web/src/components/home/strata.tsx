"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { BLOCK_MS, type BlockAnchor } from "@/data/chain";
import { TIER, WHY } from "@/lib/words";

export interface StrataSlot {
  netuid: number;
  name: string | null;
  tier: "head" | "mid" | "quiet" | null;
  why: string | null;
  momentum30d: number | null;
  daily: number[] | null;
}

const DAYS = 90;
const N = 128;
const DAY_MS = 86_400_000;

const sum = (xs: number[]) => xs.reduce((a, b) => a + b, 0);
const fmt = (v: number | null, digits = 0) =>
  v === null ? "-" : v.toLocaleString("en-GB", { maximumFractionDigits: digits });
const signed = (v: number | null, digits = 0, unit = "") =>
  v === null ? "-" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${fmt(Math.abs(v), digits)}${unit}`;
// Subnet names are set on chain by their owners: escape before markup.
const esc = (t: string) =>
  t.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c] as string);
const amp = (v: number) => Math.min(1, Math.log1p(v) / 2.6);

interface Row {
  n: number;
  name: string;
  tier: StrataSlot["tier"];
  why: string | null;
  momentum: number | null;
  d: number[] | null;
  c7: number | null;
  c30: number | null;
}

/** The sentence and figures of the annotation, as markup for one row. */
function noteHtml(x: Row, idle: boolean): string {
  const tier = x.tier ? TIER[x.tier] : null;
  const line = tier
    ? `${esc(WHY[x.why ?? ""] ?? x.why ?? "")}. ${tier[0].toUpperCase()}${tier.slice(1)}.`
    : x.d
      ? "Atlas reads its code. Not on the fleet board."
      : "No public repository Atlas can read.";
  const tone = x.momentum ? (x.momentum < 0 ? "text-down" : "text-accent-2") : "";
  const price = x.tier ? `<div><dt>Price, 30 d</dt><dd class="${tone}">${signed(x.momentum, 1, "%")}</dd></div>` : "";
  return `<p class="nm">${esc(x.name)}</p><p class="ln"><span class="sn">Subnet ${x.n}.</span> ${line}</p>
    <dl><div><dt>Commits, 7 d</dt><dd>${fmt(x.c7)}</dd></div><div><dt>Commits, 30 d</dt><dd>${fmt(x.c30)}</dd></div>${price}</dl>
    ${idle ? `<p class="hint">Point at any line to read that subnet. Click to pin it, or use the arrow keys.</p>` : ""}`;
}

/** Rows in sediment order: no code, then silent, then by 30-day commits. */
function sediment(slots: StrataSlot[]): Row[] {
  return slots
    .map((s) => ({
      n: s.netuid,
      name: s.name ?? `SN${s.netuid}`,
      tier: s.tier,
      why: s.why,
      momentum: s.momentum30d,
      d: s.daily,
      c7: s.daily ? sum(s.daily.slice(-7)) : null,
      c30: s.daily ? sum(s.daily.slice(-30)) : null,
    }))
    .sort(
      (a, b) =>
        (a.d ? 1 : 0) - (b.d ? 1 : 0) ||
        (a.c30 ?? 0) - (b.c30 ?? 0) ||
        (a.d && b.d ? sum(a.d) - sum(b.d) : 0),
    );
}

// The strata as an instrument: one line per subnet, one column per day,
// sorted like sediment (quiet on top, busiest at the floor), with a time
// axis, a today edge, named rows in the margin, and an annotation that
// follows the pointer or, when idle, a slow ghost tour. See DESIGN.md.
export function Strata({
  slots,
  lead,
  anchor,
  dataAt,
  children,
}: {
  slots: StrataSlot[];
  lead: number;
  anchor: BlockAnchor | null;
  dataAt: string;
  children: ReactNode;
}) {
  const heroRef = useRef<HTMLElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const noteRef = useRef<HTMLDivElement>(null);
  const tagRef = useRef<HTMLDivElement>(null);
  const leadRef = useRef<HTMLSpanElement>(null);
  const dotRef = useRef<HTMLSpanElement>(null);
  const curRef = useRef<HTMLDivElement>(null);
  const furRef = useRef<HTMLDivElement>(null);

  const first = sediment(slots);
  const leadRow = first.find((r) => r.n === lead) ?? first[N - 1];

  useEffect(() => {
    const rows = sediment(slots);
    const hero = heroRef.current!;
    const cv = canvasRef.current!;
    const cx = cv.getContext("2d")!;
    const nt = noteRef.current!;
    const tag = tagRef.current!;
    const leadLine = leadRef.current!;
    const dot = dotRef.current!;
    const cur = curRef.current!;
    const fur = furRef.current!;
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    const nNull = rows.filter((x) => !x.d).length;
    const nZero = rows.filter((x) => x.d && x.c30 === 0).length;
    const busiest = new Set(rows.map((_, i) => i).slice(-5));

    function geom() {
      const W = cv.clientWidth, H = cv.clientHeight, mobile = W < 1024;
      const left = 0, right = W - (mobile ? 16 : Math.max(168, W * 0.1));
      const top = mobile ? 8 : 88, bottom = H - (mobile ? 28 : 56);
      return { W, H, mobile, left, right, top, bottom, rh: (bottom - top) / N, cw: (right - left) / DAYS };
    }

    let G = geom();
    let sel = Math.max(0, rows.findIndex((r) => r.n === lead));
    let hover = -1;
    let px: number | null = null;
    let reveal = reduce ? 1 : 0;
    let flash = 0;
    let knock: { x: number; y: number; w: number; h: number } | null = null;
    let blkText = "";
    let lastInput = performance.now();
    let touring = false;
    let vx = 0, vy = 0, gx = 0, gy = 0, nextPick = 0;
    let settled = -1;
    let settledX: number | null = null;
    let noteFor = "";
    const frames: number[] = [];
    const raf = (fn: FrameRequestCallback) => frames.push(requestAnimationFrame(fn));

    const ink = () => {
      const css = getComputedStyle(cv);
      const v = (k: string) => css.getPropertyValue(k).trim();
      return { ink: v("--field-ink"), head: v("--field-head"), on: v("--field-on"), line: v("--field-line") };
    };

    // Margin labels: the quiet bands, the head of the fleet board, the five
    // busiest and the row in hand, spaced 15px apart, pushed up off the floor.
    function layout() {
      const g = G;
      const want: { i: number; y: number; txt?: string; head?: boolean; name?: string }[] = [
        { i: Math.floor(nNull / 2), y: 0, txt: `${nNull} with no code` },
        { i: nNull + Math.floor(nZero / 2), y: 0, txt: `${nZero} silent, 30 days` },
      ];
      rows.forEach((x, i) => {
        const head = x.tier === "head";
        if (head || busiest.has(i) || i === hover || i === sel)
          want.push({ i, y: 0, head, name: x.name.length > 14 ? `${x.name.slice(0, 13)}…` : x.name });
      });
      want.sort((a, b) => a.i - b.i);
      let prev = -1e9;
      for (const w of want) {
        w.y = Math.max(g.top + w.i * g.rh + g.rh / 2 - 7, prev + 15);
        prev = w.y;
      }
      let floor = g.bottom - 7;
      for (let k = want.length - 1; k >= 0; k--) {
        if (want[k].y > floor) want[k].y = floor;
        floor = want[k].y - 15;
      }
      return want;
    }

    function draw() {
      const g = (G = geom());
      const { W, H, left, right, top, rh, cw } = g;
      const c = ink();
      cx.clearRect(0, 0, W, H);
      cx.save();
      cx.beginPath();
      cx.rect(0, 0, left + (right - left) * reveal, H);
      cx.clip();
      for (let i = 0; i < N; i++) {
        const x = rows[i], y = top + i * rh + rh / 2, on = i === sel || i === hover;
        if (!x.d) {
          cx.fillStyle = `rgba(${c.line}, .07)`;
          for (let p = left; p < right; p += 6) cx.fillRect(p, y, 1.5, 1);
          continue;
        }
        if (on) {
          cx.fillStyle = `rgba(${c.on}, ${i === hover ? 0.11 : 0.06})`;
          cx.fillRect(left, y - rh / 2, right - left, rh);
        }
        cx.fillStyle = on ? `rgba(${c.on}, .35)` : `rgba(${c.line}, .035)`;
        cx.fillRect(left, y - 0.5, right - left, 1);
        for (let d = 0; d < DAYS; d++) {
          const v = x.d[d];
          if (!v) continue;
          const a = amp(v);
          cx.fillStyle = on
            ? `rgba(${c.on}, ${0.4 + a * 0.6})`
            : x.tier === "head"
              ? `rgba(${c.head}, ${0.35 + a * 0.65})`
              : `rgba(${c.ink}, ${0.14 + a * 0.5})`;
          const mh = Math.max(1, rh * 0.78 * a);
          cx.fillRect(left + d * cw + 1, y - mh / 2, Math.max(1, cw - 2), mh);
        }
      }
      cx.restore();
      // the field is cleared behind the annotation so it reads cleanly
      if (knock && !g.mobile) cx.clearRect(knock.x - 20, knock.y - 16, knock.w + 40, knock.h + 32);
      if (reveal >= 1) {
        cx.fillStyle = `rgba(${c.on}, ${0.55 + flash * 0.45})`;
        cx.fillRect(right, top - 24, 1 + flash * 1.5, g.bottom - top + 24);
        if (!g.mobile)
          for (const l of layout()) {
            const ry = top + l.i * rh + rh / 2;
            cx.strokeStyle = l.i === hover || l.i === sel ? `rgba(${c.on}, .7)` : `rgba(${c.line}, .16)`;
            cx.lineWidth = 1;
            cx.beginPath();
            cx.moveTo(right + 2, ry);
            cx.lineTo(right + 8, ry);
            cx.lineTo(right + 14, l.y + 7);
            cx.lineTo(right + 18, l.y + 7);
            cx.stroke();
          }
      }
      cx.fillStyle = `rgba(${c.line}, .12)`;
      cx.fillRect(left, g.bottom + 10, right - left, 1);
      for (const d of [0, 30, 60]) cx.fillRect(left + d * cw, g.bottom + 6, 1, 9);
      place();
    }

    const day = (i: number) =>
      new Date(Date.parse(dataAt) - (DAYS - 1 - i) * DAY_MS).toLocaleDateString("en-GB", {
        day: "numeric",
        month: "short",
        timeZone: "UTC",
      });

    // Axis dates, the today edge with the block clock, and the margin labels.
    function place() {
      const g = G;
      if (g.mobile) {
        fur.innerHTML = "";
        note();
        return;
      }
      fur.innerHTML = [
        ...([[0, "90 days ago"], [30, "60 days ago"], [60, "30 days ago"]] as const).map(
          ([d, l]) => `<span class="ax" style="left:${Math.max(g.left + d * g.cw + 6, 24)}px;top:${g.bottom + 18}px">${day(d)} <span class="ago">${l}</span></span>`,
        ),
        `<span class="ax today" style="left:${g.right - 80}px;top:${g.bottom + 18}px;width:80px;text-align:right">${day(DAYS - 1)}</span>`,
        anchor
          ? `<span class="ax today" style="left:${g.right + 12}px;top:${g.top - 30}px">today</span>
             <span class="ax" style="left:${g.right + 12}px;top:${g.top - 10}px">est. block <b data-blk>${blkText}</b></span>
             <span class="ax" style="left:${g.right + 12}px;top:${g.top + 10}px"><i class="bar" data-bar></i></span>`
          : "",
        ...layout().map((l) =>
          l.txt
            ? `<span class="band" style="left:${g.right + 20}px;top:${l.y}px">${l.txt}</span>`
            : `<span class="lbl${l.head ? " head" : ""}${l.i === hover || l.i === sel ? " on" : ""}" style="left:${g.right + 20}px;top:${l.y}px"><span>${rows[l.i].n}</span>${esc(l.name ?? "")}</span>`,
        ),
      ].join("");
      note();
    }

    // The annotation: on tour it holds the last subnet the ghost settled on.
    function note() {
      const g = G;
      const i = touring && settled >= 0 ? settled : hover >= 0 ? hover : sel;
      const x = rows[i];
      const idle = hover < 0 && !touring;
      const key = `${x.n}:${idle}`;
      if (key !== noteFor) {
        tag.innerHTML = noteHtml(x, idle);
        noteFor = key;
      }
      if (g.mobile) {
        tag.style.cssText = "";
        leadLine.style.cssText = "display:none";
        dot.style.cssText = "display:none";
        nt.style.opacity = "1";
        return;
      }
      const y = g.top + i * g.rh + g.rh / 2;
      const ax = touring && settled >= 0 ? settledX : px;
      const at = ax === null ? g.right - g.cw * 2.5 : Math.min(g.right, Math.max(g.left + 40, ax));
      const tw = tag.offsetWidth, th = tag.offsetHeight;
      const tx = Math.round(Math.min(g.right - tw - 24, Math.max(g.W * 0.62, at - tw - 24)) / 4) * 4;
      const ty = g.top + Math.round((g.bottom - g.top) * 0.24);
      const lx = tx + tw + 12, ly = ty + 18;
      dot.style.cssText = `left:${at}px;top:${y}px`;
      leadLine.style.cssText =
        at >= lx
          ? `left:${lx}px;top:${ly}px;width:${at - lx}px;height:${y - ly}px;border-width:1px 1px 0 0`
          : `left:${at}px;top:${ly}px;width:${lx - at}px;height:${y - ly}px;border-width:1px 0 0 1px`;
      tag.style.cssText = `position:absolute;left:${tx}px;top:${ty}px`;
      nt.style.opacity = reveal >= 1 ? "1" : "0";
      if (!knock || knock.x !== tx || knock.y !== ty || knock.w !== tw || knock.h !== th) {
        knock = { x: tx, y: ty, w: tw, h: th };
        draw();
      }
    }

    function curTagAt(x0: number, y0: number) {
      if (hover < 0 || G.mobile) {
        cur.style.opacity = "0";
        return;
      }
      const x = rows[hover];
      cur.innerHTML = `<b>${esc(x.name)}</b> <span>${x.n}</span><br><span>${x.d ? `${fmt(x.c30)} commits in 30 days` : "no code Atlas can read"}</span>`;
      cur.style.left = `${Math.min(x0 + 16, G.right - cur.offsetWidth - 8)}px`;
      cur.style.top = `${y0 + 16}px`;
      cur.style.opacity = "1";
    }

    function rowAt(e: MouseEvent) {
      const r = cv.getBoundingClientRect(), g = G;
      const i = Math.floor((e.clientY - r.top - g.top) / g.rh);
      return i >= 0 && i < N && e.clientX - r.left <= g.right ? i : -1;
    }
    const onMove = (e: MouseEvent) => {
      lastInput = performance.now();
      touring = false;
      const i = rowAt(e);
      px = i >= 0 ? e.clientX - cv.getBoundingClientRect().left : null;
      if (i !== hover) {
        hover = i;
        draw();
      } else note();
      const b = hero.getBoundingClientRect();
      curTagAt(e.clientX - b.left, e.clientY - b.top);
    };
    const onLeave = () => {
      lastInput = performance.now();
      hover = -1;
      px = null;
      draw();
      cur.style.opacity = "0";
    };
    const onClick = (e: MouseEvent) => {
      const i = rowAt(e);
      if (i >= 0) {
        sel = i;
        draw();
      }
    };
    const onKey = (e: KeyboardEvent) => {
      const step = ({ ArrowUp: -1, ArrowDown: 1 } as Record<string, number>)[e.key];
      if (!step) return;
      e.preventDefault();
      sel = Math.max(0, Math.min(N - 1, sel + step));
      hover = -1;
      px = null;
      draw();
    };
    const onAnyKey = () => {
      lastInput = performance.now();
      touring = false;
    };
    cv.addEventListener("mousemove", onMove);
    cv.addEventListener("mouseleave", onLeave);
    cv.addEventListener("click", onClick);
    cv.addEventListener("keydown", onKey);
    addEventListener("keydown", onAnyKey);

    const fit = () => {
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      cv.width = cv.clientWidth * dpr;
      cv.height = cv.clientHeight * dpr;
      cx.setTransform(dpr, 0, 0, dpr, 0, 0);
      knock = null;
      draw();
    };
    const ro = new ResizeObserver(fit);
    ro.observe(cv);
    const scheme = matchMedia("(prefers-color-scheme: dark)");
    scheme.addEventListener("change", draw);

    // Load: the 90 days replay left to right once.
    if (!reduce) {
      const t0 = performance.now();
      const go = (t: number) => {
        reveal = 1 - (1 - Math.min(1, (t - t0) / 1400)) ** 3;
        draw();
        if (reveal < 1) raf(go);
      };
      raf(go);
    }

    // Block clock: text every 250 ms; the today edge flares on each block.
    let last = -1;
    const clock = setInterval(() => {
      if (!anchor) return;
      const el = (Date.now() - Date.parse(anchor.at)) / BLOCK_MS;
      const n = Math.floor(el);
      blkText = (anchor.block + n).toLocaleString("en-GB");
      const b = fur.querySelector<HTMLElement>("[data-blk]");
      if (b) b.textContent = blkText;
      const bar = fur.querySelector<HTMLElement>("[data-bar]");
      if (bar) bar.style.setProperty("--p", reduce ? "0" : (el % 1).toFixed(3));
      if (n !== last && last !== -1 && !reduce) {
        const s0 = performance.now();
        const fl = (t: number) => {
          const p = Math.min(1, (t - s0) / 600);
          flash = (1 - p) ** 2;
          draw();
          if (p < 1) raf(fl);
        };
        raf(fl);
      }
      last = n;
    }, 250);

    // Idle tour: after 5 s with no input, a ghost pointer glides between
    // random subnets with code. Off with reduced motion, on phones, out of view.
    function pick() {
      const g = G, i = nNull + Math.floor(Math.random() * (N - nNull));
      gx = g.left + (g.right - g.left) * (0.5 + Math.random() * 0.47);
      gy = g.top + i * g.rh + g.rh / 2;
      nextPick = performance.now() + 6000 + Math.random() * 3000;
    }
    function tour(t: number) {
      raf(tour);
      const g = G;
      if (g.mobile || document.hidden || reveal < 1 || hero.getBoundingClientRect().bottom < 0) return;
      if (t - lastInput < 5000) {
        touring = false;
        return;
      }
      if (!touring) {
        touring = true;
        vx = px ?? g.right - g.cw * 2.5;
        settled = hover >= 0 ? hover : sel;
        settledX = vx;
        vy = g.top + settled * g.rh + g.rh / 2;
        pick();
      }
      if (t > nextPick) pick();
      vx += (gx - vx) * 0.011;
      vy += (gy - vy) * 0.011;
      const i = Math.max(0, Math.min(N - 1, Math.floor((vy - g.top) / g.rh)));
      px = vx;
      if (Math.hypot(gx - vx, gy - vy) < 3 && settled !== i) {
        settled = i;
        settledX = vx;
        draw();
      }
      if (i !== hover) {
        hover = i;
        draw();
      } else note();
      curTagAt(vx, vy);
    }
    if (!reduce) raf(tour);

    return () => {
      frames.forEach(cancelAnimationFrame);
      clearInterval(clock);
      ro.disconnect();
      scheme.removeEventListener("change", draw);
      cv.removeEventListener("mousemove", onMove);
      cv.removeEventListener("mouseleave", onLeave);
      cv.removeEventListener("click", onClick);
      cv.removeEventListener("keydown", onKey);
      removeEventListener("keydown", onAnyKey);
    };
  }, [slots, lead, anchor, dataAt]);

  return (
    <section
      ref={heroRef}
      aria-labelledby="hero-title"
      className="strata relative flex flex-col overflow-x-clip lg:-mt-[72px] lg:block lg:h-[min(100svh,980px)] lg:min-h-[760px]"
    >
      <canvas
        ref={canvasRef}
        tabIndex={0}
        role="img"
        aria-label="Commits per day for all 128 subnets over 90 days. One line per subnet, quietest at the top, busiest at the bottom, today on the right."
        className="order-2 block h-[440px] w-full cursor-crosshair md:h-[560px] lg:absolute lg:inset-0 lg:h-full"
      />
      <div className="wrap pointer-events-none relative z-[2] order-1 pb-8 pt-11 lg:pb-0 lg:pt-[148px]">
        <div className="copy pointer-events-auto relative max-w-[880px]">{children}</div>
      </div>
      <div ref={noteRef} className="note relative order-3 z-[3] mx-4 mt-3 sm:mx-[clamp(16px,4vw,64px)] lg:absolute lg:inset-0 lg:m-0" aria-live="polite">
        <span ref={leadRef} className="lead" aria-hidden="true" />
        <span ref={dotRef} className="dot" aria-hidden="true" />
        <div ref={tagRef} className="tag" dangerouslySetInnerHTML={{ __html: noteHtml(leadRow, true) }} />
      </div>
      <div ref={furRef} className="pointer-events-none absolute inset-0 z-[2] hidden lg:block" aria-hidden="true" />
      <div ref={curRef} className="cur" aria-hidden="true" />
    </section>
  );
}
