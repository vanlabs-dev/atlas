// The field set each page may receive. The data layer projects every
// fixture record through these lists, so a key a fixture still carries
// (from an older export) never reaches the HTML or the client payload.
// Each list must name every field of its type: the checks below fail the
// typecheck when a type gains a field the list does not carry.

import type {
  FleetCounts,
  FleetRow,
  Gate,
  MiningRow,
  ParamEvent,
  RotationEvent,
  SignalEvent,
  SpecUpgrade,
  SubnetActivity,
  UpgradeJob,
  Vitals,
} from "./types.ts";

type Missing<T, K extends readonly (keyof T)[]> = Exclude<keyof T, K[number]>;

const keys =
  <T>() =>
  <const K extends readonly (keyof T)[]>(k: K & ([Missing<T, K>] extends [never] ? unknown : { missing: Missing<T, K> })) =>
    k as K;

export const FIELDS = {
  mining: keys<MiningRow>()([
    "netuid", "name", "rank", "verdict", "gpuFloor", "vramGb", "gpuMentionFiles", "cutReason",
    "unratedReason", "minerBurnPct", "earnerCount", "top1SharePct", "top10SharePct", "regCostTao",
    "grossTaoMonth", "priceTao", "blockRef",
  ]),
  fleet: keys<FleetRow>()([
    "netuid", "name", "tier", "score", "why", "divergence", "cold", "commits7", "commits30",
    "authors30", "daysSinceCommit", "momentum7d", "momentum30d", "activityClass", "emissionOpaque",
  ]),
  fleetCounts: keys<FleetCounts>()(["diverging", "emission", "cold", "quiet", "invisible"]),
  signal: keys<SignalEvent>()(["class", "tier", "netuid", "createdAt"]),
  activity: keys<SubnetActivity>()(["netuid", "daily"]),
  vitals: keys<Vitals>()([
    "date", "totalStakedTao", "rootStakeTao", "subnetsSharePct", "regCostTao", "totalAccounts",
    "newAccountsToday", "taoUsd",
  ]),
  gate: keys<Gate>()(["observedAt", "active", "theta", "aboveCount", "barMode"]),
  rotation: keys<RotationEvent>()(["observedAt", "netuid", "direction", "newShare", "validatorCount"]),
  param: keys<ParamEvent>()(["item", "prevValue", "newValue", "observedAt", "block"]),
  upgrade: keys<SpecUpgrade>()(["observedAt", "prevSpec", "newSpec", "block", "source"]),
  upgradeJob: keys<UpgradeJob>()(["spec", "status"]),
};

/** Copy only the listed fields; a missing one becomes null. */
export function only<T>(fields: readonly (keyof T)[], record: unknown): T {
  const src = (record ?? {}) as Record<string, unknown>;
  const out: Record<string, unknown> = {};
  for (const f of fields) {
    const k = f as string;
    out[k] = src[k] ?? null;
  }
  return out as T;
}

export function onlyAll<T>(fields: readonly (keyof T)[], list: unknown): T[] {
  return Array.isArray(list) ? list.map((r) => only<T>(fields, r)) : [];
}

/** Signal classes the site names. Anything else, and every shadow tier, is dropped. */
export const PUBLIC_SIGNAL_CLASSES: ReadonlySet<string> = new Set([
  "econ-code",
  "narrative-cluster",
  "signal-digest",
]);

export function publicSignals(list: SignalEvent[]): SignalEvent[] {
  return list.filter((s) => PUBLIC_SIGNAL_CLASSES.has(s.class) && s.tier !== "shadow");
}
