import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
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
  assert.doesNotMatch(text, /cueKind|netTaoMonth|gateState|confidence|grossTaoMonth|priceTao|payback|requiredBand/i);
  // Rent as a field or word ("rent", "net_rent", "rentBand", "netRent"), not inside
  // words in public commit titles ("parents", "current").
  assert.doesNotMatch(text, /(?<![a-z])rent|Rent|RENT/);
});
