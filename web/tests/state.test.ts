import { test } from "node:test";
import assert from "node:assert/strict";
import { FLIGHT_ATTR, FLIGHT_MODE_SCRIPT, FLIGHT_MODES, FLIGHT_TRAITS, REDUCED_QUERY, WIDE_QUERY, flightMode } from "../src/state/flight-mode.ts";
import { FLIGHT_SCENES, REST_UNTIL, flightLabels, flightLeg, heroPose, restWeight, sceneAtProgress, sceneAtSwipe, statementPose, stopAt, swipeLeg } from "../src/state/flight-story.ts";
import { CYCLE_START, cyclePhase, cycleStep, type CycleEvent, type CycleState } from "../src/state/lead-cycle.ts";
import { DEFAULT_FILTER, fleetFilter, hashNetuid, inFilter } from "../src/state/fleet-filter.ts";
import { blockReading, blocksSince, blockText } from "../src/data/block.ts";
import { dataAge } from "../src/data/freshness.ts";
import { readPlan } from "../src/data/source-core.ts";
import { inMiningFilter, standing } from "../src/lib/mining.ts";

// ---------- flight mode ----------

const bools = [false, true];
const inputs = bools.flatMap((wide) => bools.flatMap((reduced) => bools.map((gl) => ({ wide, reduced, gl }))));

/** Runs the head script against a stub browser and returns what it wrote, plus a way to change a media query. */
function runHeadScript({ wide, reduced, gl }: { wide: boolean; reduced: boolean; gl: boolean }) {
  const attrs: Record<string, string> = {};
  let lost = 0;
  const media: Record<string, { matches: boolean; fns: (() => void)[] }> = {
    [WIDE_QUERY]: { matches: wide, fns: [] },
    [REDUCED_QUERY]: { matches: reduced, fns: [] },
  };
  const document = {
    documentElement: { setAttribute: (k: string, v: string) => { attrs[k] = v; } },
    createElement: () => ({
      getContext: (kind: string) => (gl && kind === "webgl2" ? { getExtension: () => ({ loseContext: () => { lost++; } }) } : null),
    }),
  };
  const matchMedia = (q: string) => ({
    get matches() { return media[q].matches; },
    addEventListener: (_: string, f: () => void) => { media[q].fns.push(f); },
  });
  new Function("document", "matchMedia", FLIGHT_MODE_SCRIPT)(document, matchMedia);
  const change = (q: string, matches: boolean) => { media[q].matches = matches; media[q].fns.forEach((f) => f()); };
  return { mode: () => attrs[FLIGHT_ATTR], lost: () => lost, change };
}

test("flight mode: the five modes cover every browser", () => {
  assert.equal(flightMode({ wide: true, reduced: false, gl: true }), "fly");
  assert.equal(flightMode({ wide: true, reduced: true, gl: true }), "overlay");
  assert.equal(flightMode({ wide: false, reduced: false, gl: true }), "swipe");
  assert.equal(flightMode({ wide: false, reduced: true, gl: true }), "still");
  for (const wide of bools) for (const reduced of bools) assert.equal(flightMode({ wide, reduced, gl: false }), "flat");
  assert.deepEqual(new Set(inputs.map(flightMode)), new Set(FLIGHT_MODES));
});

test("flight mode: the head script writes the same mode as the rule, for every input", () => {
  for (const i of inputs) assert.equal(runHeadScript(i).mode(), flightMode(i), JSON.stringify(i));
});

test("flight mode: the head script follows a width or motion change, and frees its WebGL probe", () => {
  const page = runHeadScript({ wide: false, reduced: false, gl: true });
  assert.equal(page.mode(), "swipe");
  assert.equal(page.lost(), 1);
  page.change(WIDE_QUERY, true);
  assert.equal(page.mode(), "fly");
  page.change(REDUCED_QUERY, true);
  assert.equal(page.mode(), "overlay");
  page.change(WIDE_QUERY, false);
  assert.equal(page.mode(), "still");
});

test("flight mode: only motion modes move the camera, and only WebGL modes ask for it", () => {
  for (const m of FLIGHT_MODES) {
    const t = FLIGHT_TRAITS[m];
    assert.equal(t.gl, m !== "flat");
    if (m === "overlay" || m === "still" || m === "flat") assert.deepEqual([t.camera, t.sway, t.rise], ["fixed", false, false], m);
  }
  assert.equal(FLIGHT_TRAITS.fly.camera, "scroll");
  assert.equal(FLIGHT_TRAITS.swipe.camera, "swipe");
});

// ---------- flight story ----------

test("flight story: each statement is centred on its stop and gone between stops", () => {
  assert.deepEqual([0, 1, 2].map(stopAt).map((v) => Number(v.toFixed(4))), [0.3333, 0.6667, 0.94]);
  for (const k of [0, 1, 2]) {
    const at = stopAt(k);
    assert.deepEqual(statementPose(at, k), { opacity: 1, shift: -0, hidden: false });
    assert.equal(statementPose(at + 0.17, k).hidden, true);
    assert.equal(statementPose(at - 0.17, k).hidden, true);
  }
  assert.equal(statementPose(0, 0).hidden, true);
});

