"use client";

import { useEffect, useState, useSyncExternalStore } from "react";
import { FilterTabs, useListTop } from "@/components/filter-tabs";
import { row, table, td, th } from "@/components/board-shell";
import { Lane } from "@/components/lane";
import type { FleetRow, SubnetActivity } from "@/data/types";
import { num, polarity, signed } from "@/lib/format";
import { gapPlaces, whyText } from "@/lib/fleet";
import { FLEET_FILTERS, fleetFilter, hashNetuid, inFilter, type FilterChoice, type FleetFilter } from "@/state/fleet-filter";

const subscribeHash = (cb: () => void) => {
  window.addEventListener("hashchange", cb);
  return () => window.removeEventListener("hashchange", cb);
};

export function FleetTable({ rows, activity }: { rows: FleetRow[]; activity: SubnetActivity[] }) {
  // A link such as /fleet#sn20 opens the tab that holds that subnet's row. The tab on show is
  // decided in src/state/fleet-filter.ts from the hash and the visitor's last choice: the newer wins.
  const hash = useSyncExternalStore(subscribeHash, () => window.location.hash, () => "");
  const targetN = hashNetuid(hash);
  const target = targetN === null ? undefined : rows.find((r) => r.netuid === targetN);
  const [choice, setChoice] = useState<FilterChoice | null>(null);
  const { filter, source } = fleetFilter(hash, target?.tier ?? null, choice);
  const daily = new Map(activity.map((a) => [a.netuid, a.daily]));
  const [top, resetTop] = useListTop<HTMLDivElement>();

  // The row is looked up inside this table, not by document id: Next keeps visited pages alive
  // off screen, and the mining table has rows with the same ids.
  const linked = source === "link" ? target : undefined;
  useEffect(() => {
    if (linked) top.current?.querySelector(`[data-sn="${linked.netuid}"]`)?.scrollIntoView({ block: "center" });
  }, [linked, top]);
  const shown = rows.filter(inFilter(filter));

  return (
    <div ref={top} className="min-w-0" data-filter={filter} data-filter-source={source}>
      <FilterTabs<FleetFilter>
        label="Filter by tier"
        value={filter}
        onChange={(f) => {
          setChoice({ filter: f, atHash: window.location.hash });
          resetTop();
        }}
        options={FLEET_FILTERS.map((f) => ({ ...f, count: rows.filter(inFilter(f.value)).length }))}
      />
      <div className="mt-6 overflow-x-auto max-sm:mt-0 max-sm:overflow-visible">
        <table className={`${table} rowlist fleet`} role="table">
          <caption className="sr-only">Subnets ranked by fleet score</caption>
          <thead role="rowgroup">
            <tr role="row">
              <th role="columnheader" scope="col" className={th}>Subnet</th>
              <th role="columnheader" scope="col" className={`${th} text-right`}>Score</th>
              <th role="columnheader" scope="col" className={th}>Why it ranks</th>
              <th role="columnheader" scope="col" className={`${th} text-right`}>Code vs price, places apart</th>
              <th role="columnheader" scope="col" className={`${th} text-right`}>Commits, 30 d</th>
              <th role="columnheader" scope="col" className={`${th} text-right`}>Alpha price in TAO, 7 d</th>
              <th role="columnheader" scope="col" className={`${th} text-right`}>Alpha price in TAO, 30 d</th>
              <th role="columnheader" scope="col" className={`${th} text-right`}>Last 30 days</th>
            </tr>
          </thead>
          <tbody role="rowgroup">
            {shown.map((r) => (
              <tr key={r.netuid} id={`sn${r.netuid}`} data-sn={r.netuid} data-linked={hash === `#sn${r.netuid}` ? "" : undefined} role="row" className={row}>
                <td role="cell" data-cell="subnet" className={td}>
                  <span className="num mr-2.5 text-ink-3">{r.netuid}</span>
                  {r.name ?? "unnamed"}
                </td>
                <td role="cell" data-cell="score" data-label="Score" className={`${td} num text-right`}>{r.score}</td>
                <td role="cell" data-cell="words" className={`${td} text-ink-2`}>{whyText(r.why, r.divergence)}</td>
                <td role="cell" data-cell="fig" data-label="Places apart" className={`${td} num text-right`}>{num(gapPlaces(r.divergence))}</td>
                <td role="cell" data-cell="fig" data-label="Commits 30 d" className={`${td} num text-right`}>{num(r.commits30)}</td>
                {/* The gap ranks 30-day commits against this 7-day price move, unsigned. */}
                <td role="cell" data-cell="fig" data-label="Price 7 d" className={`${td} num text-right ${polarity(r.momentum7d)}`}>
                  {signed(r.momentum7d, 1, "%")}
                </td>
                <td role="cell" data-cell="fig" data-label="Price 30 d" className={`${td} num text-right ${polarity(r.momentum30d)}`}>
                  {signed(r.momentum30d, 1, "%")}
                </td>
                <td role="cell" data-cell="lane" className={td}>
                  <Lane daily={daily.get(r.netuid) ?? null} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
