import type { Metadata } from "next";
import { Figures, Panel } from "@/components/board-shell";
import { BoardHeader } from "@/components/board-header";
import { FleetTable } from "@/components/boards/fleet-table";
import { getFleet } from "@/data/fleet";
import { day } from "@/lib/format";
import { SIGNAL } from "@/lib/words";

export const metadata: Metadata = { title: "Fleet attention" };

export default async function FleetPage() {
  const { generatedAt, data } = await getFleet();
  const { rows, counts, signals, activity } = data;
  const byNetuid = new Map(rows.map((r) => [r.netuid, r]));
  const lead = rows[0];
  const finding = `${counts.diverging} subnets show code and price moving 40 points or more apart. SN${lead.netuid} ${lead.name} leads the board with a score of ${lead.score}.`;

  return (
    <>
      <BoardHeader title="Fleet attention" finding={finding} at={generatedAt} />
      <div className="grid gap-12 lg:grid-cols-[4fr_8fr] lg:gap-16">
        <div className="flex min-w-0 flex-col gap-12">
          <Figures
            items={[
              { value: counts.diverging, label: "code and price apart" },
              { value: counts.emission, label: "emission route flags" },
              { value: counts.cold, label: "gone cold this month" },
              { value: counts.invisible, label: "with no public repository, root included" },
            ]}
          />
          <Panel title="Rotation signals, newest first">
            <ul className="text-[15px]">
              {signals.slice(0, 12).map((s, i) => (
                <li key={i} className="flex items-baseline justify-between gap-3 py-1.5">
                  <span>
                    {s.netuid !== null ? <span className="num text-ink-3">{s.netuid} </span> : null}
                    {SIGNAL[s.class] ?? s.class}
                    {s.netuid !== null && byNetuid.get(s.netuid)?.name ? (
                      <span className="text-ink-2">, {byNetuid.get(s.netuid)?.name}</span>
                    ) : null}
                  </span>
                  <span className="num shrink-0 text-small text-ink-3">{day(s.createdAt)}</span>
                </li>
              ))}
            </ul>
          </Panel>
        </div>
        <FleetTable rows={rows} activity={activity} />
      </div>
    </>
  );
}
