import { test } from "node:test";
import assert from "node:assert/strict";
import { APART_AT, COLD, gapText, lastCommitText, whyText } from "../src/lib/fleet.ts";
import { mean, num, pct, signed } from "../src/lib/format.ts";
import { BAR_MODE, ROTATION, paramText, seriesTitle, usd } from "../src/lib/network.ts";

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
  assert.deepEqual(paramText(p("SubnetEmissionEnabled[103]", "true", "false")), { name: "SN103 emission", change: "switched off" });
  assert.deepEqual(paramText(p("CollateralLockShare[24]", "0", "32768")), { name: "SN24 registration collateral share", change: "0.0% to 50.0%" });
  assert.equal(paramText(p("BasketConcentrationCap", "4096", "7865")).change, "6.3% to 12.0%");
  assert.deepEqual(paramText(p("NewThing", "1", "2")), { name: "NewThing (chain parameter)", change: "1 to 2" });
  assert.equal(BAR_MODE.rank, "A fixed number of subnets, by demand share");
  assert.equal(ROTATION.entered, "Entered root weights");
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
