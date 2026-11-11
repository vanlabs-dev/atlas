"use client";

import { useEffect, useRef, useSyncExternalStore, type ReactNode } from "react";
import { blockText, type BlockAnchor } from "@/data/block";
import { useBlockReading } from "@/components/block-clock";
import { FLIGHT_TRAITS, readFlightMode, watchFlightMode } from "@/state/flight-mode";
import { FLIGHT_SCENES, REST_UNTIL, STATEMENTS, flightLabels, flightLeg, heroPose, restWeight, sceneAtProgress, sceneAtSwipe, statementPose, swipeLeg, type FlightScene } from "@/state/flight-story";

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
// The phone's three views, one per statement; a swipe through the strip blends between them.
// `sway` is how far the camera drifts sideways while a view rests.
const PHONE_STOPS = [
  { pos: [4, 92, 116], look: [2, -10, 8], fov: 44, sway: 26 }, // rows: the whole field from above
  { pos: [34, 30, 104], look: [14, 0, 44], fov: 44, sway: 9 }, // days: low enough to read the height of a mark
  { pos: [22, 11, 84], look: [36, 1, 46], fov: 44, sway: 4 }, // moving: along the busiest rows to the today edge
] as const;
const NO_ROW = -1;
const FIELD_LABEL =
  "90 days of commits for all 128 subnets, one row per subnet, one column per day, newest on the right. Quiet subnets sit at the back, the busiest at the front.";

