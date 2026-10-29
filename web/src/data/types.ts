// Shapes of the four boards. Fields mirror the Atlas stores they come
// from; the export allowlist in scripts/allowlist.ts names the same fields.
// Every record is subnet-level. Nothing here describes the owner.

/** ISO 8601 UTC timestamp. */
export type Iso = string;

export interface Board<T> {
  /** When Atlas produced the data, not when the site was built. */
  generatedAt: Iso;
  data: T;
}

// Mining triage: chain economics per subnet plus the code-feasibility scan.
export interface MiningRow {
  netuid: number;
  name: string | null;
  rank: number | null;
  gateState: string | null;
  verdict: "possible" | "needs-gpu" | "unknown" | null;
  gpuFloor: string | null;
  vramGb: number | null;
  cutReason: string | null;
  confidence: string | null;
  minerBurnPct: number | null;
  earnerCount: number | null;
  top1SharePct: number | null;
  top10SharePct: number | null;
  regCostTao: number | null;
  grossTaoMonth: number | null;
  netTaoMonth: number | null;
  priceTao: number | null;
}

// Fleet attention: the ranked rotation board built from repository activity.
export type FleetTier = "head" | "mid" | "quiet";

export interface FleetRow {
  netuid: number;
  name: string | null;
  tier: FleetTier;
  score: number;
  why: string | null;
  cueKind: string | null;
  divergence: number | null;
  cold: boolean;
  commits7: number | null;
  commits30: number | null;
  authors30: number | null;
  daysSinceCommit: number | null;
  momentum7d: number | null;
  momentum30d: number | null;
  quadrant: string | null;
  activityClass: string | null;
  emissionOpaque: boolean;
}

export interface FleetCounts {
  diverging: number;
  emission: number;
  cold: number;
  quiet: number;
  invisible: number;
}

/** A rotation signal Atlas raised about a subnet's code. */
export interface SignalEvent {
  class: string;
  tier: string;
  netuid: number | null;
  createdAt: Iso;
}

export interface Fleet {
  rows: FleetRow[];
  counts: FleetCounts;
  signals: SignalEvent[];
}

// Network pulse: daily vitals, the emission gate, root rotation, chain params.
export interface Vitals {
  date: string;
  totalStakedTao: number | null;
  rootStakeTao: number | null;
  subnetsSharePct: number | null;
  regCostTao: number | null;
  totalAccounts: number | null;
  newAccountsToday: number | null;
  taoUsd: number | null;
}

export interface Gate {
  observedAt: Iso;
  active: boolean;
  theta: number | null;
  aboveCount: number | null;
  barMode: string | null;
}

export interface RotationEvent {
  observedAt: Iso;
  netuid: number;
  direction: string;
  newShare: number | null;
  validatorCount: number | null;
}

export interface ParamEvent {
  item: string;
  prevValue: string | null;
  newValue: string | null;
  observedAt: Iso;
  block: number | null;
}

export interface Network {
  vitals: Vitals[];
  gate: Gate | null;
  rotations: RotationEvent[];
  params: ParamEvent[];
}

// Runtime-upgrade timeline: each spec bump and the upgrade job's last state.
export interface SpecUpgrade {
  observedAt: Iso;
  prevSpec: number | null;
  newSpec: number;
  block: number | null;
  source: string | null;
}

export interface UpgradeJob {
  spec: number | null;
  status: string | null;
}

export interface Upgrades {
  events: SpecUpgrade[];
  job: UpgradeJob | null;
}
