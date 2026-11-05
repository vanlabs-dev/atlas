import { test } from "node:test";
import assert from "node:assert/strict";
import { APART_AT, COLD, gapText, lastCommitText, whyText } from "../src/lib/fleet.ts";
import { mean, num, pct, signed } from "../src/lib/format.ts";
import { BAR_MODE, paramRows, seriesTitle, usd } from "../src/lib/network.ts";

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
