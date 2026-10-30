import type { Metadata } from "next";
import { Panel, row, table, td, th } from "@/components/board-shell";
import { BoardHeader } from "@/components/board-header";
import { BarChart } from "@/components/boards/bar-chart";
import { getNetwork } from "@/data/network";
import { day, num, polarity, signed } from "@/lib/format";

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
    { label: "Staked TAO", value: num(last.totalStakedTao), d: delta(first.totalStakedTao, last.totalStakedTao), digits: 0, unit: "" },
    { label: "Share in subnets", value: `${num(last.subnetsSharePct, 2)}%`, d: shareChange, digits: 2, unit: " pt" },
    { label: "Subnet registration, TAO", value: num(last.regCostTao, 1), d: delta(first.regCostTao, last.regCostTao), digits: 1, unit: "" },
    { label: "TAO in USD", value: last.taoUsd === null ? "-" : `$${last.taoUsd.toFixed(2)}`, d: delta(first.taoUsd, last.taoUsd), digits: 2, unit: "" },
  ];

  return (
    <>
      <BoardHeader title="Network pulse" finding={finding} at={generatedAt} />
      <section aria-label="Chain vitals" className="grid grid-cols-1 gap-x-8 gap-y-10 sm:grid-cols-2 lg:grid-cols-4">
        {kpis.map((k) => (
          <dl key={k.label}>
            <dt className="text-[15px] text-ink-2">{k.label}</dt>
            <dd className="num mt-2 font-display text-[clamp(40px,4.4vw,56px)] leading-none">{k.value}</dd>
            <dd className="mt-2 text-small text-ink-3">
              <span className={`num ${polarity(k.d)}`}>{signed(k.d, k.digits, k.unit)}</span> since {since}
            </dd>
          </dl>
        ))}
      </section>

      <div className="mt-[clamp(72px,9vw,120px)] grid gap-6 lg:grid-cols-[8fr_4fr]">
        <Panel title={`Share of staked TAO in subnets, daily, ${vitals.length} days`}>
          <BarChart
            label="Share of staked TAO in subnets"
            unit="%"
            digits={1}
            points={vitals.filter((v) => v.subnetsSharePct !== null).map((v) => ({ x: day(v.date), y: v.subnetsSharePct as number }))}
          />
        </Panel>
        <Panel title="Emission gate">
          {gate ? (
            <dl className="grid grid-cols-2 gap-x-4 gap-y-6">
              <div>
                <dt className="text-small text-ink-3">State</dt>
                <dd className="mt-1 font-display text-[44px] leading-none">{gate.active ? "On" : "Off"}</dd>
              </div>
              <div>
                <dt className="text-small text-ink-3">Above the bar</dt>
                <dd className="num mt-1 font-display text-[44px] leading-none">{num(gate.aboveCount)}</dd>
              </div>
              <div>
                <dt className="text-small text-ink-3">Bar, share of emission</dt>
                <dd className="num mt-1 text-[20px]">{gate.theta === null ? "-" : `${num(gate.theta * 100, 2)}%`}</dd>
              </div>
              <div>
                <dt className="text-small text-ink-3">Bar set by</dt>
                <dd className="mt-1 text-[20px]">{gate.barMode ?? "-"}</dd>
              </div>
            </dl>
          ) : (
            <p className="text-ink-2">No gate reading in this window.</p>
          )}
          <p className="mt-6 text-small text-ink-3">Read {gate ? day(gate.observedAt) : "-"}. A subnet under the bar earns no emission while the gate is on.</p>
        </Panel>
      </div>

      <div className="mt-[clamp(72px,9vw,120px)] grid gap-16 lg:grid-cols-2 lg:gap-12">
        <section aria-labelledby="params-title" className="min-w-0">
          <h2 id="params-title" className="font-display text-[clamp(28px,3vw,40px)] leading-none">
            Chain parameter changes
          </h2>
          <div className="mt-8 overflow-x-auto">
            <table className={`${table} min-w-[460px]`}>
              <caption className="sr-only">Chain parameter changes, newest first</caption>
              <thead>
                <tr>
                  <th scope="col" className={th}>Parameter</th>
                  <th scope="col" className={th}>Change</th>
                  <th scope="col" className={`${th} text-right`}>Date</th>
                </tr>
              </thead>
              <tbody>
                {params.slice(0, 10).map((p, i) => (
                  <tr key={i} className={row}>
                    <td className={td}>{p.item}</td>
                    <td className={`${td} text-ink-2`}>
                      {p.prevValue ?? "-"} to <span className="text-ink">{p.newValue ?? "-"}</span>
                    </td>
                    <td className={`${td} num text-right text-ink-2`}>{day(p.observedAt)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
        <section aria-labelledby="rotation-title" className="min-w-0">
          <h2 id="rotation-title" className="font-display text-[clamp(28px,3vw,40px)] leading-none">
            Root rotation
          </h2>
          <div className="mt-8 overflow-x-auto">
            <table className={`${table} min-w-[420px]`}>
              <caption className="sr-only">Subnets entering or leaving root validator weights</caption>
              <thead>
                <tr>
                  <th scope="col" className={th}>Subnet</th>
                  <th scope="col" className={th}>Direction</th>
                  <th scope="col" className={`${th} text-right`}>Root share</th>
                  <th scope="col" className={`${th} text-right`}>Date</th>
                </tr>
              </thead>
              <tbody>
                {rotations.slice(0, 10).map((r, i) => (
                  <tr key={i} className={row}>
                    <td className={`${td} num`}>SN{r.netuid}</td>
                    <td className={`${td} text-ink-2`}>{r.direction}</td>
                    <td className={`${td} num text-right`}>{r.newShare === null ? "-" : `${num(r.newShare * 100, 3)}%`}</td>
                    <td className={`${td} num text-right text-ink-2`}>{day(r.observedAt)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-4 text-small text-ink-3">
            Showing {Math.min(10, rotations.length)} of {rotations.length} events.
          </p>
        </section>
      </div>
    </>
  );
}
