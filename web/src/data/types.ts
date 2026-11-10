// Shapes of the four boards. Fields mirror the Atlas stores they come
// from; the field allowlist in sitedata/allowlist.json names the same fields.
// Every record is subnet-level. Nothing here describes the owner.

/** ISO 8601 UTC timestamp. */
export type Iso = string;

export interface Board<T> {
  /** When Atlas produced the data, not when the site was built. */
  generatedAt: Iso;
  /** When the site read this copy: from the store, or the fixture at build. */
  readAt: Iso;
  data: T;
}

// Mining triage: chain economics per subnet plus the code-feasibility scan.
export interface MiningRow {
  netuid: number;
  name: string | null;
  /** Atlas rank on the stored board; null when cut or unrated. */
  rank: number | null;
  verdict: "possible" | "needs-gpu" | "unknown" | "closed" | "stub" | null;
  gpuFloor: string | null;
  vramGb: number | null;
  /** Files in the miner code that mention a GPU, for a `possible` scan. */
  gpuMentionFiles: number | null;
  cutReason: string | null;
  unratedReason: string | null;
  minerBurnPct: number | null;
  earnerCount: number | null;
  top1SharePct: number | null;
  top10SharePct: number | null;
  regCostTao: number | null;
  /** The chain block the ranking's prices were read at. */
  blockRef: number | null;
}

// Fleet attention: the ranked rotation board built from repository activity.
export type FleetTier = "head" | "mid" | "quiet";

export interface FleetRow {
  netuid: number;
  name: string | null;
  tier: FleetTier;
  score: number;
  why: string | null;
  /** Code-activity rank minus 7-day price rank, in places. Rendered unsigned. */
  divergence: number | null;
  cold: boolean;
  commits7: number | null;
  commits30: number | null;
  authors30: number | null;
  daysSinceCommit: number | null;
  momentum7d: number | null;
  momentum30d: number | null;
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

/** Commits per day for 90 days, oldest first. Null: no clone Atlas can read. */
export interface SubnetActivity {
  netuid: number;
  daily: number[] | null;
}

export interface Fleet {
  rows: FleetRow[];
  counts: FleetCounts;
  signals: SignalEvent[];
  activity: SubnetActivity[];
}

// Network pulse: daily vitals, the emission gate, gate crossings, emission share, chain params.
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

/** A subnet's demand share crossing the emission gate bar. */
export interface GateCrossing {
  observedAt: Iso;
  netuid: number;
  /** "rose-above" or "fell-below". */
  direction: string;
  /** The subnet's demand share at the crossing, 0 to 1. */
  share: number | null;
  /** The bar at the crossing, 0 to 1. */
  theta: number | null;
  /** "reversed" when the subnet crossed back within the durability window. */
  eligibility: string | null;
}

/** A subnet's share of emission now and about 30 days earlier, in percent. */
export interface EmissionShare {
  netuid: number;
  pct: number | null;
  pctThen: number | null;
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
  crossings: GateCrossing[];
  emission: EmissionShare[];
  /** When the "then" emission reading was taken. */
  emissionSince: Iso | null;
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

/** What one chain upgrade shipped, from the subtensor repository. */
export interface Release {
  /** The chain spec it shipped as, or the repo spec when pending. */
  spec: number;
  /** Merged in the repository, not on chain yet. */
  pending: boolean;
  /** When Atlas first read code for this release. */
  since: Iso;
  /** Repo specs that never went live on their own, as "480" or "460, 461". */
  bundled: string | null;
  commits: number;
  files: number;
  adds: number;
  dels: number;
  /** A file or commit list was truncated: counts are lower bounds. */
  partial: boolean;
  headline: string | null;
  headline2: string | null;
  headline3: string | null;
  filesRuntime: number;
  filesPallets: number;
  filesEvm: number;
  filesNode: number;
  filesSdk: number;
  filesDocs: number;
  filesTooling: number;
}

export interface UpgradeJob {
  spec: number | null;
  status: string | null;
}

export interface Upgrades {
  events: SpecUpgrade[];
  releases: Release[];
  job: UpgradeJob | null;
}
