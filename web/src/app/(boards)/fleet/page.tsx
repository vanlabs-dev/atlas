import type { Metadata } from "next";
import { Panel } from "@/components/board-shell";
import { BoardHeader } from "@/components/board-header";
import { FleetTable } from "@/components/boards/fleet-table";
import { getFleet } from "@/data/fleet";
import { day } from "@/lib/format";
import { APART_AT, COLD } from "@/lib/fleet";
import { SIGNAL } from "@/lib/words";

export const metadata: Metadata = { title: "Fleet attention" };

export default async function FleetPage() {
  const { generatedAt, readAt, data } = await getFleet();
  const { rows, counts, signals, activity } = data;
  const byNetuid = new Map(rows.map((r) => [r.netuid, r]));
  const lead = rows[0];
  const finding = lead
    ? `${counts.diverging} subnets show code and price apart: their 30-day code rank and 7-day price rank differ by ${APART_AT} places in 100 or more. SN${lead.netuid} ${lead.name ?? "(name not recorded)"} leads the board with a score of ${lead.score}.`
    : "No subnet is on the fleet board in this pass.";
  const shownSignals = signals.slice(0, 12);

  return (
    <>
      <BoardHeader title="Fleet attention" finding={finding} at={generatedAt} readAt={readAt} />
      <dl className="grid grid-cols-2 gap-x-8 gap-y-10 lg:grid-cols-4">
        {[
          { value: counts.diverging, label: "code and price apart" },
          { value: counts.emission, label: "emission route flags" },
          { value: counts.cold, label: COLD.toLowerCase() },
          { value: counts.invisible, label: "with no public repository, root included" },
        ].map((k) => (
          <div key={k.label} className="flex flex-col-reverse justify-end">
            <dt className="mt-2 max-w-[22ch] text-body text-ink-2">{k.label}</dt>
            <dd className="num font-display text-[clamp(44px,5vw,64px)] leading-[0.9]">{k.value}</dd>
          </div>
        ))}
      </dl>
      <div className="mt-[clamp(64px,8vw,104px)]">
        <FleetTable rows={rows} activity={activity} />
      </div>
      <div className="mt-[clamp(72px,9vw,120px)] grid gap-12 lg:grid-cols-[4fr_8fr] lg:gap-16">
        <section aria-labelledby="signals-title">
          <h2 id="signals-title" className="font-display text-sub leading-none">
            Rotation signals
          </h2>
          <p className="mt-4 max-w-[34ch] text-ink-2">
            What Atlas raised about subnet code, the {shownSignals.length} newest.
          </p>
        </section>
        <Panel title={`The ${shownSignals.length} newest`}>
          <ul className="grid gap-x-10 text-body md:grid-cols-2">
            {shownSignals.map((s, i) => (
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
    </>
  );
}
