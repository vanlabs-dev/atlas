import type { Metadata } from "next";
import { Block, BoardShell, td, th } from "@/components/board-shell";
import { BoardHeader } from "@/components/board-header";
import { getUpgrades } from "@/data/upgrades";
import { day, num } from "@/lib/format";

export const metadata: Metadata = { title: "Runtime upgrades" };

const DAY_MS = 86_400_000;

export default async function UpgradesPage() {
  const { generatedAt, data } = await getUpgrades();
  const events = data.events;
  const first = events[0];
  const last = events[events.length - 1];
  const t0 = Date.parse(first.observedAt);
  const t1 = Date.parse(last.observedAt);
  const spanDays = (t1 - t0) / DAY_MS;
  const gaps = events.slice(1).map((e, i) => (Date.parse(e.observedAt) - Date.parse(events[i].observedAt)) / DAY_MS);
  const mean = gaps.reduce((a, b) => a + b, 0) / gaps.length;
  const longest = Math.max(...gaps);
  const finding = `${events.length} runtime upgrades in ${Math.round(spanDays)} days, one every ${num(mean, 1)} days on average. The latest is spec ${last.newSpec}, on ${day(last.observedAt)}.`;

  const rows = events
    .map((e, i) => ({ ...e, gap: i === 0 ? null : gaps[i - 1] }))
    .reverse();

  return (
    <BoardShell>
      <BoardHeader title="Runtime upgrades" finding={finding} at={generatedAt} />
      <div className="grid gap-4">
        <Block title={`Every spec upgrade, ${day(first.observedAt)} to ${day(last.observedAt)}`}>
          <svg viewBox="0 0 1000 64" className="w-full" role="img" aria-label={`${events.length} upgrades on a time line from ${day(first.observedAt)} to ${day(last.observedAt)}`}>
            <line x1={0} x2={1000} y1={32} y2={32} stroke="currentColor" strokeOpacity={0.2} />
            {events.map((e) => {
              const x = ((Date.parse(e.observedAt) - t0) / (t1 - t0)) * 992 + 4;
              return <rect key={e.newSpec} x={x - 4} y={22} width={8} height={20} className="fill-ink" />;
            })}
          </svg>
          <p className="mt-2 flex justify-between text-small text-muted">
            <span>{day(first.observedAt)}</span>
            <span>Longest quiet stretch: {num(longest, 1)} days</span>
            <span>{day(last.observedAt)}</span>
          </p>
        </Block>

        <Block title="Upgrades, newest first">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[560px] text-[14px]">
              <caption className="sr-only">Runtime spec upgrades seen by Atlas</caption>
              <thead>
                <tr>
                  <th className={`${th} text-left`}>Spec</th>
                  <th className={`${th} text-left`}>Seen</th>
                  <th className={`${th} text-right`}>Days since the one before</th>
                  <th className={`${th} text-right`}>Block</th>
                  <th className={`${th} pl-4 text-left`}>Read by</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((e) => (
                  <tr key={e.newSpec}>
                    <td className={`${td} pr-4`}>
                      <span className="text-muted">{e.prevSpec ?? "-"} to</span> {e.newSpec}
                    </td>
                    <td className={`${td} pr-4`}>{day(e.observedAt)}</td>
                    <td className={`${td} text-right`}>{num(e.gap, 1)}</td>
                    <td className={`${td} text-right text-muted`}>{e.block === null ? "-" : e.block.toLocaleString("en-GB")}</td>
                    <td className={`${td} pl-4 text-muted`}>{e.source === "rpc" ? "Chain RPC" : (e.source ?? "-")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Block>
      </div>
    </BoardShell>
  );
}
