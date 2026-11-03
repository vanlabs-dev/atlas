import type { Metadata } from "next";
import { Panel, row, table, td, th } from "@/components/board-shell";
import { BoardHeader } from "@/components/board-header";
import { BarChart } from "@/components/boards/bar-chart";
import { getNetwork } from "@/data/network";
import { day, num, polarity, signed } from "@/lib/format";
import { BAR_MODE, paramText, ROTATION, seriesTitle, usd } from "@/lib/network";

export const metadata: Metadata = { title: "Network pulse" };

const SHOWN = 10;

export default async function NetworkPage() {
  const { generatedAt, data } = await getNetwork();
  const { vitals, gate, rotations, params } = data;
  const first = vitals[0] ?? null;
  const last = vitals[vitals.length - 1] ?? null;
  const since = first ? day(first.date) : "-";
  const delta = (a: number | null | undefined, b: number | null | undefined) => (a == null || b == null ? null : b - a);
  const shareChange = delta(first?.subnetsSharePct, last?.subnetsSharePct);
  const share = vitals.filter((v) => v.subnetsSharePct !== null);
  const gateText = gate ? `The emission gate is ${gate.active ? "on" : "off"}, with ${num(gate.aboveCount)} subnets above the bar.` : "No emission gate reading.";

  const finding = last
    ? `Subnets hold ${num(last.subnetsSharePct, 2)}% of all staked TAO, ${signed(shareChange, 2, " points")} since ${since}. ${gateText}`
    : `No chain vitals in this window. ${gateText}`;

  const kpis = [
    { label: "Staked TAO", value: num(last?.totalStakedTao), d: delta(first?.totalStakedTao, last?.totalStakedTao), digits: 0, unit: "" },
    { label: "Share in subnets", value: last?.subnetsSharePct == null ? "-" : `${num(last.subnetsSharePct, 2)}%`, d: shareChange, digits: 2, unit: " pt" },
    { label: "Subnet registration, TAO", value: num(last?.regCostTao, 1), d: delta(first?.regCostTao, last?.regCostTao), digits: 1, unit: "" },
    { label: "TAO in USD", value: usd(last?.taoUsd ?? null), d: delta(first?.taoUsd, last?.taoUsd), digits: 0, unit: "" },
  ];
  const shownParams = params.slice(0, SHOWN);
  const shownRotations = rotations.slice(0, SHOWN);

  return (
    <>
      <BoardHeader title="Network pulse" finding={finding} at={generatedAt} />
      <section aria-label="Chain vitals" className="grid grid-cols-1 gap-x-8 gap-y-10 sm:grid-cols-2 lg:grid-cols-4">
        {kpis.map((k) => (
          <dl key={k.label}>
            <dt className="text-body text-ink-2">{k.label}</dt>
            <dd className="num mt-2 font-display text-[clamp(44px,5vw,64px)] leading-none">{k.value}</dd>
            <dd className="mt-2 text-small text-ink-3">
              <span className={`num ${polarity(k.d)}`}>{signed(k.d, k.digits, k.unit)}</span> since {since}
            </dd>
          </dl>
        ))}
      </section>

      <div className="mt-[clamp(72px,9vw,120px)] grid gap-6 lg:grid-cols-[8fr_4fr]">
        <Panel title={`Share of staked TAO in subnets, ${seriesTitle(share.map((v) => v.date))}`}>
          {share.length ? (
            <BarChart
              label="Share of staked TAO in subnets"
              unit="%"
              digits={1}
              points={share.map((v) => ({ x: day(v.date), y: v.subnetsSharePct as number }))}
            />
          ) : (
            <p className="text-ink-2">No readings in this window.</p>
          )}
        </Panel>
        <Panel title="Emission gate">
          {gate ? (
            <dl className="grid grid-cols-2 gap-x-4 gap-y-6">
              <div>
                <dt className="text-small text-ink-3">State</dt>
                <dd className="mt-1 font-display text-section leading-none">{gate.active ? "On" : "Off"}</dd>
              </div>
              <div>
                <dt className="text-small text-ink-3">Above the bar</dt>
                <dd className="num mt-1 font-display text-section leading-none">{num(gate.aboveCount)}</dd>
              </div>
              <div>
                <dt className="text-small text-ink-3">Bar, share of emission</dt>
                <dd className="num mt-1 text-lead">{gate.theta === null ? "-" : `${num(gate.theta * 100, 2)}%`}</dd>
              </div>
              <div>
                <dt className="text-small text-ink-3">How the bar is set</dt>
                <dd className="mt-1 text-lead">{gate.barMode ? (BAR_MODE[gate.barMode] ?? gate.barMode) : "-"}</dd>
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
          <h2 id="params-title" className="font-display text-sub leading-none">
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
                {shownParams.map((p, i) => {
                  const t = paramText(p);
                  return (
                    <tr key={i} className={row}>
                      <td className={td}>{t.name}</td>
                      <td className={`${td} text-ink-2`}>{t.change}</td>
                      <td className={`${td} num text-right text-ink-2`}>{day(p.observedAt)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="mt-4 text-small text-ink-3">The {shownParams.length} newest changes.</p>
        </section>
        <section aria-labelledby="rotation-title" className="min-w-0">
          <h2 id="rotation-title" className="font-display text-sub leading-none">
            Root rotation
          </h2>
          <div className="mt-8 overflow-x-auto">
            <table className={`${table} min-w-[420px]`}>
              <caption className="sr-only">Subnets entering or leaving root validator weights</caption>
              <thead>
                <tr>
                  <th scope="col" className={th}>Subnet</th>
                  <th scope="col" className={th}>Change</th>
                  <th scope="col" className={`${th} text-right`}>Share of root weight</th>
                  <th scope="col" className={`${th} text-right`}>Date</th>
                </tr>
              </thead>
              <tbody>
                {shownRotations.map((r, i) => (
                  <tr key={i} className={row}>
                    <td className={`${td} num`}>SN{r.netuid}</td>
                    <td className={`${td} text-ink-2`}>{ROTATION[r.direction] ?? r.direction}</td>
                    <td className={`${td} num text-right`}>{r.newShare === null ? "-" : `${num(r.newShare * 100, 3)}%`}</td>
                    <td className={`${td} num text-right text-ink-2`}>{day(r.observedAt)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-4 text-small text-ink-3">The {shownRotations.length} newest events.</p>
        </section>
      </div>
    </>
  );
}
