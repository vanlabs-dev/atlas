"use client";

import { useState } from "react";
import { FilterTabs } from "@/components/filter-tabs";
import { td, th } from "@/components/board-shell";
import type { MiningRow } from "@/data/types";
import { num, verdict } from "@/lib/format";

type Filter = "all" | "possible" | "needs-gpu" | "unknown";

const CAVEAT: Record<string, string> = {
  "owner-capture": "Owner takes most",
  "winner-take-all": "Winner takes all",
  "identity-placeholder": "No identity",
  "pool-side-switch-off": "Pool switched off",
};


export function MiningTable({ rows }: { rows: MiningRow[] }) {
  const [filter, setFilter] = useState<Filter>("all");
  const count = (f: Filter) => (f === "all" ? rows.length : rows.filter((r) => r.verdict === f).length);
  const shown = filter === "all" ? rows : rows.filter((r) => r.verdict === filter);

  return (
    <>
      <FilterTabs<Filter>
        label="Filter by what the code needs"
        value={filter}
        onChange={setFilter}
        options={[
          { value: "all", label: "All", count: count("all") },
          { value: "possible", label: "Runs on a CPU", count: count("possible") },
          { value: "needs-gpu", label: "Needs a GPU", count: count("needs-gpu") },
          { value: "unknown", label: "Not readable", count: count("unknown") },
        ]}
      />
      <div className="mt-4 overflow-x-auto">
        <table className="w-full min-w-[880px] text-[14px]">
          <caption className="sr-only">Mining economics per subnet, highest gross first</caption>
          <thead>
            <tr>
              <th className={`${th} text-left`}>Subnet</th>
              <th className={`${th} text-left`}>Code</th>
              <th className={`${th} text-right`}>Burn</th>
              <th className={`${th} text-right`}>Earners</th>
              <th className={`${th} text-right`}>Top earner</th>
              <th className={`${th} text-right`}>Register, TAO</th>
              <th className={`${th} text-right`}>Gross, TAO/mo</th>
              <th className={`${th} pl-4 text-left`}>Caveat</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((r) => (
              <tr key={r.netuid} id={`sn${r.netuid}`} className="target:bg-surface">
                <td className={`${td} pr-4`}>
                  <span className="text-muted">SN{r.netuid}</span> {r.name ?? "unnamed"}
                </td>
                <td className={`${td} pr-4 ${r.verdict === "possible" ? "" : "text-muted"}`}>
                  {verdict(r.verdict)}
                  {r.gpuFloor ? <span className="text-muted">, {r.gpuFloor.replace(/\s*\(.*\)$/, "")}</span> : null}
                </td>
                <td className={`${td} text-right`}>{num(r.minerBurnPct, 1)}%</td>
                <td className={`${td} text-right`}>{num(r.earnerCount)}</td>
                <td className={`${td} text-right`}>{r.top1SharePct === null ? "-" : `${num(r.top1SharePct, 1)}%`}</td>
                <td className={`${td} text-right`}>{num(r.regCostTao, 4)}</td>
                <td className={`${td} text-right`}>{num(r.grossTaoMonth, 1)}</td>
                <td className={`${td} pl-4 text-muted`}>{r.cutReason ? (CAVEAT[r.cutReason] ?? r.cutReason) : "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
