// Reading one published board from Supabase (change: supabase-data-layer).
// Pure logic only, so the node tests can load it: the cached server
// wrapper is in source.ts. Import-free of aliases.

export const BOARD_NAMES = ["mining", "fleet", "network", "upgrades"] as const;
export type BoardName = (typeof BOARD_NAMES)[number];

/** A board as stored: its produced time and its raw data. */
export interface RawBoard {
  generatedAt: string;
  data: unknown;
}

export interface StoreConfig {
  url: string;
  key: string;
}

/** Store settings from the environment, or null when not configured. */
export function storeConfig(env: Record<string, string | undefined>): StoreConfig | null {
  const url = env.SUPABASE_URL?.trim();
  const key = env.SUPABASE_PUBLISHABLE_KEY?.trim();
  return url && key ? { url: url.replace(/\/+$/, ""), key } : null;
}

/** Seconds a cached board is served before a background refresh. */
export function revalidateSeconds(env: Record<string, string | undefined>): number {
  const n = Number(env.SITEDATA_REVALIDATE_SECONDS);
  return Number.isInteger(n) && n > 0 ? n : 900;
}

type Fetch = (url: string, init: { headers: Record<string, string>; cache: "no-store" }) => Promise<{
  ok: boolean;
  status: number;
  json(): Promise<unknown>;
}>;

/** One board from the store. Throws on any failure or malformed row. */
export async function fetchBoard(name: BoardName, config: StoreConfig, fetchImpl: Fetch = fetch): Promise<RawBoard> {
  const res = await fetchImpl(`${config.url}/rest/v1/boards?name=eq.${name}&select=generated_at,data`, {
    headers: { apikey: config.key, Accept: "application/json" },
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`board ${name}: HTTP ${res.status}`);
  const rows = await res.json();
  if (!Array.isArray(rows) || rows.length !== 1) throw new Error(`board ${name}: no stored row`);
  const row = rows[0] as { generated_at?: unknown; data?: unknown };
  if (typeof row.generated_at !== "string" || Number.isNaN(Date.parse(row.generated_at))) {
    throw new Error(`board ${name}: bad generated time`);
  }
  if (!row.data || typeof row.data !== "object") throw new Error(`board ${name}: no data`);
  return { generatedAt: row.generated_at, data: row.data };
}

/**
 * Whether a failed read may fall back to the committed fixture. Only while
 * the site is being built: at run time the error must propagate, so the
 * refresh fails and Next keeps serving the last good page instead of
 * replacing it with the fixture.
 */
export function mayUseFixture(env: Record<string, string | undefined>): boolean {
  return env.NEXT_PHASE === "phase-production-build";
}