test("flight story: the hero copy leaves in the first tenth", () => {
  assert.deepEqual(heroPose(0), { opacity: 1, shift: -0, hidden: false });
  assert.equal(heroPose(0.09).opacity, 0);
  assert.equal(heroPose(0.1).hidden, false);
  assert.equal(heroPose(0.11).hidden, true);
  assert.equal(restWeight(0), 1);
  assert.equal(restWeight(REST_UNTIL), 0);
  assert.equal(restWeight(0.5), 0);
});

test("flight story: scenes follow the scroll and the strip", () => {
  assert.deepEqual([0, 0.1, 0.2, 0.34, 0.45, 0.6, 0.8, 0.81, 1].map(sceneAtProgress), ["hero", "hero", "rows", "rows", "rows", "days", "days", "moving", "moving"]);
  assert.deepEqual([-1, 0, 0.4, 0.6, 1.4, 1.6, 2, 9].map(sceneAtSwipe), ["rows", "rows", "rows", "days", "days", "moving", "moving", "moving"]);
  assert.equal(FLIGHT_SCENES.length, 4);
});

test("flight story: labels show at rest and near the end of the flight", () => {
  assert.deepEqual(flightLabels(0), { names: true, axis: true });
  assert.deepEqual(flightLabels(0.3), { names: false, axis: false });
  assert.deepEqual(flightLabels(0.5), { names: false, axis: true });
  assert.deepEqual(flightLabels(0.9), { names: true, axis: true });
});

test("flight story: the camera holds at each stop and never leaves the last leg", () => {
  assert.deepEqual(flightLeg(0, 4), { from: 0, t: 0 });
  assert.deepEqual(flightLeg(0.05, 4), { from: 0, t: 0 });
  assert.deepEqual(flightLeg(0.33, 4), { from: 0, t: 1 });
  assert.deepEqual(flightLeg(1, 4), { from: 2, t: 1 });
  const mid = flightLeg(0.5, 4);
  assert.equal(mid.from, 1);
  assert.ok(Math.abs(mid.t - 0.5) < 1e-9);
  assert.deepEqual(swipeLeg(0, 3), { from: 0, t: 0 });
  assert.deepEqual(swipeLeg(0.25, 3), { from: 0, t: 0.25 });
  assert.deepEqual(swipeLeg(2, 3), { from: 1, t: 1 });
  assert.deepEqual(swipeLeg(7, 3), { from: 1, t: 1 });
  assert.deepEqual(swipeLeg(-3, 3), { from: 0, t: 0 });
});

// ---------- lead cycle ----------

const run = (events: CycleEvent[], from: CycleState = CYCLE_START) => events.reduce(cycleStep, from);

test("lead cycle: the timer runs only while in view, not held, with motion allowed", () => {
  assert.equal(cyclePhase(CYCLE_START, false), "offscreen");
  const seen = run([{ type: "enter" }]);
  assert.equal(cyclePhase(seen, false), "cycling");
  assert.equal(cyclePhase(seen, true), "still");
  assert.equal(cyclePhase(run([{ type: "hold" }], seen), false), "held");
  assert.equal(cyclePhase(run([{ type: "hold" }, { type: "release" }], seen), false), "cycling");
  assert.equal(cyclePhase(run([{ type: "leave" }], seen), false), "offscreen");
});

test("lead cycle: ticks wrap around the tabs", () => {
  const tick: CycleEvent = { type: "tick", tabs: 3 };
  assert.deepEqual([1, 2, 3, 4].map((n) => run(Array(n).fill(tick)).tab), [1, 2, 0, 1]);
  assert.equal(run([{ type: "tick", tabs: 0 }]).tab, 0);
});

test("lead cycle: once the visitor takes a tab, nothing gives the panel back to the timer", () => {
  const taken = run([{ type: "enter" }, { type: "tick", tabs: 3 }, { type: "take", tab: 2 }]);
  assert.equal(taken.tab, 2);
  assert.equal(cyclePhase(taken, false), "taken");
  const after = run([{ type: "tick", tabs: 3 }, { type: "leave" }, { type: "enter" }, { type: "hold" }, { type: "release" }], taken);
  assert.equal(after.tab, 2);
  assert.equal(cyclePhase(after, false), "taken");
  assert.equal(cyclePhase(after, true), "taken");
});

test("lead cycle: focus inside the panel hands it to the visitor without changing the tab", () => {
  const s = run([{ type: "enter" }, { type: "tick", tabs: 3 }, { type: "focus" }]);
  assert.equal(s.tab, 1);
  assert.equal(cyclePhase(s, false), "taken");
});

test("lead cycle: repeated events return the same state object", () => {
  const seen = run([{ type: "enter" }]);
  assert.equal(cycleStep(seen, { type: "enter" }), seen);
  assert.equal(cycleStep(seen, { type: "release" }), seen);
});

// ---------- fleet filter ----------

