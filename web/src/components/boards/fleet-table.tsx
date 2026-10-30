"use client";

import { useEffect, useState, useSyncExternalStore } from "react";
import { FilterTabs } from "@/components/filter-tabs";
import { row, table, td, th } from "@/components/board-shell";
import { Lane } from "@/components/lane";
import type { FleetRow, FleetTier, SubnetActivity } from "@/data/types";
import { num, polarity, signed } from "@/lib/format";
import { WHY } from "@/lib/words";

type Filter = FleetTier | "all";

const subscribeHash = (cb: () => void) => {
  window.addEventListener("hashchange", cb);
  return () => window.removeEventListener("hashchange", cb);
};

export function FleetTable({ rows, activity }: { rows: FleetRow[]; activity: SubnetActivity[] }) {
  // A link such as /fleet#sn20 opens the tab that holds that subnet's row.
  const hash = useSyncExternalStore(subscribeHash, () => window.location.hash, () => "");
  const target = rows.find((r) => `#sn${r.netuid}` === hash);
  const [chosen, setChosen] = useState<Filter | null>(null);
  const filter: Filter = chosen ?? target?.tier ?? "head";
  const daily = new Map(activity.map((a) => [a.netuid, a.daily]));

  useEffect(() => {
    if (target) document.getElementById(`sn${target.netuid}`)?.scrollIntoView({ block: "center" });
  }, [target]);
  const count = (f: Filter) => (f === "all" ? rows.length : rows.filter((r) => r.tier === f).length);
  const shown = filter === "all" ? rows : rows.filter((r) => r.tier === filter);

  return (
    <div className="min-w-0">
      <FilterTabs<Filter>
        label="Filter by tier"
        value={filter}
        onChange={setChosen}
        options={[
          { value: "head", label: "Head", count: count("head") },
          { value: "mid", label: "Middle", count: count("mid") },
          { value: "quiet", label: "Quiet", count: count("quiet") },
          { value: "all", label: "All", count: count("all") },
        ]}
      />
      <div className="mt-6 overflow-x-auto">
        <table className={`${table} min-w-[760px]`}>
          <caption className="sr-only">Subnets ranked by fleet score</caption>
          <thead>
            <tr>
              <th scope="col" className={th}>Subnet</th>
              <th scope="col" className={`${th} text-right`}>Score</th>
              <th scope="col" className={th}>Why it ranks</th>
              <th scope="col" className={`${th} text-right`}>Code against price</th>
              <th scope="col" className={`${th} text-right`}>Commits, 30 d</th>
              <th scope="col" className={`${th} text-right`}>Price, 30 d</th>
              <th scope="col" className={`${th} text-right`}>Last 30 days</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((r) => (
              <tr key={r.netuid} id={`sn${r.netuid}`} className={row}>
                <td className={td}>
                  <span className="num mr-2.5 text-ink-3">{r.netuid}</span>
                  {r.name ?? "unnamed"}
                </td>
                <td className={`${td} num text-right`}>{r.score}</td>
                <td className={`${td} min-w-[11rem] text-ink-2`}>{r.why ? (WHY[r.why] ?? r.why) : "-"}</td>
                <td className={`${td} num text-right`}>{signed(r.divergence)}</td>
                <td className={`${td} num text-right`}>{num(r.commits30)}</td>
                <td className={`${td} num text-right ${polarity(r.momentum30d)}`}>
                  {signed(r.momentum30d, 1, "%")}
                </td>
                <td className={td}>
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
