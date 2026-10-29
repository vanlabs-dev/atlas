import type { Metadata } from "next";
import { Block, BoardShell, td, th } from "@/components/board-shell";
import { BoardHeader } from "@/components/board-header";
import { BarChart } from "@/components/boards/bar-chart";
import { getNetwork } from "@/data/network";
import { day, num, signed } from "@/lib/format";

export const metadata: Metadata = { title: "Network pulse" };

export default async function NetworkPage() {
  const { generatedAt, data } = await getNetwork();
  const { vitals, gate, rotations, params } = data;
  const first = vitals[0];
  const last = vitals[vitals.length - 1];
  const since = day(first.date);
  const delta = (a: number | null, b: number | null) => (a === null || b === null ? null : b - a);
  const shareChange = delta(first.subnetsSharePct, last.subnetsSharePct);

  const finding = `Subnets hold ${num(last.subnetsSharePct, 2)}% of all staked TAO, ${signed(shareChange, 2, " points")} since ${since}. The emission gate is ${gate?.active ? "on" : "off"}, with ${num(gate?.aboveCount ?? null)} subnets above the bar.`;

  const kpis = [
    { label: "Staked TAO", value: num(last.totalStakedTao), change: signed(delta(first.totalStakedTao, last.totalStakedTao)) },
    { label: "In subnets", value: `${num(last.subnetsSharePct, 2)}%`, change: signed(shareChange, 2, " pt") },
    { label: "Subnet registration, TAO", value: num(last.regCostTao, 1), change: signed(delta(first.regCostTao, last.regCostTao), 1) },
    { label: "TAO in USD", value: last.taoUsd === null ? "-" : `$${last.taoUsd.toFixed(2)}`, change: signed(delta(first.taoUsd, last.taoUsd), 2) },
  ];

  return (
    <BoardShell>
      <BoardHeader title="Network pulse" finding={finding} at={generatedAt} />
      <div className="grid gap-4">
        <section aria-label="Chain vitals" className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          {kpis.map((k) => (
            <div key={k.label} className="bg-card p-5">
              <h2 className="text-small text-muted">{k.label}</h2>
              <p className="pt-2 text-[28px] font-bold leading-none">{k.value}</p>
              <p className="pt-2 text-small text-muted">
                {k.change} since {since}
              </p>
            </div>
          ))}
        </section>

        <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
          <Block title={`Share of staked TAO in subnets, daily, ${vitals.length} days`}>
            <BarChart
              label="Share of staked TAO in subnets"
              unit="%"
              digits={1}
              points={vitals.filter((v) => v.subnetsSharePct !== null).map((v) => ({ x: day(v.date), y: v.subnetsSharePct as number }))}
            />
          </Block>
          <Block title="Emission gate">
            {gate ? (
              <dl className="grid grid-cols-2 gap-x-4 gap-y-4">
                <div className="flex flex-col-reverse">
                  <dt className="pt-1 text-small text-muted">State</dt>
                  <dd className="text-[28px] font-bold leading-none">{gate.active ? "On" : "Off"}</dd>
                </div>
                <div className="flex flex-col-reverse">
                  <dt className="pt-1 text-small text-muted">Subnets above the bar</dt>
                  <dd className="text-[28px] font-bold leading-none">{num(gate.aboveCount)}</dd>
                </div>
                <div className="flex flex-col-reverse">
                  <dt className="pt-1 text-small text-muted">Bar, share of emission</dt>
                  <dd className="text-[20px] leading-none">{gate.theta === null ? "-" : `${num(gate.theta * 100, 2)}%`}</dd>
                </div>
                <div className="flex flex-col-reverse">
                  <dt className="pt-1 text-small text-muted">Bar set by</dt>
                  <dd className="text-[20px] leading-none">{gate.barMode ?? "-"}</dd>
                </div>
              </dl>
            ) : (
              <p className="text-muted">No gate reading in this window.</p>
            )}
            <p className="mt-5 text-small text-muted">Read {gate ? day(gate.observedAt) : "-"}. A subnet under the bar earns no emission while the gate is on.</p>
          </Block>
        </div>

        <div className="grid gap-4 lg:grid-cols-2">
          <Block title="Chain parameter changes">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[480px] text-[14px]">
                <caption className="sr-only">Chain parameter changes, newest first</caption>
                <thead>
                  <tr>
                    <th className={`${th} text-left`}>Parameter</th>
                    <th className={`${th} text-left`}>Change</th>
                    <th className={`${th} text-right`}>Date</th>
                  </tr>
                </thead>
                <tbody>
                  {params.slice(0, 10).map((p, i) => (
                    <tr key={i}>
                      <td className={`${td} pr-4`}>{p.item}</td>
                      <td className={`${td} pr-4 text-muted`}>
                        {p.prevValue ?? "-"} to <span className="text-ink">{p.newValue ?? "-"}</span>
                      </td>
                      <td className={`${td} text-right text-muted`}>{day(p.observedAt)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Block>
          <Block title="Root rotation">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[420px] text-[14px]">
                <caption className="sr-only">Subnets entering or leaving root validator weights</caption>
                <thead>
                  <tr>
                    <th className={`${th} text-left`}>Subnet</th>
                    <th className={`${th} text-left`}>Direction</th>
                    <th className={`${th} text-right`}>Root share</th>
                    <th className={`${th} text-right`}>Date</th>
                  </tr>
                </thead>
                <tbody>
                  {rotations.slice(0, 10).map((r, i) => (
                    <tr key={i}>
                      <td className={`${td} pr-4`}>SN{r.netuid}</td>
                      <td className={`${td} pr-4 text-muted`}>{r.direction}</td>
                      <td className={`${td} text-right`}>{r.newShare === null ? "-" : `${num(r.newShare * 100, 3)}%`}</td>
                      <td className={`${td} text-right text-muted`}>{day(r.observedAt)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-3 text-small text-muted">Showing {Math.min(10, rotations.length)} of {rotations.length} events.</p>
          </Block>
        </div>
      </div>
    </BoardShell>
  );
}