/**
 * The home hero: 128 subnets x 90 days of commits as a 3D field. Rows arrive
 * in sediment order: no code at the back, then silent, then by 30-day commits.
 *
 * What it does is set by the stage mode on <html data-flight>
 * (src/state/flight-mode.ts): fly (the scroll flies the camera), overlay
 * (still, copy over it), swipe (a phone: the statement strip moves the
 * camera), still, or flat (no WebGL, drawn in 2D). When the mode changes (a
 * tablet turns, reduced motion is switched on) the effect below tears the
 * field down and builds it again in the new mode.
 *
 * State a reader or a test can see in the DOM:
 *   .figure[data-field]  loading | live | flat   the field's lifecycle
 *   .stage[data-scene]   hero | rows | days | moving   the story position (fly and swipe)
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
  const reading = useBlockReading(anchor);
  // Null on the server and until the head script's attribute is read: no field is built without a mode.
  const mode = useSyncExternalStore(watchFlightMode, readFlightMode, () => null);

  useEffect(() => {
    const el = root.current;
    if (!el || !mode) return;
    const traits = FLIGHT_TRAITS[mode];
    const byScroll = traits.camera === "scroll";
    const bySwipe = traits.camera === "swipe";
    const fig = el.querySelector<HTMLDivElement>(".figure")!;
    fig.dataset.field = traits.gl ? "loading" : "flat";
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
    const strip = el.querySelector<HTMLElement>(".stops");
    const pagerEls = [...el.querySelectorAll<HTMLButtonElement>(".pager button")];
    const setScene = (scene: FlightScene | null) => {
      if (scene === null) delete el.dataset.scene;
      else if (el.dataset.scene !== scene) el.dataset.scene = scene;
      else return;
      // Statement k is scene k + 1; the hero (or no scene) marks the first.
      const on = Math.max(0, (scene === null ? 0 : FLIGHT_SCENES.indexOf(scene)) - 1);
      pagerEls.forEach((b, k) => (k === on ? b.setAttribute("aria-current", "true") : b.removeAttribute("aria-current")));
    };

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

    const cleanups: (() => void)[] = [() => canvas.remove(), () => delete fig.dataset.field, () => setScene(null)];
    const on = <K extends keyof WindowEventMap>(t: Window, k: K, f: (e: WindowEventMap[K]) => void, o?: AddEventListenerOptions) => {
      t.addEventListener(k, f, o);
      cleanups.push(() => t.removeEventListener(k, f, o));
    };
    let disposed = false;

    if (!traits.gl) {
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
      fig.dataset.field = "live";
      // progress: the page scroll through the stage, 0 to 1 (fly). swipe: the strip position, 0 to 2 (swipe).
      let dirty = true, visible = true, progress = 0, swipe = 0, hover = NO_ROW, raf = 0;
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
        if (i === NO_ROW) return;
        byRow[i].forEach((idx) => mesh.setColorAt(idx, onRow ? lit : marks[idx].color));
        if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
      }

      const lerp = (a: number, b: number, t: number) => a + (b - a) * t;
      type Stop = { readonly pos: readonly number[]; readonly look: readonly number[]; readonly fov: number };
      const between = (a: Stop, b: Stop, t: number) => {
        camera.position.set(lerp(a.pos[0], b.pos[0], t), lerp(a.pos[1], b.pos[1], t), lerp(a.pos[2], b.pos[2], t));
        v.set(lerp(a.look[0], b.look[0], t), lerp(a.look[1], b.look[1], t), lerp(a.look[2], b.look[2], t));
        camera.fov = lerp(a.fov, b.fov, t);
      };
      function frame(now: number) {
        const k = (now - t0) / 1000;
        if (byScroll) {
          const { from, t } = flightLeg(progress, STOPS.length);
          between(STOPS[from], STOPS[from + 1], t);
          // A very slow drift while the hero rests, fading out as the flight starts.
          const rest = restWeight(progress);
          camera.position.x += Math.sin(k * 0.09) * 4 * rest;
          camera.position.y += Math.sin(k * 0.06) * 1.5 * rest;
        } else if (bySwipe) {
          const { from, t } = swipeLeg(swipe, PHONE_STOPS.length);
          const a = PHONE_STOPS[from], b = PHONE_STOPS[from + 1];
          between(a, b, t);
          // A phone has no flight, so the camera sways slowly across the view it rests on.
          const sway = lerp(a.sway, b.sway, t);
          camera.position.x += Math.sin(k * 0.22) * sway;
          camera.position.y += Math.sin(k * 0.15) * sway * 0.3;
          v.x += Math.sin(k * 0.22) * sway * 0.3;
        } else {
          const s = traits.over ? STOPS[0] : PHONE_STOPS[0];
          between(s, s, 0);
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
      // A label that is off is out of the layout tree as well as unseen.
      const show = (node: HTMLElement, on: boolean) => {
        node.style.opacity = on ? "1" : "0";
        node.style.visibility = on ? "visible" : "hidden";
      };
      function placeLabels() {
        const w = fig.clientWidth, h = fig.clientHeight;
        const lo = traits.over ? w * 0.42 : 0;
        const { names: nameOn, axis: axisOn } = byScroll ? flightLabels(progress) : { names: true, axis: true };
        // The today label first: the names and the dates keep clear of it.
        const t = project(todayP);
        // On a phone the today edge is in the picture only for the first statement's view.
        const todayOn = t.ok && axisOn && (!bySwipe || swipe < 0.5);
        // Kept inside the figure: by a fixed allowance over the copy, by its own width and the page margin elsewhere.
        const right = traits.over ? w - 160 : w - todayEl.offsetWidth - 16;
        const tx = Math.min(right, Math.max(lo, t.x + 10)), ty = Math.max(84, Math.min(h - 60, t.y - 40));
        show(todayEl, todayOn);
        todayEl.style.transform = `translate(${tx}px, ${ty}px)`;
        // Without the copy over the field, the strip of statements follows the figure: a date at the
        // very bottom would read as a label on the first statement.
        const floor = traits.over ? h - 8 : h - 44;
        axis.forEach(({ el: a, p }) => {
          const s = project(p);
          show(a, axisOn && s.ok && s.x > lo && s.x < w - 120 && s.y > 0 && s.y < floor);
          a.style.transform = `translate(${s.x}px, ${s.y + 6}px)`;
        });
        let last = -1e9;
        names.map((n) => ({ n, s: project(n.p) })).sort((a, b) => a.s.y - b.s.y).forEach(({ n, s }) => {
          // Over the copy the name under the today label is placed by the camera stops; elsewhere the two can meet.
          const underToday = !traits.over && todayOn && s.x + 150 > tx && s.y > ty - 14 && s.y < ty + 52;
          const on = nameOn && !underToday && s.ok && s.x > lo && s.x < w - 130 && s.y > 60 && s.y < h - 30 && s.y - last > 17;
          if (on) last = s.y;
          show(n.el, on);
          n.el.style.transform = `translate(${s.x}px, ${s.y - 8}px)`;
        });
      }

      function size() {
        const w = fig.clientWidth, h = fig.clientHeight;
        renderer.setSize(w, h, false);
        camera.aspect = w / h;
        // Shift the picture right on wide screens so the field sits clear of the copy column.
        if (traits.over) camera.setViewOffset(w, h, -w * 0.14, 0, w, h); else camera.clearViewOffset();
        camera.updateProjectionMatrix();
        dirty = true;
      }

      // Load: the 90 days rise left to right once, then settle. Off under reduced motion.
      // null once the rise has settled.
      let grow: number | null = traits.rise ? performance.now() : null;
      const easeOut = (t: number) => 1 - Math.pow(1 - t, 4);
      const growAt = (now: number) => (d: number) => easeOut(Math.min(1, Math.max(0, ((now - grow!) / 1000 - (d / ND) * 0.45) / 0.55)));

      const pose = (node: HTMLElement, p: { opacity: number; shift: number; hidden: boolean }) => {
        node.style.opacity = String(p.opacity);
        node.style.transform = `translateY(${p.shift}px)`;
        node.style.visibility = p.hidden ? "hidden" : "visible";
      };
      if (byScroll) {
        // The page scroll drives the flight, locked to the scrollbar.
        const read = () => {
          const r = el.getBoundingClientRect();
          progress = Math.min(1, Math.max(0, -r.top / (r.height - innerHeight)));
          pose(heroCopy, heroPose(progress));
          stopEls.forEach((s, k) => pose(s, statementPose(progress, k)));
          setScene(sceneAtProgress(progress));
          dirty = true;
        };
        on(window, "scroll", read, { passive: true });
        read();
        // Another mode lays these out in CSS: leave no inline pose behind.
        cleanups.push(() => [heroCopy, ...stopEls].forEach((n) => n.removeAttribute("style")));
      }
      if (bySwipe && strip) {
        // The statement strip drives the camera: each statement has its own view of the field.
        const read = () => {
          const span = strip.scrollWidth - strip.clientWidth;
          swipe = span > 0 ? (strip.scrollLeft / span) * (STATEMENTS - 1) : 0;
          setScene(sceneAtSwipe(swipe));
          dirty = true;
        };
        strip.addEventListener("scroll", read, { passive: true });
        const step = (e: Event) => {
          const k = Number((e.currentTarget as HTMLElement).dataset.statement);
          const span = strip.scrollWidth - strip.clientWidth;
          strip.scrollTo({ left: (span * k) / (STATEMENTS - 1), behavior: "smooth" });
        };
        pagerEls.forEach((b) => b.addEventListener("click", step));
        cleanups.push(() => pagerEls.forEach((b) => b.removeEventListener("click", step)));
        // A scroller must be reachable by keyboard; the arrow keys then move it.
        strip.tabIndex = 0;
        read();
        cleanups.push(() => {
          strip.removeEventListener("scroll", read);
          strip.removeAttribute("tabindex");
        });
      }

      // Hover: the row under the pointer lifts, and a tag names it.
      const ray = new THREE.Raycaster(), ndc = new THREE.Vector2(), plane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0), hit = new THREE.Vector3();
      function setHover(i: number, x = 0, y = 0) {
        if (i !== hover) { paintRow(hover, false); hover = i; paintRow(hover, true); place(); dirty = true; }
        if (i === NO_ROW) { tagEl.classList.remove("on"); return; }
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
        let i = NO_ROW;
        const boxHit = ray.intersectObject(mesh, false)[0];
        if (boxHit?.instanceId !== undefined) i = marks[boxHit.instanceId].i;
        else if (ray.ray.intersectPlane(plane, hit) && Math.abs(hit.x) < ND / 2 + 1) {
          const k = Math.round(hit.z + (NR - 1) / 2);
          if (k >= 0 && k < NR) i = k;
        }
        if (byScroll && (e.target as Element)?.closest?.(".hero-copy, .stop")) i = NO_ROW;
        setHover(i, x, y);
      }
      const pin = fig.parentElement!;
      const onMove = (e: PointerEvent) => { if (e.pointerType === "mouse") pick(e); };
      const onLeave = () => setHover(NO_ROW);
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
          // The camera drifts while the hero rests (fly) and always sways on a phone (swipe).
          const moving = traits.sway && (bySwipe || progress < REST_UNTIL);
          if (grow !== null) {
            place(growAt(now));
            if (now - grow > 1050) { grow = null; place(); }
            dirty = true;
          }
          if (dirty || moving) {
            frame(now);
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
  }, [rows, leadN, generatedAt, mode]);

  return (
    <section ref={root} className="stage" aria-labelledby="hero-title">
      <div className="pin">
        <div className="figure">
          <div className="labels" aria-hidden="true" />
          <div className="today" aria-hidden="true">
            <span className="t">{new Date(generatedAt).toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" })}, data day</span>
            <br />
            <span className="b">
              est. block now<strong>{blockText(reading)}</strong>
            </span>
            <span className="tick" style={{ transform: `scaleX(${reading.state === "ticking" ? reading.fraction : 0})` }} />
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
          {/* Swipe mode only: which statement of the strip is on show, and a tap to step to another. */}
          <div className="pager" role="group" aria-label="Statements about the field">
            {Array.from({ length: STATEMENTS }, (_, k) => (
              <button key={k} type="button" data-statement={k} aria-label={`Statement ${k + 1} of ${STATEMENTS}`} aria-current={k === 0 ? "true" : undefined}>
                <i />
              </button>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
