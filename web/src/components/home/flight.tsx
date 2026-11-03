"use client";

import { useEffect, useRef, type ReactNode } from "react";
import type { BlockAnchor } from "@/data/chain";
import { useBlocks } from "@/components/block-clock";

export interface FlightRow {
  n: number;
  name: string | null;
  head: boolean;
  c30: number | null;
  daily: number[] | null;
}

const ND = 90;
const short = (t: number) => new Date(t).toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });

// Camera stops along the flight. Progress 0 is the hero, 1 faces the busiest rows.
const STOPS = [
  { pos: [24, 86, 134], look: [10, -8, 10], fov: 37 }, // the whole field from high above
  { pos: [-58, 36, -108], look: [10, -6, -14], fov: 42 }, // the quiet back, where the dotted rows lie
  { pos: [26, 12, 82], look: [52, 1, 22], fov: 42 }, // along the time axis to today
  { pos: [48, 17, 92], look: [30, 0.4, 38], fov: 38 }, // turned to face the busiest rows
] as const;
const PHONE = { pos: [4, 92, 116], look: [2, -10, 8], fov: 44 } as const;
const FIELD_LABEL =
  "90 days of commits for all 128 subnets, one row per subnet, one column per day, newest on the right. Quiet subnets sit at the back, the busiest at the front.";

/**
 * The home hero: 128 subnets x 90 days of commits as a 3D field. On wide
 * screens the scroll flies the camera through it; on phones it sways; under
 * reduced motion it is still; without WebGL it is drawn flat. Rows arrive in
 * sediment order: no code at the back, then silent, then by 30-day commits.
 */
