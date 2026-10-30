"use client";

import { useState } from "react";
import { FilterTabs } from "@/components/filter-tabs";
import { row, table, td, th } from "@/components/board-shell";
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
    <div className="min-w-0">
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
      <div className="mt-6 overflow-x-auto">
        <table className={`${table} min-w-[880px]`}>
          <caption className="sr-only">Mining economics per subnet, highest gross first</caption>
          <thead>
            <tr>
              <th scope="col" className={th}>Subnet</th>
              <th scope="col" className={th}>Code</th>
              <th scope="col" className={`${th} text-right`}>Burn</th>
              <th scope="col" className={`${th} text-right`}>Earners</th>
              <th scope="col" className={`${th} text-right`}>Top earner</th>
              <th scope="col" className={`${th} text-right`}>Register, TAO</th>
              <th scope="col" className={`${th} text-right`}>Gross, TAO/mo</th>
              <th scope="col" className={th}>Caveat</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((r) => (
              <tr key={r.netuid} id={`sn${r.netuid}`} className={row}>
                <td className={td}>
                  <span className="num mr-2.5 text-ink-3">{r.netuid}</span>
                  {r.name ?? "unnamed"}
                </td>
                <td className={`${td} ${r.verdict === "possible" ? "" : "text-ink-2"}`}>
                  {verdict(r.verdict)}
                  {r.gpuFloor ? <span className="text-ink-3">, {r.gpuFloor.replace(/\s*\(.*\)$/, "")}</span> : null}
                </td>
                <td className={`${td} num text-right`}>{num(r.minerBurnPct, 1)}%</td>
                <td className={`${td} num text-right`}>{num(r.earnerCount)}</td>
                <td className={`${td} num text-right`}>{r.top1SharePct === null ? "-" : `${num(r.top1SharePct, 1)}%`}</td>
                <td className={`${td} num text-right`}>{num(r.regCostTao, 4)}</td>
                <td className={`${td} num text-right`}>{num(r.grossTaoMonth, 1)}</td>
                <td className={`${td} text-ink-2`}>{r.cutReason ? (CAVEAT[r.cutReason] ?? r.cutReason) : "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
