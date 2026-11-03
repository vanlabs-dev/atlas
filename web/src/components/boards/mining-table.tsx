"use client";

import { useState } from "react";
import { FilterTabs } from "@/components/filter-tabs";
import { row, table, td, th } from "@/components/board-shell";
import type { MiningRow } from "@/data/types";
import { num, pct } from "@/lib/format";
import { codeText, reason } from "@/lib/mining";

type Filter = "all" | "possible" | "needs-gpu" | "other";

const other = (r: MiningRow) => r.verdict !== "possible" && r.verdict !== "needs-gpu";

export function MiningTable({ rows }: { rows: MiningRow[] }) {
  const [filter, setFilter] = useState<Filter>("all");
  const match = (f: Filter) => (r: MiningRow) => (f === "all" ? true : f === "other" ? other(r) : r.verdict === f);
  const count = (f: Filter) => rows.filter(match(f)).length;
  const shown = rows.filter(match(filter));

  return (
    <div className="min-w-0">
      <FilterTabs<Filter>
        label="Filter by what the code scan found"
        value={filter}
        onChange={setFilter}
        options={[
          { value: "all", label: "All", count: count("all") },
          { value: "possible", label: "No GPU code found", count: count("possible") },
          { value: "needs-gpu", label: "Needs a GPU", count: count("needs-gpu") },
          { value: "other", label: "Not readable or not scanned", count: count("other") },
        ]}
      />
      <div className="mt-6 overflow-x-auto">
        <table className={`${table} min-w-[960px]`}>
          <caption className="sr-only">Mining economics per subnet, in Atlas rank order, cut subnets last</caption>
          <thead>
            <tr>
              <th scope="col" className={`${th} text-right`}>Rank</th>
              <th scope="col" className={th}>Subnet</th>
              <th scope="col" className={th}>Code</th>
              <th scope="col" className={`${th} text-right`}>Burn</th>
              <th scope="col" className={`${th} text-right`}>Earners</th>
              <th scope="col" className={`${th} text-right`}>Top earner, excl. owner</th>
              <th scope="col" className={`${th} text-right`}>Register, TAO</th>
              <th scope="col" className={th}>Not ranked because</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((r) => (
              <tr key={r.netuid} id={`sn${r.netuid}`} className={row}>
                <td className={`${td} num text-right text-ink-3`}>{r.rank ?? "-"}</td>
                <td className={td}>
                  <span className="num mr-2.5 text-ink-3">{r.netuid}</span>
                  {r.name ?? "unnamed"}
                </td>
                <td className={`${td} ${r.verdict === "possible" ? "" : "text-ink-2"}`}>{codeText(r)}</td>
                <td className={`${td} num text-right`}>{pct(r.minerBurnPct)}</td>
                <td className={`${td} num text-right`}>{num(r.earnerCount)}</td>
                <td className={`${td} num text-right`}>{pct(r.top1SharePct)}</td>
                <td className={`${td} num text-right`}>{num(r.regCostTao, 4)}</td>
                <td className={`${td} text-ink-2`}>{reason(r) ?? "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