export function Flight({
  rows,
  leadN,
  generatedAt,
  anchor,
  children,
  stops,
}: {
  rows: FlightRow[];
  leadN: number;
  generatedAt: string;
  anchor: BlockAnchor | null;
  children: ReactNode;
  stops: ReactNode;
}) {
  const root = useRef<HTMLElement>(null);
  const elapsed = useBlocks(anchor);
  const block = anchor && elapsed !== null ? (anchor.block + Math.floor(elapsed)).toLocaleString("en-GB") : "-";

  useEffect(() => {
    const el = root.current;
    if (!el) return;
    const fig = el.querySelector<HTMLDivElement>(".figure")!;
    // A fresh canvas per mount: Next keeps this page alive in an Activity, so the
    // effect re-runs on the same DOM, and a canvas whose context was released cannot be reused.
    const canvas = document.createElement("canvas");
    canvas.className = "field";
    canvas.setAttribute("role", "img");
    canvas.setAttribute("aria-label", FIELD_LABEL);
    fig.prepend(canvas);
    const labels = el.querySelector<HTMLDivElement>(".labels")!;
    const todayEl = el.querySelector<HTMLDivElement>(".today")!;
    const tagEl = el.querySelector<HTMLDivElement>(".tagp")!;
    const heroCopy = el.querySelector<HTMLDivElement>(".hero-copy")!;
    const stopEls = [...el.querySelectorAll<HTMLElement>(".stop")];

    const wide = matchMedia("(min-width: 900px)");
    const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
    const nogl = document.documentElement.classList.contains("nogl");
    const OVER = wide.matches && !nogl;
    const FLY = OVER && !still;

    const NR = rows.length;
    const rowZ = (i: number) => i - (NR - 1) / 2;
    const dayX = (d: number) => d - (ND - 1) / 2;
    let maxC = 1;
    rows.forEach((r) => r.daily?.forEach((c) => { if (c > maxC) maxC = c; }));
    const level = (c: number) => Math.log1p(c) / Math.log1p(maxC);
    const end = Date.parse(generatedAt);
    const dayAt = (d: number) => end - (ND - 1 - d) * 864e5;
    const css = () => {
      const s = getComputedStyle(document.documentElement);
      const v = (k: string) => s.getPropertyValue(k).trim();
      return {
        ground: v("--field-ground"), lo: v("--field-lo"), hi: v("--field-hi"), headLo: v("--field-head-lo"),
        headHi: v("--field-head-hi"), base: v("--field-base"), dot: v("--field-dot"), lit: v("--field-lit"), accent: v("--accent"),
      };
    };

    const cleanups: (() => void)[] = [() => canvas.remove()];
    const on = <K extends keyof WindowEventMap>(t: Window, k: K, f: (e: WindowEventMap[K]) => void, o?: AddEventListenerOptions) => {
      t.addEventListener(k, f, o);
      cleanups.push(() => t.removeEventListener(k, f, o));
    };
    let disposed = false;

    if (nogl) {
      // No WebGL: the same field drawn flat, newest on the right, busiest at the bottom.
      const dpr = Math.min(devicePixelRatio || 1, 2);
      const draw = () => {
        const c = css();
        const w = fig.clientWidth, h = fig.clientHeight;
        canvas.width = w * dpr; canvas.height = h * dpr;
        const ctx = canvas.getContext("2d")!;
        ctx.scale(dpr, dpr);
        const cw = w / ND, rh = (h - 40) / NR;
        rows.forEach((r, i) => {
          const y = 8 + i * rh;
          for (let d = 0; d < ND; d++) {
            if (!r.daily) { if (d % 3 === 0) { ctx.fillStyle = c.dot; ctx.fillRect(d * cw, y + rh - 1, 1.5, 1); } continue; }
            const v = r.daily[d]; if (!v) continue;
            const t = Math.max(0.25, level(v));
            ctx.globalAlpha = 0.3 + 0.7 * t;
            ctx.fillStyle = r.head ? c.headHi : c.hi;
            ctx.fillRect(d * cw + 1, y + rh * (1 - t), cw * 0.7, Math.max(1, rh * t));
          }
        });
        ctx.globalAlpha = 1;
        todayEl.style.transform = `translate(${w - 160}px, ${h - 40}px)`;
      };
      draw();
      on(window, "resize", draw);
      return () => cleanups.forEach((f) => f());
    }

    let teardown = () => {};
    import("three").then((THREE) => {
      if (disposed) return;
      let dirty = true, visible = true, progress = 0, hover = -1, raf = 0;
      const t0 = performance.now();
      const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: "high-performance" });
      renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
      const scene = new THREE.Scene();
      const camera = new THREE.PerspectiveCamera(38, 1, 0.5, 600);
      scene.add(new THREE.AmbientLight(0xffffff, 1.35));
      const sun = new THREE.DirectionalLight(0xffffff, 1.6);
      sun.position.set(-0.5, 1, 0.35);
      scene.add(sun);

      // One flat box per subnet per day with commits. Height and tone follow log1p(commits).
      type Mark = { i: number; d: number; t: number; h: number; color: InstanceType<typeof THREE.Color> };
      const marks: Mark[] = [];
      rows.forEach((r, i) => r.daily?.forEach((c, d) => { if (c > 0) marks.push({ i, d, t: level(c), h: 0.35 + level(c) * 5.5, color: new THREE.Color() }); }));
      const geo = new THREE.BoxGeometry(1, 1, 1);
      geo.translate(0, 0.5, 0);
      const mat = new THREE.MeshLambertMaterial();
      const mesh = new THREE.InstancedMesh(geo, mat, marks.length);
      const byRow: number[][] = Array.from({ length: NR }, () => []);
      marks.forEach((k, idx) => byRow[k.i].push(idx));
      scene.add(mesh);

      // Baselines: a line under every row with code, a dotted line for rows with none, and the today edge.
      const base: { x: number; z: number; w: number; d: number; k: "base" | "dot" | "accent" }[] = [];
      rows.forEach((r, i) => {
        if (r.daily) base.push({ x: 0, z: rowZ(i), w: ND, d: 0.08, k: "base" });
        else for (let d = 0; d < ND; d += 3) base.push({ x: dayX(d), z: rowZ(i), w: 0.3, d: 0.3, k: "dot" });
      });
      base.push({ x: dayX(ND - 1) + 0.9, z: 0, w: 0.12, d: NR + 2, k: "accent" });
      const bgeo = new THREE.BoxGeometry(1, 1, 1);
      const bmat = new THREE.MeshBasicMaterial();
      const bmesh = new THREE.InstancedMesh(bgeo, bmat, base.length);
      scene.add(bmesh);

      const m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), v = new THREE.Vector3(), sc = new THREE.Vector3();
      let lit = new THREE.Color();
      function paint() {
        const c = css();
        renderer.setClearColor(c.ground, 1);
        const lo = new THREE.Color(c.lo), hi = new THREE.Color(c.hi), hlo = new THREE.Color(c.headLo), hhi = new THREE.Color(c.headHi);
        lit = new THREE.Color(c.lit);
        marks.forEach((k, idx) => {
          k.color.copy(rows[k.i].head ? hlo : lo).lerp(rows[k.i].head ? hhi : hi, k.t);
          mesh.setColorAt(idx, k.i === hover ? lit : k.color);
        });
        if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
        const tone = { base: new THREE.Color(c.base), dot: new THREE.Color(c.dot), accent: new THREE.Color(c.accent) };
        base.forEach((b, k) => {
          m4.compose(v.set(b.x, 0.02, b.z), q.identity(), sc.set(b.w, 0.04, b.d));
          bmesh.setMatrixAt(k, m4);
          bmesh.setColorAt(k, tone[b.k]);
        });
        bmesh.instanceMatrix.needsUpdate = true;
        if (bmesh.instanceColor) bmesh.instanceColor.needsUpdate = true;
        dirty = true;
      }
      paint();
      const scheme = matchMedia("(prefers-color-scheme: dark)");
      scheme.addEventListener("change", paint);
      cleanups.push(() => scheme.removeEventListener("change", paint));

      function place(grow?: (d: number) => number) {
        marks.forEach((k, idx) => {
          const g = grow ? grow(k.d) : 1;
          m4.compose(v.set(dayX(k.d), k.i === hover ? 0.6 : 0, rowZ(k.i)), q.identity(), sc.set(0.62, Math.max(0.001, k.h * g), 0.44));
          mesh.setMatrixAt(idx, m4);
        });
        mesh.instanceMatrix.needsUpdate = true;
      }
      function paintRow(i: number, onRow: boolean) {
        if (i < 0) return;
        byRow[i].forEach((idx) => mesh.setColorAt(idx, onRow ? lit : marks[idx].color));
        if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
      }

      const ease = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
      const lerp = (a: number, b: number, t: number) => a + (b - a) * t;
      function frame(p: number, now: number) {
        const k = (now - t0) / 1000;
        if (!FLY) {
          const s = OVER ? STOPS[0] : PHONE;
          camera.position.set(s.pos[0], s.pos[1], s.pos[2]);
          v.set(s.look[0], s.look[1], s.look[2]);
          camera.fov = s.fov;
          if (!OVER && !still) {
            // Phones have no flight, so the camera sways slowly across the field instead.
            camera.position.x += Math.sin(k * 0.22) * 26;
            camera.position.y += Math.sin(k * 0.15) * 8;
            v.x += Math.sin(k * 0.22) * 8;
          }
        } else {
          const seg = Math.min(STOPS.length - 2, Math.floor(p * (STOPS.length - 1)));
          const e = ease(Math.min(1, Math.max(0, (p * (STOPS.length - 1) - seg - 0.16) / 0.68)));
          const a = STOPS[seg], b = STOPS[seg + 1];
          camera.position.set(lerp(a.pos[0], b.pos[0], e), lerp(a.pos[1], b.pos[1], e), lerp(a.pos[2], b.pos[2], e));
          v.set(lerp(a.look[0], b.look[0], e), lerp(a.look[1], b.look[1], e), lerp(a.look[2], b.look[2], e));
          camera.fov = lerp(a.fov, b.fov, e);
          // A very slow drift while the hero rests, fading out as the flight starts.
          const rest = Math.max(0, 1 - p / 0.06);
          camera.position.x += Math.sin(k * 0.09) * 4 * rest;
          camera.position.y += Math.sin(k * 0.06) * 1.5 * rest;
        }
        camera.lookAt(v);
        camera.updateProjectionMatrix();
      }

      // HTML labels pinned to points in the field.
      const mk = (cls: string, html: string) => {
        const d = document.createElement("div");
        d.className = cls;
        d.innerHTML = html;
        labels.appendChild(d);
        return d;
      };
      const axis = [0, 30, 60, ND - 1].map((d, k) => ({
        el: mk(`lab axis${k === 1 || k === 2 ? " mid" : ""}`, `${short(dayAt(d))} <span>${ND - 1 - d ? ND - d + " days ago" : ""}</span>`),
        p: new THREE.Vector3(dayX(d) - 0.3, 0, rowZ(NR - 1) + 2.2),
      }));
      const named: number[] = [];
      for (let i = NR - 1; i >= 0 && named.length < 6; i--) named.push(i);
      const li = rows.findIndex((r) => r.n === leadN);
      if (li >= 0 && !named.includes(li)) named.push(li);
      const names = named.map((i) => ({
        el: mk(`lab name${rows[i].head ? " head" : ""}`, `<b>${rows[i].n}</b>${rows[i].name ?? "SN" + rows[i].n}`),
        p: new THREE.Vector3(dayX(ND - 1) + 2.2, 0.2, rowZ(i)),
      }));
      const todayP = new THREE.Vector3(dayX(ND - 1) + 1.2, 0, rowZ(0) - 1);
      const proj = new THREE.Vector3();
      const project = (p3: InstanceType<typeof THREE.Vector3>) => {
        proj.copy(p3).project(camera);
        return { x: (proj.x * 0.5 + 0.5) * fig.clientWidth, y: (-proj.y * 0.5 + 0.5) * fig.clientHeight, ok: proj.z < 1 && proj.z > -1 };
      };
      function placeLabels() {
        const w = fig.clientWidth, h = fig.clientHeight;
        const lo = OVER ? w * 0.42 : 0;
        const nameOn = !FLY || progress < 0.06 || progress > 0.8;
        const axisOn = !FLY || progress < 0.06 || progress > 0.45;
        axis.forEach(({ el: a, p }) => {
          const s = project(p);
          a.style.opacity = axisOn && s.ok && s.x > lo && s.x < w - 120 && s.y > 0 && s.y < h - 8 ? "1" : "0";
          a.style.transform = `translate(${s.x}px, ${s.y + 6}px)`;
        });
        let last = -1e9;
        names.map((n) => ({ n, s: project(n.p) })).sort((a, b) => a.s.y - b.s.y).forEach(({ n, s }) => {
          const show = nameOn && s.ok && s.x > lo && s.x < w - 130 && s.y > 60 && s.y < h - 30 && s.y - last > 17;
          if (show) last = s.y;
          n.el.style.opacity = show ? "1" : "0";
          n.el.style.transform = `translate(${s.x}px, ${s.y - 8}px)`;
        });
        const t = project(todayP);
        todayEl.style.opacity = t.ok && axisOn ? "1" : "0";
        todayEl.style.transform = `translate(${Math.min(w - 160, Math.max(lo, t.x + 10))}px, ${Math.max(84, Math.min(h - 60, t.y - 40))}px)`;
      }

      function size() {
        const w = fig.clientWidth, h = fig.clientHeight;
        renderer.setSize(w, h, false);
        camera.aspect = w / h;
        // Shift the picture right on wide screens so the field sits clear of the copy column.
        if (OVER) camera.setViewOffset(w, h, -w * 0.14, 0, w, h); else camera.clearViewOffset();
        camera.updateProjectionMatrix();
        dirty = true;
      }

      // Load: the 90 days rise left to right once, then settle. Off under reduced motion.
      let grow: number | null = still ? null : performance.now();
      const easeOut = (t: number) => 1 - Math.pow(1 - t, 4);
      const growAt = (now: number) => (d: number) => easeOut(Math.min(1, Math.max(0, ((now - grow!) / 1000 - (d / ND) * 0.45) / 0.55)));

      // Scroll drives the flight, locked to the scrollbar.
      function onProgress(p: number) {
        progress = p;
        heroCopy.style.opacity = String(Math.max(0, 1 - p / 0.09));
        heroCopy.style.transform = `translateY(${-p * 240}px)`;
        heroCopy.style.visibility = p > 0.1 ? "hidden" : "visible";
        stopEls.forEach((s, k) => {
          const at = (k + 1) / 3 - (k === 2 ? 0.06 : 0);
          const o = Math.max(0, Math.min(1, 1.6 - Math.abs(p - at) / 0.1));
          s.style.opacity = String(o);
          s.style.visibility = o < 0.02 ? "hidden" : "visible";
          s.style.transform = `translateY(${(p - at) * -120}px)`;
        });
        dirty = true;
      }
      if (FLY) {
        const read = () => {
          const r = el.getBoundingClientRect();
          onProgress(Math.min(1, Math.max(0, -r.top / (r.height - innerHeight))));
        };
        on(window, "scroll", read, { passive: true });
        read();
      }

      // Hover: the row under the pointer lifts, and a tag names it.
      const ray = new THREE.Raycaster(), ndc = new THREE.Vector2(), plane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0), hit = new THREE.Vector3();
      function setHover(i: number, x = 0, y = 0) {
        if (i !== hover) { paintRow(hover, false); hover = i; paintRow(hover, true); place(); dirty = true; }
        if (i < 0) { tagEl.classList.remove("on"); return; }
        const r = rows[i];
        tagEl.innerHTML = `<b>${r.n}</b>${r.name ?? "SN" + r.n}, ${r.daily ? (r.c30 ?? 0).toLocaleString("en-GB") + " commits in 30 days" : "no readable code"}`;
        tagEl.style.transform = `translate(${Math.min(x + 14, fig.clientWidth - tagEl.offsetWidth - 8)}px, ${y - 38}px)`;
        tagEl.classList.add("on");
      }
      function pick(e: PointerEvent | MouseEvent) {
        const r = canvas.getBoundingClientRect();
        const x = e.clientX - r.left, y = e.clientY - r.top;
        ndc.set((x / r.width) * 2 - 1, -(y / r.height) * 2 + 1);
        ray.setFromCamera(ndc, camera);
        let i = -1;
        const boxHit = ray.intersectObject(mesh, false)[0];
        if (boxHit?.instanceId !== undefined) i = marks[boxHit.instanceId].i;
        else if (ray.ray.intersectPlane(plane, hit) && Math.abs(hit.x) < ND / 2 + 1) {
          const k = Math.round(hit.z + (NR - 1) / 2);
          if (k >= 0 && k < NR) i = k;
        }
        if (FLY && (e.target as Element)?.closest?.(".hero-copy, .stop")) i = -1;
        setHover(i, x, y);
      }
      const pin = fig.parentElement!;
      const onMove = (e: PointerEvent) => { if (e.pointerType === "mouse") pick(e); };
      const onLeave = () => setHover(-1);
      pin.addEventListener("pointermove", onMove);
      pin.addEventListener("pointerleave", onLeave);
      canvas.addEventListener("click", pick);
      cleanups.push(() => {
        pin.removeEventListener("pointermove", onMove);
        pin.removeEventListener("pointerleave", onLeave);
        canvas.removeEventListener("click", pick);
      });

      // Render only while the field is on screen and something changed.
      const io = new IntersectionObserver(([e]) => { visible = e.isIntersecting; if (visible) loop(); }, { rootMargin: "100px" });
      io.observe(fig);
      cleanups.push(() => io.disconnect());
      on(window, "resize", size);
      const onVis = () => { if (!document.hidden) loop(); };
      document.addEventListener("visibilitychange", onVis);
      cleanups.push(() => document.removeEventListener("visibilitychange", onVis));

      size();
      place(grow ? growAt(performance.now()) : undefined);
      function loop() {
        cancelAnimationFrame(raf);
        raf = requestAnimationFrame(function step(now) {
          if (!visible || document.hidden) return;
          const moving = (FLY && progress < 0.06) || (!OVER && !still);
          if (grow !== null) {
            place(growAt(now));
            if (now - grow > 1050) { grow = null; place(); }
            dirty = true;
          }
          if (dirty || moving) {
            frame(progress, now);
            renderer.render(scene, camera);
            placeLabels();
            dirty = false;
          }
          raf = requestAnimationFrame(step);
        });
      }
      loop();

      teardown = () => {
        cancelAnimationFrame(raf);
        labels.replaceChildren();
        geo.dispose(); mat.dispose(); bgeo.dispose(); bmat.dispose();
        mesh.dispose(); bmesh.dispose();
        renderer.dispose();
        renderer.forceContextLoss();
      };
    });

    return () => {
      disposed = true;
      teardown();
      cleanups.forEach((f) => f());
    };
  }, [rows, leadN, generatedAt]);

  return (
    <section ref={root} className="stage" aria-labelledby="hero-title">
      <div className="pin">
        <div className="figure">
          <div className="labels" aria-hidden="true" />
          <div className="today" aria-hidden="true">
            <span className="t">{new Date(generatedAt).toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" })}, data day</span>
            <br />
            <span className="b">
              est. block<strong>{block}</strong>
            </span>
            <span className="tick" style={{ transform: `scaleX(${(elapsed ?? 0) % 1})` }} />
          </div>
          <div className="tagp" aria-hidden="true" />
        </div>
        <div className="copy">
          <div className="wrap">
            <div className="hero-copy">{children}</div>
          </div>
        </div>
        <div className="stops-wrap">
          <div className="wrap relative">{stops}</div>
        </div>
      </div>
    </section>
  );
}
