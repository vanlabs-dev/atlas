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

export interface ParamText {
  name: string;
  change: string;
}

export function paramText(p: ParamEvent): ParamText {
  const m = /^(\w+)(?:\[(\d+)\])?$/.exec(p.item);
  const key = m?.[1] ?? p.item;
  const sn = m?.[2] ? `SN${m[2]} ` : "";
  switch (key) {
    case "SubnetEmissionEnabled":
      return { name: `${sn}emission`, change: `switched ${onOff(p.newValue)}` };
    case "CollateralLockShare":
      return { name: `${sn}registration collateral share`, change: `${u16pct(p.prevValue)} to ${u16pct(p.newValue)}` };
    case "RootWeightSettingEnabled":
      return { name: "Root weight setting", change: `switched ${onOff(p.newValue)}` };
    case "BasketConcentrationCap":
      return { name: "Largest share one holding may reach in a fund", change: `${u16pct(p.prevValue)} to ${u16pct(p.newValue)}` };
    default:
      return { name: `${p.item} (chain parameter)`, change: `${p.prevValue ?? "-"} to ${p.newValue ?? "-"}` };
  }
}

export const BAR_MODE: Record<string, string> = {
  rank: "A fixed number of subnets, by demand share",
  "q-mass": "A share of total demand",
};

export const ROTATION: Record<string, string> = {
  entered: "Entered root weights",
  left: "Left root weights",
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
