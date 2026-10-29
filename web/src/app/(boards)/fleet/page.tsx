import type { Metadata } from "next";
import { Block, BoardShell } from "@/components/board-shell";
import { BoardHeader } from "@/components/board-header";
import { FleetTable } from "@/components/boards/fleet-table";
import { getFleet } from "@/data/fleet";
import { day } from "@/lib/format";

export const metadata: Metadata = { title: "Fleet attention" };

const TIER_CLASS: Record<string, string> = { head: "text-tier-head", mid: "text-tier-mid", quiet: "text-tier-quiet" };

const SIGNAL_WORD: Record<string, string> = {
  "econ-code": "Economics code changed",
  "narrative-cluster": "Several subnets moved together",
  "signal-digest": "Digest of smaller changes",
  watchlist: "Watchlist hit",
};

export default async function FleetPage() {
  const { generatedAt, data } = await getFleet();
  const { rows, counts, signals } = data;
  const byNetuid = new Map(rows.map((r) => [r.netuid, r]));
  const lead = rows[0];
  const finding = `${counts.diverging} subnets show code and price moving 40 points or more apart. SN${lead.netuid} ${lead.name} leads the board with a score of ${lead.score}.`;

  const kpis = [
    { label: "Code and price apart", value: counts.diverging },
    { label: "Emission route flags", value: counts.emission },
    { label: "Gone cold", value: counts.cold },
    { label: "No public repository", value: counts.invisible },
  ];

  return (
    <BoardShell>
      <BoardHeader title="Fleet attention" finding={finding} at={generatedAt} />
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_300px] lg:items-start">
        <Block title="Subnets ranked by how their code moved">
          <FleetTable rows={rows} />
        </Block>
        <div className="flex min-w-0 flex-col gap-4">
          <Block title="Across the fleet">
            <dl className="grid grid-cols-2 gap-x-4 gap-y-4">
              {kpis.map((k) => (
                <div key={k.label} className="flex flex-col-reverse">
                  <dt className="pt-1 text-small text-muted">{k.label}</dt>
                  <dd className="text-[28px] font-bold leading-none">{k.value}</dd>
                </div>
              ))}
            </dl>
          </Block>
          <Block title="All 128 slots">
            <div
              className="grid grid-cols-16 gap-[2px]"
              role="img"
              aria-label={`128 subnet slots: ${counts.invisible} without a public repository, the rest by tier as in the table`}
            >
              {Array.from({ length: 128 }, (_, i) => {
                const r = byNetuid.get(i + 1);
                return <span key={i} className={`aspect-square bg-current ${r ? TIER_CLASS[r.tier] : "text-tier-none"}`} />;
              })}
            </div>
            <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-small text-muted">
              <li className="flex items-center gap-1.5"><span className="cell text-tier-head" aria-hidden="true" />Head</li>
              <li className="flex items-center gap-1.5"><span className="cell text-tier-mid" aria-hidden="true" />Middle</li>
              <li className="flex items-center gap-1.5"><span className="cell text-tier-quiet" aria-hidden="true" />Quiet</li>
              <li className="flex items-center gap-1.5"><span className="cell text-tier-none" aria-hidden="true" />No repository</li>
            </ul>
          </Block>
          <Block title="Rotation signals">
            <ul className="text-[14px]">
              {signals.slice(0, 12).map((s, i) => (
                <li key={i} className="flex items-baseline justify-between gap-3 border-t border-border py-2" /* taste-skill-ignore: app list rule */>
                  <span>
                    {s.netuid !== null ? <span className="text-muted">SN{s.netuid} </span> : null}
                    {SIGNAL_WORD[s.class] ?? s.class}
                    {s.netuid !== null && byNetuid.get(s.netuid)?.name ? <span className="text-muted">, {byNetuid.get(s.netuid)?.name}</span> : null}
                  </span>
                  <span className="shrink-0 text-small text-muted">{day(s.createdAt)}</span>
                </li>
              ))}
            </ul>
          </Block>
        </div>
      </div>
    </BoardShell>
  );
}
