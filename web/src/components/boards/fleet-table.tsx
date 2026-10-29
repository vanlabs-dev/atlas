"use client";

import { useState } from "react";
import { FilterTabs } from "@/components/filter-tabs";
import { td, th } from "@/components/board-shell";
import type { FleetRow, FleetTier } from "@/data/types";
import { num, signed } from "@/lib/format";

type Filter = FleetTier | "all";

const WHY: Record<string, string> = {
  emission: "Emission route changed",
  divergence: "Code and price apart",
  abandon: "Code gone quiet",
};

export function FleetTable({ rows }: { rows: FleetRow[] }) {
  const [filter, setFilter] = useState<Filter>("head");
  const count = (f: Filter) => (f === "all" ? rows.length : rows.filter((r) => r.tier === f).length);
  const shown = filter === "all" ? rows : rows.filter((r) => r.tier === filter);

  return (
    <>
      <FilterTabs<Filter>
        label="Filter by tier"
        value={filter}
        onChange={setFilter}
        options={[
          { value: "head", label: "Head", count: count("head") },
          { value: "mid", label: "Middle", count: count("mid") },
          { value: "quiet", label: "Quiet", count: count("quiet") },
          { value: "all", label: "All", count: count("all") },
        ]}
      />
      <div className="mt-4 overflow-x-auto">
        <table className="w-full min-w-[860px] text-[14px]">
          <caption className="sr-only">Subnets ranked by fleet score</caption>
          <thead>
            <tr>
              <th className={`${th} text-left`}>Subnet</th>
              <th className={`${th} text-right`}>Score</th>
              <th className={`${th} pl-4 text-left`}>Why</th>
              <th className={`${th} text-right`}>Code against price</th>
              <th className={`${th} text-right`}>Commits, 7 d</th>
              <th className={`${th} text-right`}>Commits, 30 d</th>
              <th className={`${th} text-right`}>Authors, 30 d</th>
              <th className={`${th} text-right`}>Price, 30 d</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((r) => (
              <tr key={r.netuid} id={`sn${r.netuid}`} className="target:bg-surface">
                <td className={`${td} pr-4`}>
                  <span className="text-muted">SN{r.netuid}</span> {r.name ?? "unnamed"}
                </td>
                <td className={`${td} text-right`}>{r.score}</td>
                <td className={`${td} pl-4 text-muted`}>{r.why ? (WHY[r.why] ?? r.why) : "-"}</td>
                <td className={`${td} text-right`}>{signed(r.divergence)}</td>
                <td className={`${td} text-right`}>{num(r.commits7)}</td>
                <td className={`${td} text-right`}>{num(r.commits30)}</td>
                <td className={`${td} text-right`}>{num(r.authors30)}</td>
                <td className={`${td} text-right`}>{signed(r.momentum30d, 1, "%")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
