// Plain words for the network board. Item names and units follow the
// Atlas chain readers (livedata/atlas_live.py): u16 shares are 65535 =
// 100%. An item the site has no wording for keeps its chain name, marked
// as such. Import-free of aliases so the node tests can load it.

import type { ParamEvent } from "../data/types.ts";

const U16_MAX = 65535;

const onOff = (v: string | null) => (v === "true" ? "on" : v === "false" ? "off" : (v ?? "-"));
const u16pct = (v: string | null) => {
  const n = v === null ? NaN : Number(v);
  return Number.isFinite(n) ? `${((100 * n) / U16_MAX).toFixed(1)}%` : (v ?? "-");
};

const dayOf = (iso: string) => new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });

/** One setting in words: its label, a short state for history, and what the latest value means. */
interface Wording {
  setting: string;
  state: (v: string | null) => string;
  means: (p: ParamEvent) => string;
}

const WORDING: Record<string, Wording> = {
  SubnetEmissionEnabled: {
    setting: "TAO injection",
    state: onOff,
    means: (p) => (p.newValue === "false" ? "Off: the chain adds no TAO to the pool. Alpha still flows." : "On: the chain adds TAO to the pool."),
  },
  CollateralLockShare: {
    setting: "Registration collateral",
    state: u16pct,
    means: (p) =>
      Number(p.newValue) === 0
        ? `0%: the whole registration price is burned again (was ${u16pct(p.prevValue)}).`
        : `${u16pct(p.newValue)} of a miner's registration price is now locked, not burned (was ${u16pct(p.prevValue)}).`,
  },
  RootWeightSettingEnabled: {
    setting: "Root weight setting",
    state: onOff,
    means: (p) => (p.newValue === "false" ? "Off: validators can no longer set root weights." : "On: validators can set root weights."),
  },
  BasketConcentrationCap: {
    setting: "Fund holding cap",
    state: u16pct,
    means: (p) => `${u16pct(p.prevValue)} to ${u16pct(p.newValue)}: the largest share one holding may reach in a fund buy.`,
  },
};

export interface ParamRow {
  /** The subnet the setting belongs to, or null for a network-wide setting. */
  netuid: number | null;
  setting: string;
  means: string;
  /** "5 changes since 27 Sept: off, on, off, on, off", or null for a single change. */
  history: string | null;
  observedAt: string;
}

/** One row per setting, newest change first. Events arrive newest first. */
export function paramRows(events: ParamEvent[]): ParamRow[] {
  const groups = new Map<string, ParamEvent[]>();
  for (const e of events) groups.set(e.item, [...(groups.get(e.item) ?? []), e]);
  return [...groups.entries()].map(([item, evs]) => {
    const latest = evs[0];
    const m = /^(\w+)(?:\[(\d+)\])?$/.exec(item);
    const key = m?.[1] ?? item;
    const w: Wording = WORDING[key] ?? {
      setting: `${key} (chain parameter)`,
      state: (v) => v ?? "-",
      means: (p) => `${p.prevValue ?? "-"} to ${p.newValue ?? "-"}`,
    };
    const oldest = evs[evs.length - 1];
    const states = [...evs].reverse().map((e) => w.state(e.newValue));
    return {
      netuid: m?.[2] ? Number(m[2]) : null,
      setting: w.setting,
      means: w.means(latest),
      history: evs.length > 1 ? `${evs.length} changes since ${dayOf(oldest.observedAt)}: ${states.join(", ")}` : null,
      observedAt: latest.observedAt,
    };
  });
}

export const BAR_MODE: Record<string, string> = {
  rank: "A fixed number of subnets, by demand share",
  "q-mass": "A share of total demand",
};

/** "45 readings over 53 days": the chart is not daily when days are missing. */
export function seriesTitle(dates: string[]): string {
  if (!dates.length) return "no readings";
  const span = Math.round((Date.parse(dates[dates.length - 1]) - Date.parse(dates[0])) / 864e5) + 1;
  return dates.length === span ? `daily, ${span} days` : `${dates.length} readings over ${span} days`;
}

/** Whole dollars: the export keeps four significant digits, not cents. */
export function usd(v: number | null): string {
  return v === null || !Number.isFinite(v) ? "-" : `$${Math.round(v).toLocaleString("en-GB")}`;
}

export const CROSSING: Record<string, string> = {
  "rose-above": "Rose above the bar",
  "fell-below": "Fell below the bar",
};

export interface Mover {
  netuid: number;
  then: number;
  now: number;
  /** Percentage points, now minus then. */
  change: number;
}

/** The n subnets whose emission share rose most and fell most. Zero changes are left out. */
export function emissionMovers(rows: { netuid: number; pct: number | null; pctThen: number | null }[], n: number): { up: Mover[]; down: Mover[] } {
  const all = rows
    .filter((r) => r.pct !== null && r.pctThen !== null)
    .map((r) => ({ netuid: r.netuid, then: r.pctThen as number, now: r.pct as number, change: (r.pct as number) - (r.pctThen as number) }));
  return {
    up: all.filter((m) => m.change > 0).sort((a, b) => b.change - a.change).slice(0, n),
    down: all.filter((m) => m.change < 0).sort((a, b) => a.change - b.change).slice(0, n),
  };
}