test("fleet filter: default, then a link, then the visitor", () => {
  assert.deepEqual(fleetFilter("", null, null), { filter: DEFAULT_FILTER, source: "default" });
  assert.deepEqual(fleetFilter("#sn20", "quiet", null), { filter: "quiet", source: "link" });
  assert.deepEqual(fleetFilter("#sn20", "quiet", { filter: "all", atHash: "#sn20" }), { filter: "all", source: "visitor" });
  assert.deepEqual(fleetFilter("", null, { filter: "mid", atHash: "" }), { filter: "mid", source: "visitor" });
});

test("fleet filter: a link to another subnet beats an older choice", () => {
  const choice = { filter: "quiet" as const, atHash: "" };
  assert.deepEqual(fleetFilter("#sn68", "head", choice), { filter: "head", source: "link" });
  // A hash that names no row on the board does not undo the choice.
  assert.deepEqual(fleetFilter("#reads", null, choice), { filter: "quiet", source: "visitor" });
});

test("fleet filter: hashes and rows", () => {
  assert.equal(hashNetuid("#sn20"), 20);
  assert.equal(hashNetuid("#sn"), null);
  assert.equal(hashNetuid("#sn20x"), null);
  assert.equal(hashNetuid(""), null);
  const rows = [{ tier: "head" as const }, { tier: "mid" as const }, { tier: "quiet" as const }];
  assert.equal(rows.filter(inFilter("all")).length, 3);
  assert.deepEqual(rows.filter(inFilter("mid")), [{ tier: "mid" }]);
});

// ---------- block clock, data age, read plan, mining ----------

test("block clock: none without an anchor, pending before the clock, then ticking", () => {
  const anchor = { block: 1000, at: "2026-11-01T00:00:00Z" };
  assert.deepEqual(blockReading(null, null), { state: "none" });
  assert.deepEqual(blockReading(null, 4), { state: "none" });
  assert.deepEqual(blockReading(anchor, null), { state: "pending" });
  const elapsed = blocksSince(anchor, Date.parse(anchor.at) + 30_000);
  assert.equal(elapsed, 2.5);
  assert.deepEqual(blockReading(anchor, elapsed), { state: "ticking", block: 1002, fraction: 0.5 });
  assert.equal(blockText(blockReading(anchor, elapsed)), "1,002");
  assert.equal(blockText(blockReading(anchor, null)), "-");
});

test("data age: the server judges staleness at read time, the browser by its own clock", () => {
  const at = "2026-10-01T00:00:00Z";
  const later = (h: number) => new Date(Date.parse(at) + h * 3_600_000);
  assert.deepEqual(dataAge(at, later(1).toISOString(), null), { clock: "read", status: "fresh", label: null });
  assert.deepEqual(dataAge(at, later(49).toISOString(), null), { clock: "read", status: "stale", label: null });
  assert.deepEqual(dataAge(at, undefined, null), { clock: "read", status: "fresh", label: null });
  assert.deepEqual(dataAge(at, later(1).toISOString(), later(72)), { clock: "live", status: "stale", label: "3 days ago" });
  assert.deepEqual(dataAge(at, later(49).toISOString(), later(5)), { clock: "live", status: "fresh", label: "5 h ago" });
});

test("read plan: fixture without settings; the store otherwise, failing soft only while building", () => {
  const store = { SUPABASE_URL: "https://example.supabase.co/", SUPABASE_PUBLISHABLE_KEY: "sb_publishable_test" };
  const config = { url: "https://example.supabase.co", key: "sb_publishable_test" };
  assert.deepEqual(readPlan({}), { from: "fixture", why: "not-configured" });
  assert.deepEqual(readPlan({ SUPABASE_URL: store.SUPABASE_URL }), { from: "fixture", why: "not-configured" });
  assert.deepEqual(readPlan(store), { from: "store", config, onFailure: "throw" });
  assert.deepEqual(readPlan({ ...store, NEXT_PHASE: "phase-production-build" }), { from: "store", config, onFailure: "fixture" });
  assert.deepEqual(readPlan({ ...store, NEXT_PHASE: "phase-production-server" }), { from: "store", config, onFailure: "throw" });
});

test("mining: standing and the scan filter", () => {
  const row = (o: Partial<{ rank: number | null; cutReason: string | null; unratedReason: string | null }>) => ({ rank: null, cutReason: null, unratedReason: null, ...o });
  assert.equal(standing(row({ rank: 3 })), "ranked");
  assert.equal(standing(row({ cutReason: "prune-risk" })), "cut");
  assert.equal(standing(row({ rank: 3, cutReason: "prune-risk" })), "cut");
  assert.equal(standing(row({ unratedReason: "not-emitting" })), "unrated");
  assert.equal(standing(row({ rank: 2, unratedReason: "not-emitting" })), "ranked");
  assert.equal(standing(row({})), "unlisted");
  const verdicts = ["possible", "needs-gpu", "unknown", "closed", "stub", null] as const;
  const count = (f: Parameters<typeof inMiningFilter>[0]) => verdicts.filter((verdict) => inMiningFilter(f)({ verdict })).length;
  assert.deepEqual([count("all"), count("possible"), count("needs-gpu"), count("other")], [6, 1, 1, 4]);
});
