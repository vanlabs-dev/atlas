import { test } from "node:test";
import assert from "node:assert/strict";
import { freshness } from "../src/data/freshness.ts";

const at = "2026-10-01T00:00:00Z";
const hoursLater = (h: number) => new Date(Date.parse(at) + h * 3_600_000);

test("fresh under 48 hours", () => {
  const f = freshness(at, hoursLater(47));
  assert.equal(f.stale, false);
  assert.equal(f.label, "47 h ago");
});

test("stale past 48 hours", () => {
  const f = freshness(at, hoursLater(49));
  assert.equal(f.stale, true);
  assert.equal(f.label, "2 days ago");
});

test("future timestamps read as now", () => {
  assert.equal(freshness(at, hoursLater(-2)).label, "under an hour ago");
});
