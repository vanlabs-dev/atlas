"use client";

import { useState } from "react";
import { FilterTabs, useListTop } from "@/components/filter-tabs";
import { row, table, td, th } from "@/components/board-shell";
import type { MiningRow } from "@/data/types";
import { num, pct } from "@/lib/format";
import { codeText, inMiningFilter, MINING_FILTERS, reason, standing, type MiningFilter } from "@/lib/mining";

export function MiningTable({ rows }: { rows: MiningRow[] }) {
  const [filter, setFilter] = useState<MiningFilter>("all");
  const [top, resetTop] = useListTop<HTMLDivElement>();
  const shown = rows.filter(inMiningFilter(filter));

  return (
    <div ref={top} className="min-w-0" data-filter={filter}>
      <FilterTabs<MiningFilter>
        label="Filter by what the code scan found"
        value={filter}
        onChange={(f) => {
          setFilter(f);
          resetTop();
        }}
        options={MINING_FILTERS.map((f) => ({ ...f, count: rows.filter(inMiningFilter(f.value)).length }))}
      />
      <div className="mt-6 overflow-x-auto max-sm:mt-0 max-sm:overflow-visible">
        <table className={`${table} rowlist mining sm:min-w-[960px]`} role="table">
          <caption className="sr-only">Mining economics per subnet, in Atlas rank order, cut subnets last</caption>
          <thead role="rowgroup">
            <tr role="row">
              <th role="columnheader" scope="col" className={`${th} text-right`}>Rank</th>
              <th role="columnheader" scope="col" className={th}>Subnet</th>
              <th role="columnheader" scope="col" className={th}>Code</th>
              <th role="columnheader" scope="col" className={`${th} text-right`}>Burn</th>
              <th role="columnheader" scope="col" className={`${th} text-right`}>Earners</th>
              <th role="columnheader" scope="col" className={`${th} text-right`}>Top earner, excl. owner</th>
              <th role="columnheader" scope="col" className={`${th} text-right`}>Register, TAO</th>
              <th role="columnheader" scope="col" className={th}>Not ranked because</th>
            </tr>
          </thead>
          <tbody role="rowgroup">
            {shown.map((r) => {
              const why = reason(r);
              return (
                <tr key={r.netuid} id={`sn${r.netuid}`} role="row" className={row} data-standing={standing(r)}>
                  <td role="cell" data-cell="rank" className={`${td} num text-right text-ink-3`}>{r.rank ?? "-"}</td>
                  <td role="cell" data-cell="subnet" className={td}>
                    <span className="num mr-2.5 text-ink-3">{r.netuid}</span>
                    {r.name ?? "unnamed"}
                  </td>
                  <td role="cell" data-cell="words" className={`${td} ${r.verdict === "possible" ? "" : "text-ink-2"}`}>{codeText(r)}</td>
                  <td role="cell" data-cell="fig" data-label="Burn" className={`${td} num text-right`}>{pct(r.minerBurnPct)}</td>
                  <td role="cell" data-cell="fig" data-label="Earners" className={`${td} num text-right`}>{num(r.earnerCount)}</td>
                  <td role="cell" data-cell="fig" data-label="Top, excl. owner" className={`${td} num text-right`}>{pct(r.top1SharePct)}</td>
                  <td role="cell" data-cell="fig" data-label="Register, TAO" className={`${td} num text-right`}>{num(r.regCostTao, 4)}</td>
                  <td role="cell" data-cell="note" data-label="Not ranked:" data-empty={why ? undefined : ""} className={`${td} text-ink-2`}>{why ?? "-"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
