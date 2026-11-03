import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { ALLOWLIST, pick } from "../scripts/allowlist.ts";
import { findLeaks } from "../scripts/scrub.ts";

const DIR = join(import.meta.dirname, "../src/data/fixtures");
const files = readdirSync(DIR).filter((name) => name.endsWith(".json"));

test("fixtures exist", () => {
  assert.deepEqual(files.sort(), ["fleet.json", "mining.json", "network.json", "upgrades.json"]);
});

for (const name of files) {
  const text = readFileSync(join(DIR, name), "utf8");

  test(`${name} has no leaks`, () => {
    assert.deepEqual(findLeaks(text), []);
  });

  test(`${name} has no em dash`, () => {
    assert.ok(!text.includes("\u2014"));
  });
}

test("scrub catches planted leaks", () => {
  const planted = [
    "ghp_aB3dE5fG7hJ9kL1mN3pQ5rS7",
    "7123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw1",
    "10.1.2.3",
    "pi@device.local",
    "/home/someone/project/store.db",
    "5F3sa2TJAWMqDhXG6jhV4N8ko9SxwGy8TpaNS1repo5EYjQX",
  ];
  for (const leak of planted) {
    const text = JSON.stringify({ data: [{ name: leak }] });
    assert.ok(findLeaks(text).length > 0, leak);
  }
});

test("allowlist drops unlisted fields", () => {
  const record = pick("mining", {
    netuid: 7,
    subnet_name: "Seven",
    owner_ss58: "5F3sa2TJAWMqDhXG6jhV4N8ko9SxwGy8TpaNS1repo5EYjQX",
    hotkey: "secret",
  });
  assert.deepEqual(Object.keys(record), Object.keys(ALLOWLIST.mining));
  assert.equal(record.netuid, 7);
  assert.ok(!JSON.stringify(record).includes("5F3sa2"));
});

test("allowlist rounds and strips em dashes", () => {
  const record = pick("vitals", { tao_usd: 257.16123, date: "a \u2014 b" });
  assert.equal(record.taoUsd, 257.2);
  assert.equal(record.date, "a - b");
});

test("allowlist rejects nested values", () => {
  assert.throws(() => pick("signal", { class: { nested: true } }));
});

test("allowlist accepts only a 90-day integer series", () => {
  const good = Array.from({ length: 90 }, (_, i) => i % 3);
  assert.deepEqual(pick("activity", { netuid: 1, daily: good }).daily, good);
  assert.equal(pick("activity", { netuid: 1, daily: null }).daily, null);
  assert.throws(() => pick("activity", { netuid: 1, daily: good.slice(1) }));
  assert.throws(() => pick("activity", { netuid: 1, daily: [...good.slice(1), -1] }));
  assert.throws(() => pick("activity", { netuid: 1, daily: [...good.slice(1), 0.5] }));
  assert.throws(() => pick("activity", { netuid: 1, daily: [...good.slice(1), "x"] }));
});

test("daily series cover 128 subnets and match the board counts", () => {
  const fleet = JSON.parse(readFileSync(join(DIR, "fleet.json"), "utf8")).data;
  assert.deepEqual(
    fleet.activity.map((a: { netuid: number }) => a.netuid),
    Array.from({ length: 128 }, (_, i) => i + 1),
  );
  const daily = new Map(fleet.activity.map((a: { netuid: number; daily: number[] | null }) => [a.netuid, a.daily]));
  const sum = (xs: number[]) => xs.reduce((a, b) => a + b, 0);
  for (const row of fleet.rows) {
    const d = daily.get(row.netuid) as number[] | null;
    assert.ok(d, `SN${row.netuid} is on the board but has no series`);
    // Same reader, bot filter and window rule as the metric: exact.
    assert.equal(sum(d.slice(-7)), row.commits7, `SN${row.netuid} 7 d`);
    assert.equal(sum(d.slice(-30)), row.commits30, `SN${row.netuid} 30 d`);
  }
});

test("mining rows come from a model-3 export", () => {
  // Only the subnt-site-honesty export writes the read block, so the
  // model-3 labels can never sit on an older fixture.
  const mining = JSON.parse(readFileSync(join(DIR, "mining.json"), "utf8")).data;
  assert.ok(mining.length > 0);
  for (const row of mining) assert.equal(typeof row.blockRef, "number", `SN${row.netuid} has no read block`);
  for (const row of mining.filter((r: { verdict: string }) => r.verdict === "possible")) {
    assert.equal(row.vramGb, null, `SN${row.netuid} shows VRAM on a no-GPU-code scan`);
  }
});

test("fixtures carry no dropped or rent-bounding field", () => {
  const text = files.map((n) => readFileSync(join(DIR, n), "utf8")).join("\n");
  assert.doesNotMatch(text, /cueKind|netTaoMonth|gateState|confidence|grossTaoMonth|priceTao|payback|requiredBand|rent/i);
});
