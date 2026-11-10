import { test } from "node:test";
import assert from "node:assert/strict";
import { fetchBoard, mayUseFixture, revalidateSeconds, storeConfig } from "../src/data/source-core.ts";

const config = { url: "https://example.supabase.co", key: "sb_publishable_test" };

type Call = { url: string; headers: Record<string, string> };
function fake(status: number, body: unknown, calls: Call[] = []) {
  return async (url: string, init: { headers: Record<string, string> }) => {
    calls.push({ url, headers: init.headers });
    return { ok: status >= 200 && status < 300, status, json: async () => body };
  };
}

test("no store settings means the fixture path", () => {
  assert.equal(storeConfig({}), null);
  assert.equal(storeConfig({ SUPABASE_URL: "https://x.supabase.co" }), null);
  assert.deepEqual(storeConfig({ SUPABASE_URL: "https://x.supabase.co/", SUPABASE_PUBLISHABLE_KEY: " k " }), {
    url: "https://x.supabase.co",
    key: "k",
  });
});

test("a stored board is read with the publishable key", async () => {
  const calls: Call[] = [];
  const board = await fetchBoard(
    "network",
    config,
    fake(200, [{ generated_at: "2026-11-10T01:18:12+00:00", data: { vitals: [] } }], calls),
  );
  assert.deepEqual(board, { generatedAt: "2026-11-10T01:18:12+00:00", data: { vitals: [] } });
  assert.equal(calls[0].url, "https://example.supabase.co/rest/v1/boards?name=eq.network&select=generated_at,data");
  assert.equal(calls[0].headers.apikey, "sb_publishable_test");
});

test("any failed or malformed read throws", async () => {
  await assert.rejects(fetchBoard("mining", config, fake(503, {})), /HTTP 503/);
  await assert.rejects(fetchBoard("mining", config, fake(200, [])), /no stored row/);
  await assert.rejects(fetchBoard("mining", config, fake(200, [{ generated_at: "nope", data: {} }])), /bad generated time/);
  await assert.rejects(fetchBoard("mining", config, fake(200, [{ generated_at: "2026-11-10T00:00:00Z", data: null }])), /no data/);
  const down = async () => {
    throw new TypeError("fetch failed");
  };
  await assert.rejects(fetchBoard("mining", config, down), /fetch failed/);
});

test("the fixture stands in for a failed read only while building", () => {
  assert.equal(mayUseFixture({ NEXT_PHASE: "phase-production-build" }), true);
  assert.equal(mayUseFixture({ NEXT_PHASE: "phase-production-server" }), false);
  assert.equal(mayUseFixture({}), false);
});

test("boards refresh every 15 minutes unless overridden", () => {
  assert.equal(revalidateSeconds({}), 900);
  assert.equal(revalidateSeconds({ SITEDATA_REVALIDATE_SECONDS: "30" }), 30);
  assert.equal(revalidateSeconds({ SITEDATA_REVALIDATE_SECONDS: "-1" }), 900);
});
