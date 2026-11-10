import { test } from "node:test";
import assert from "node:assert/strict";
import { APART_AT, COLD, gapText, lastCommitText, whyText } from "../src/lib/fleet.ts";
import { mean, num, pct, signed } from "../src/lib/format.ts";
import { bundledText, heat, pendingView } from "../src/lib/upgrades.ts";
import { BAR_MODE, CROSSING, emissionMovers, paramRows, seriesTitle, usd } from "../src/lib/network.ts";

const p = (item: string, prevValue: string | null, newValue: string | null) => ({ item, prevValue, newValue, observedAt: "2026-11-01T00:00:00Z", block: 1 });

test("apart only at the board's threshold", () => {
  assert.equal(APART_AT, 40);
  assert.equal(whyText("divergence", 12), "No strong signal");
  assert.equal(whyText("divergence", -39), "No strong signal");
  assert.equal(whyText("divergence", -40), "Code and price apart");
  assert.equal(whyText("divergence", 55), "Code and price apart");
  assert.equal(whyText("divergence", null), "No strong signal");
  assert.equal(whyText("abandon", 3), "Code gone quiet");
  assert.equal(whyText("something-new", 3), "On the board");
});

test("the gap carries no direction", () => {
  assert.equal(gapText(-47), "47 places apart");
  assert.equal(gapText(47), "47 places apart");
  assert.equal(gapText(null), "no price to rank");
  assert.doesNotMatch([gapText(-47), whyText("divergence", -60)].join(" "), /ahead|behind|faster|[+−-]\d/);
});

test("cold and last-commit wording never says today", () => {
  assert.match(COLD, /30 days or more in the tracked repository/);
  for (const d of [null, 0, 1, 12]) assert.doesNotMatch(lastCommitText(d), /today/i);
  assert.equal(lastCommitText(1), "last commit 1 day before the data");
});

test("missing values print as a bare dash", () => {
  assert.equal(pct(null), "-");
  assert.equal(pct(NaN), "-");
  assert.equal(pct(12.345), "12.3%");
  assert.equal(num(-Infinity), "-");
  assert.equal(signed(NaN, 1, "%"), "-");
  assert.equal(mean([]), null);
  assert.equal(mean([2, 4]), 3);
});

test("chain parameters in plain words", () => {
  const at = (e: ReturnType<typeof p>, d: string) => ({ ...e, observedAt: `2026-10-${d}T00:00:00Z` });
  const rows = paramRows([
    at(p("SubnetEmissionEnabled[82]", "true", "false"), "30"),
    at(p("CollateralLockShare[24]", "0", "32768"), "30"),
    at(p("SubnetEmissionEnabled[82]", "false", "true"), "29"),
    at(p("SubnetEmissionEnabled[82]", "true", "false"), "19"),
    at(p("CollateralLockShare[65]", "39321", "0"), "01"),
    at(p("BasketConcentrationCap", "4096", "7865"), "01"),
    at(p("NewThing", "1", "2"), "01"),
  ]);
  assert.deepEqual(rows.map((r) => r.netuid), [82, 24, 65, null, null]);
  assert.equal(rows[0].setting, "TAO injection");
  assert.equal(rows[0].means, "Off: the chain adds no TAO to the pool. Alpha still flows.");
  assert.equal(rows[0].history, "3 changes since 19 Oct: off, on, off");
  assert.equal(rows[0].observedAt, "2026-10-30T00:00:00Z");
  assert.equal(rows[1].means, "50.0% of a miner's registration price is now locked, not burned (was 0.0%).");
  assert.equal(rows[1].history, null);
  assert.equal(rows[2].means, "0%: the whole registration price is burned again (was 60.0%).");
  assert.equal(rows[3].means, "6.3% to 12.0%: the largest share one holding may reach in a fund buy.");
  assert.deepEqual([rows[4].setting, rows[4].means], ["NewThing (chain parameter)", "1 to 2"]);
  assert.equal(BAR_MODE.rank, "A fixed number of subnets, by demand share");
});

test("sparse readings are not called daily", () => {
  assert.equal(seriesTitle(["2026-08-30", "2026-08-31", "2026-09-01"]), "daily, 3 days");
  assert.equal(seriesTitle(["2026-08-30", "2026-09-05"]), "2 readings over 7 days");
  assert.equal(seriesTitle([]), "no readings");
});

test("dollars are whole, not false cents", () => {
  assert.equal(usd(257.2), "$257");
  assert.equal(usd(null), "-");
});

test("emission movers rank by points and skip flat or missing rows", () => {
  const { up, down } = emissionMovers(
    [
      { netuid: 51, pct: 16.2, pctThen: 12.4 },
      { netuid: 28, pct: 4, pctThen: 2.2 },
      { netuid: 38, pct: 0.2, pctThen: 2.4 },
      { netuid: 7, pct: 1, pctThen: 1 },
      { netuid: 9, pct: null, pctThen: 1 },
    ],
    1,
  );
  assert.deepEqual(up.map((m) => m.netuid), [51]);
  assert.deepEqual(down.map((m) => m.netuid), [38]);
  assert.equal(CROSSING["fell-below"], "Fell below the bar");
});

test("upgrade heat steps and bundled specs read plainly", () => {
  assert.deepEqual([0, 1, 9, 10, 39, 40, 99, 100, 865].map(heat), [0, 1, 1, 2, 2, 3, 3, 4, 4]);
  assert.equal(bundledText(null), null);
  assert.equal(bundledText("480"), "Includes spec 480, never live on its own");
  assert.equal(bundledText("460, 461, 462"), "Includes specs 460, 461 and 462, never live on their own");
});

test("merged code after the live spec is not called that spec, waiting", () => {
  // 2026-11-10: the chain ran 488, and one CI commit landed after 488
  // shipped, with the repository still stating 488.
  const after = pendingView({ spec: 488, commits: 1 }, 488, "6 Nov 2026");
  assert.equal(after.label, "Next");
  assert.equal(after.heading, "Merged since spec 488");
  assert.equal(after.finding, "The chain runs spec 488; 1 commit merged since then is in no spec yet.");
  assert.doesNotMatch(after.finding + after.note, /spec 488 is merged|waiting/);
  assert.match(pendingView({ spec: 488, commits: 3 }, 488, "x").finding, /3 commits merged since then are in no spec yet/);
  // A spec above the live one is merged and waiting, as before.
  const ahead = pendingView({ spec: 488, commits: 5 }, 486, "27 Oct 2026");
  assert.equal(ahead.label, "488");
  assert.equal(ahead.heading, "Merged, waiting");
  assert.equal(ahead.finding, "The chain runs spec 486; spec 488 is merged and waiting.");
});
