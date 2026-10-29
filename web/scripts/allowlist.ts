// Field allowlist for the fixture export. Each record is built from these
// names only, so a field the stores add later cannot flow to the site.
// Map: site field -> source field. Owner-specific data (holdings, hotkeys,
// wallets, rotation decisions) is never listed. Addresses are never listed.

export const ALLOWLIST = {
  mining: {
    netuid: "netuid",
    name: "subnet_name",
    rank: "rank",
    gateState: "gate_state",
    verdict: "verdict",
    gpuFloor: "gpu_floor",
    vramGb: "vram_gb",
    cutReason: "cut_reason",
    confidence: "confidence",
    minerBurnPct: "miner_burn_pct",
    earnerCount: "earner_count",
    top1SharePct: "top1_share_pct",
    top10SharePct: "top10_share_pct",
    regCostTao: "reg_cost_tao",
    grossTaoMonth: "gross_tao_month",
    netTaoMonth: "net_tao_month",
    priceTao: "price_tao",
  },
  fleet: {
    netuid: "netuid",
    name: "name",
    tier: "tier",
    score: "score",
    why: "why",
    cueKind: "cue_kind",
    divergence: "div_signed",
    cold: "cold",
    commits7: "c7",
    commits30: "c30",
    authors30: "a30",
    daysSinceCommit: "days_since",
    momentum7d: "momentum_7d",
    momentum30d: "momentum_30d",
    activityClass: "activity_class",
    emissionOpaque: "emission_opaque",
  },
  fleetCounts: {
    diverging: "diverging",
    emission: "emission",
    cold: "cold",
    quiet: "quiet",
    invisible: "invisible",
  },
  activity: {
    netuid: "netuid",
    daily: "daily",
  },
  signal: {
    class: "class",
    tier: "tier",
    netuid: "netuid",
    createdAt: "created_at",
  },
  vitals: {
    date: "date",
    totalStakedTao: "total_staked_tao",
    rootStakeTao: "root_stake_tao",
    subnetsSharePct: "subnets_share_pct",
    regCostTao: "subnet_reg_cost_tao",
    totalAccounts: "total_accounts",
    newAccountsToday: "new_accounts_today",
    taoUsd: "tao_usd",
  },
  gate: {
    observedAt: "observed_at",
    active: "gate_active",
    theta: "theta",
    aboveCount: "above_count",
    barMode: "bar_mode",
  },
  rotation: {
    observedAt: "observed_at",
    netuid: "netuid",
    direction: "direction",
    newShare: "new_share",
    validatorCount: "validator_count",
  },
  param: {
    item: "item",
    prevValue: "prev_value",
    newValue: "new_value",
    observedAt: "observed_at",
    block: "block_number",
  },
  upgrade: {
    observedAt: "observed_at",
    prevSpec: "prev_spec",
    newSpec: "new_spec",
    block: "block_reference",
    source: "source",
  },
  upgradeJob: {
    spec: "spec",
    status: "status",
  },
} as const satisfies Record<string, Record<string, string>>;

export type Kind = keyof typeof ALLOWLIST;

type Value = string | number | boolean | null | number[];

/** Fields that hold a day series, oldest first. Every other field is scalar. */
export const SERIES: Record<string, number> = { daily: 90 };

/** Four significant digits: values are rounded, never exact live state. */
export function round(value: number): number {
  return Number.isInteger(value) ? value : Number(value.toPrecision(4));
}

function clean(value: unknown): Value {
  if (value === null || value === undefined) return null;
  if (typeof value === "number") return round(value);
  if (typeof value === "boolean") return value;
  // House style bans em dashes, and source prose carries some.
  if (typeof value === "string") return value.replace(/\u2014/g, "-");
  throw new Error(`non-scalar value ${JSON.stringify(value)}`);
}

function series(field: string, value: unknown): number[] | null {
  if (value === null || value === undefined) return null;
  const ok =
    Array.isArray(value) &&
    value.length === SERIES[field] &&
    value.every((v) => Number.isInteger(v) && v >= 0);
  if (!ok) throw new Error(`${field} must be ${SERIES[field]} non-negative integers`);
  return value as number[];
}

/** Build a record from the allowlist alone. Unlisted source fields drop. */
export function pick(kind: Kind, source: Record<string, unknown>): Record<string, Value> {
  const out: Record<string, Value> = {};
  for (const [field, from] of Object.entries(ALLOWLIST[kind])) {
    out[field] = field in SERIES ? series(field, source[from]) : clean(source[from]);
  }
  return out;
}
