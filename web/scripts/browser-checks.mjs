// Browser checks for the explicit state machines and the phone layout (README, "State
// machines"). They read the states the page publishes in the DOM (data-flight, data-field,
// data-scene, data-cycle, data-filter, data-filter-source) in a real Chromium.
//
//   npm run build && npm run start -- -p 3100     # in one shell
//   npm run check:browser                         # in another; optional base URL argument
//
// Needs the CDP helper of the design-taste-frontend skill (override its path with CDP_LIB)
// and an installed Chromium. It is not part of `npm test`, which needs no browser.
import { homedir } from "node:os";

const lib = process.env.CDP_LIB ?? `${homedir()}/.claude/skills/design-taste-frontend/scripts/lib/cdp.mjs`;
const { Browser, sleep } = await import(lib);
const base = process.argv[2] ?? "http://localhost:3100";
const browser = await Browser.launch({ width: 390, height: 844 });
let bad = 0;
const check = (name, ok, detail = "") => { if (!ok) bad++; console.log(`${ok ? "OK  " : "FAIL"} ${name} ${detail}`); };
const state = (page) => page.eval(() => ({
  path: location.pathname + location.hash,
  flight: document.documentElement.dataset.flight,
  field: document.querySelector(".figure")?.dataset.field,
  scene: document.querySelector(".stage")?.dataset.scene,
  cycle: document.querySelector(".leadp")?.dataset.cycle,
  filter: document.querySelector("[data-filter]")?.dataset.filter,
  source: document.querySelector("[data-filter-source]")?.dataset.filterSource,
  overflowX: document.documentElement.scrollWidth - innerWidth,
}));
try {
  // ---- phone ----
  const page = await browser.newPage({ width: 390, height: 844, dsf: 1, mobile: true });
  await page.goto(base + "/", { settleMs: 2500 });
  let s = await state(page);
  check("phone home: swipe mode, field live, first scene", s.flight === "swipe" && s.field === "live" && s.scene === "rows", JSON.stringify(s));
  check("phone home: no sideways page scroll", s.overflowX <= 0, `overflow ${s.overflowX}`);
  check("phone home: lead cycle waits off screen", s.cycle === "offscreen", s.cycle);

  // lead panel: cycling in view, taken after a tab
  await page.eval(() => document.querySelector(".leadp").scrollIntoView({ block: "start" }));
  await sleep(700);
  s = await state(page);
  check("lead cycle runs in view", s.cycle === "cycling", s.cycle);
  await page.eval(() => document.querySelectorAll(".leadp [role=tab]")[2].click());
  await sleep(300);
  const tab = await page.eval(() => ({ cycle: document.querySelector(".leadp").dataset.cycle, sel: [...document.querySelectorAll(".leadp [role=tab]")].findIndex((b) => b.getAttribute("aria-selected") === "true") }));
  check("lead cycle: a taken tab stays taken", tab.cycle === "taken" && tab.sel === 2, JSON.stringify(tab));

  // deep link from the home watch list, by client navigation
  const first = await page.eval(() => { const a = document.querySelector(".wrow a"); a.click(); return a.getAttribute("href"); });
  await sleep(1800);
  s = await state(page);
  const row1 = await page.eval(() => { const el = document.querySelector(location.hash); const b = el?.getBoundingClientRect(); return el ? { top: Math.round(b.top), h: Math.round(b.height), vis: b.top >= 0 && b.bottom <= innerHeight } : null; });
  check(`deep link ${first}: the row's tab opens and the row is on screen`, s.path === first && s.source === "link" && row1?.vis, JSON.stringify({ ...s, row1 }));

  // the visitor picks Quiet, goes home, follows a link to a row in another tier
  await page.eval(() => [...document.querySelectorAll("[role=radio]")].find((b) => b.textContent.startsWith("Quiet")).click());
  await sleep(300);
  s = await state(page);
  check("fleet: a chosen tab wins over the old link", s.filter === "quiet" && s.source === "visitor", JSON.stringify(s));
  await page.eval(() => document.querySelector('nav[aria-label="Pages"] a[href="/"]').click());
  await sleep(1800);
  s = await state(page);
  check("back home by the bottom bar: field live again", s.path === "/" && s.field === "live" && s.flight === "swipe", JSON.stringify(s));
  const second = await page.eval(() => { const a = document.querySelectorAll(".wrow a")[1]; a.click(); return a.getAttribute("href"); });
  await sleep(1800);
  s = await state(page);
  const row2 = await page.eval(() => { const el = document.querySelector(location.hash); const b = el?.getBoundingClientRect(); return el ? { vis: b.top >= 0 && b.bottom <= innerHeight } : null; });
  check(`new deep link ${second} after a choice: the link wins, the row shows`, s.path === second && s.source === "link" && row2?.vis === true, JSON.stringify({ ...s, row2 }));
  check("phone fleet: no sideways page scroll", s.overflowX <= 0, `overflow ${s.overflowX}`);

  // filter keyboard: arrow keys move the choice
  await page.eval(() => document.querySelector("[role=radio][aria-checked=true]").focus());
  await page.send("Input.dispatchKeyEvent", { type: "keyDown", key: "ArrowRight", code: "ArrowRight", windowsVirtualKeyCode: 39 });
  await page.send("Input.dispatchKeyEvent", { type: "keyUp", key: "ArrowRight", code: "ArrowRight", windowsVirtualKeyCode: 39 });
  await sleep(200);
  const kb = await page.eval(() => ({ checked: document.querySelector("[role=radio][aria-checked=true]").textContent, focused: document.activeElement.textContent, tabstops: document.querySelectorAll("[role=radio][tabindex='0']").length }));
  check("filter: the arrow key moves choice and focus, one tab stop", kb.checked === kb.focused && kb.tabstops === 1, JSON.stringify(kb));
  check("phone: no page errors", page.consoleErrors.length === 0, JSON.stringify(page.consoleErrors));
  await page.close();

  // ---- the same row id on two live pages: mining first, then a fleet deep link ----
  const dup = await browser.newPage({ width: 390, height: 844, dsf: 1, mobile: true });
  await dup.goto(base + "/mining", { settleMs: 1500 });
  await dup.eval(() => document.querySelector('nav[aria-label="Pages"] a[href="/"]').click());
  await sleep(2000);
  const href = await dup.eval(() => { const a = document.querySelector(".wrow a"); a.click(); return a.getAttribute("href"); });
  await sleep(1800);
  const d2 = await dup.eval(() => {
    const same = document.querySelectorAll(`[id="${location.hash.slice(1)}"]`).length;
    const el = document.querySelector(".rowlist.fleet [data-linked]");
    const b = el?.getBoundingClientRect();
    return { path: location.pathname + location.hash, same, vis: !!el && b.top >= 0 && b.bottom <= innerHeight, bg: el ? getComputedStyle(el).backgroundColor : null, ground: getComputedStyle(document.body).backgroundColor };
  });
  check(`deep link ${href} with mining kept alive: the fleet row shows, marked`, d2.path === href && d2.vis && d2.bg !== d2.ground && d2.bg !== "rgba(0, 0, 0, 0)", JSON.stringify(d2));
  await dup.close();

  // ---- a tablet turns: the mode follows the width ----
  const tab2 = await browser.newPage({ width: 820, height: 1180, dsf: 1, mobile: true });
  await tab2.goto(base + "/", { settleMs: 2500 });
  s = await state(tab2);
  check("tablet upright: swipe mode", s.flight === "swipe" && s.field === "live", JSON.stringify(s));
  await tab2.setViewport({ width: 1180, height: 820, dsf: 1, mobile: true });
  await sleep(2500);
  s = await state(tab2);
  const stage = await tab2.eval(() => ({ h: Math.round(document.querySelector(".stage").offsetHeight / innerHeight * 100), canvases: document.querySelectorAll(".figure canvas").length, strip: document.querySelector(".stops").hasAttribute("tabindex") }));
  check("tablet turned: fly mode, one canvas, a 420vh stage", s.flight === "fly" && s.field === "live" && s.scene === "hero" && stage.h === 420 && stage.canvases === 1 && !stage.strip, JSON.stringify({ ...s, stage }));
  await tab2.setViewport({ width: 820, height: 1180, dsf: 1, mobile: true });
  await sleep(2500);
  s = await state(tab2);
  const back = await tab2.eval(() => ({ canvases: document.querySelectorAll(".figure canvas").length, inline: document.querySelector(".hero-copy").getAttribute("style"), stops: [...document.querySelectorAll(".stop")].map((x) => x.getAttribute("style")) }));
  check("tablet upright again: swipe mode, no leftovers", s.flight === "swipe" && s.field === "live" && back.canvases === 1 && !back.inline && back.stops.every((x) => !x), JSON.stringify({ ...s, back }));
  check("tablet: no page errors", tab2.consoleErrors.length === 0, JSON.stringify(tab2.consoleErrors));
  await tab2.close();

  // ---- reduced motion ----
  const rm = await browser.newPage({ width: 390, height: 844, dsf: 1, mobile: true, reducedMotion: true });
  await rm.goto(base + "/", { settleMs: 2000 });
  s = await state(rm);
  check("reduced motion, phone: still mode", s.flight === "still" && s.field === "live" && s.scene === undefined, JSON.stringify(s));
  await rm.eval(() => document.querySelector(".leadp").scrollIntoView({ block: "start" }));
  await sleep(600);
  s = await state(rm);
  check("reduced motion: the cycle is still", s.cycle === "still", s.cycle);
  await rm.close();
  const rmd = await browser.newPage({ width: 1280, height: 720, reducedMotion: true });
  await rmd.goto(base + "/", { settleMs: 2000 });
  s = await state(rmd);
  check("reduced motion, desktop: overlay mode", s.flight === "overlay" && s.field === "live", JSON.stringify(s));
  await rmd.close();

  // ---- desktop flight ----
  const d = await browser.newPage({ width: 1280, height: 720 });
  await d.goto(base + "/", { settleMs: 2500 });
  s = await state(d);
  check("desktop: fly mode at the hero", s.flight === "fly" && s.field === "live" && s.scene === "hero", JSON.stringify(s));
  const scenes = [];
  for (const f of [0.34, 0.67, 0.95]) {
    await d.eval((ff) => { const st = document.querySelector(".stage"); window.scrollTo(0, (st.offsetHeight - innerHeight) * ff); }, f);
    await sleep(500);
    scenes.push(await d.eval(() => ({ scene: document.querySelector(".stage").dataset.scene, seen: [...document.querySelectorAll(".stop")].map((x) => getComputedStyle(x).visibility === "visible") })));
  }
  check("desktop: the scroll passes rows, days, moving, one statement each", scenes.map((x) => x.scene).join() === "rows,days,moving" && scenes.every((x, i) => x.seen.filter(Boolean).length === 1 && x.seen[i]), JSON.stringify(scenes));
  check("desktop: bottom bar hidden, top nav shown", await d.eval(() => getComputedStyle(document.querySelector('nav[aria-label="Pages"]')).display === "none" && getComputedStyle(document.querySelector('nav[aria-label="Boards"]')).display !== "none"));
  check("desktop: no page errors", d.consoleErrors.length === 0, JSON.stringify(d.consoleErrors));
  await d.close();

  // ---- the phone's bars: step down every page and hit-test each line of text of 24px or more ----
  for (const path of ["/", "/mining", "/fleet", "/network", "/upgrades"]) {
    const cover = await browser.newPage({ width: 390, height: 844, mobile: true });
    await cover.goto(base + path, { settleMs: 2000 });
    const total = await cover.eval(() => document.documentElement.scrollHeight);
    const other = new Set(); let byBar = 0, steps = 0;
    for (let y = 0; y < total; y += 211, steps++) {
      await cover.eval((yy) => window.scrollTo(0, yy), y);
      await sleep(60);
      const r = await cover.eval(() => {
        const bar = document.querySelector('nav[aria-label="Pages"]');
        const out = { bar: 0, other: [] };
        for (const el of document.querySelectorAll("h1,h2,h3,p,li,a,span,div,b,dd")) {
          let direct = ""; for (const n of el.childNodes) if (n.nodeType === 3) direct += n.nodeValue;
          if (direct.trim().length < 3) continue;
          const cs = getComputedStyle(el);
          if (parseFloat(cs.fontSize) < 24 || cs.visibility === "hidden" || +cs.opacity < 0.3) continue;
          const range = document.createRange();
          for (const node of el.childNodes) {
            if (node.nodeType !== 3 || !node.nodeValue.trim()) continue;
            range.selectNodeContents(node);
            for (const b of range.getClientRects()) {
              if (b.width < 6 || b.bottom < 0 || b.top > innerHeight) continue;
              for (const fx of [0.15, 0.5, 0.85]) {
                const x = b.left + b.width * fx, y = b.top + b.height * 0.55;
                if (x < 0 || x >= innerWidth || y < 0 || y >= innerHeight) continue;
                const hit = document.elementFromPoint(x, y);
                if (!hit || hit === el || el.contains(hit) || hit.contains(el)) continue;
                if (bar.contains(hit)) out.bar++;
                else if (hit.closest(".filter-tabs")) out.bar++;
                else out.other.push(`${direct.trim().slice(0, 30)} <- ${hit.tagName}.${hit.className?.baseVal ?? hit.className}`.slice(0, 90));
              }
            }
          }
        }
        return out;
      });
      byBar += r.bar; r.other.forEach((o) => other.add(o));
    }
    const end = await cover.eval(() => {
      window.scrollTo(0, document.documentElement.scrollHeight);
      const bar = document.querySelector('nav[aria-label="Pages"]').getBoundingClientRect();
      const last = [...document.querySelectorAll("footer p, footer a")].pop().getBoundingClientRect();
      return { barTop: Math.round(bar.top), lastBottom: Math.round(last.bottom) };
    });
    check(`phone ${path}: only the bars pass over large text, and the last line clears the bottom bar`, other.size === 0 && end.lastBottom <= end.barTop, `under the bars ${byBar}, other covers ${other.size}, last text ${end.lastBottom} <= bar ${end.barTop} ${[...other].slice(0, 5).join(" | ")}`);
    await cover.close();
  }
} finally {
  await browser.close();
}
console.log(bad ? `${bad} FAILED` : "all browser checks pass");
process.exit(bad ? 1 : 0);
