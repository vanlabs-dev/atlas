import type { Metadata } from "next";
import { Figures, Panel, row, table, td, th } from "@/components/board-shell";
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
    <>
      <BoardHeader title="Runtime upgrades" finding={finding} at={generatedAt} />
      <Panel title={`Every spec upgrade, ${day(first.observedAt)} to ${day(last.observedAt)}`}>
        <svg
          viewBox="0 0 1000 64"
          className="w-full"
          role="img"
          aria-label={`${events.length} upgrades on a time line from ${day(first.observedAt)} to ${day(last.observedAt)}`}
        >
          <line x1={0} x2={1000} y1={32} y2={32} className="stroke-rule" />
          {events.map((e) => {
            const x = ((Date.parse(e.observedAt) - t0) / (t1 - t0)) * 992 + 4;
            return <rect key={e.newSpec} x={x - 1.5} y={16} width={3} height={32} className="fill-accent" />;
          })}
        </svg>
        <p className="num mt-3 flex justify-between text-small text-ink-3">
          <span>{day(first.observedAt)}</span>
          <span>{day(last.observedAt)}</span>
        </p>
      </Panel>

      <div className="mt-[clamp(72px,9vw,120px)] grid gap-12 lg:grid-cols-[4fr_8fr] lg:gap-16">
        <Figures
          items={[
            { value: events.length, label: `upgrades in ${Math.round(spanDays)} days` },
            { value: num(mean, 1), label: "days between upgrades, on average" },
            { value: num(longest, 1), label: "days in the longest quiet stretch" },
          ]}
        />
        <div className="min-w-0 overflow-x-auto">
          <table className={`${table} min-w-[560px]`}>
            <caption className="sr-only">Runtime spec upgrades seen by Atlas, newest first</caption>
            <thead>
              <tr>
                <th scope="col" className={th}>Spec</th>
                <th scope="col" className={th}>Seen</th>
                <th scope="col" className={`${th} text-right`}>Days since the one before</th>
                <th scope="col" className={`${th} text-right`}>Block</th>
                <th scope="col" className={th}>Read by</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((e) => (
                <tr key={e.newSpec} className={row}>
                  <td className={`${td} num`}>
                    <span className="text-ink-3">{e.prevSpec ?? "-"} to</span> {e.newSpec}
                  </td>
                  <td className={`${td} num`}>{day(e.observedAt)}</td>
                  <td className={`${td} num text-right`}>{num(e.gap, 1)}</td>
                  <td className={`${td} num text-right text-ink-2`}>{e.block === null ? "-" : e.block.toLocaleString("en-GB")}</td>
                  <td className={`${td} text-ink-2`}>{e.source === "rpc" ? "Chain RPC" : (e.source ?? "-")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
