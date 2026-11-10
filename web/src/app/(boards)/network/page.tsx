import type { Metadata } from "next";
import { Panel, row, table, td, th } from "@/components/board-shell";
import { BoardHeader } from "@/components/board-header";
import { BarChart } from "@/components/boards/bar-chart";
import { getMining } from "@/data/mining";
import { getNetwork } from "@/data/network";
import { day, num, polarity, signed } from "@/lib/format";
import { BAR_MODE, CROSSING, emissionMovers, type Mover, paramRows, seriesTitle, usd } from "@/lib/network";

export const metadata: Metadata = { title: "Network pulse" };

const SHOWN = 10;
// Setting text is prose: let it wrap on a phone instead of scrolling the table.
const tdWrap = td.replace("whitespace-nowrap", "whitespace-normal");

export default async function NetworkPage() {
  const [{ generatedAt, readAt, data }, mining] = await Promise.all([getNetwork(), getMining()]);
  const names = new Map(mining.data.map((m) => [m.netuid, m.name]));
  const { vitals, gate, crossings, emission, emissionSince, params } = data;
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
  const shownParams = paramRows(params).slice(0, SHOWN);
  const movers = emissionMovers(emission, 5);
  const nameOf = (n: number) => names.get(n) ?? "unnamed";
  const moverList = (title: string, list: Mover[]) => (
    <div className="min-w-0">
      <h3 className="text-body text-ink-2">{title}</h3>
      <ul className="mt-4">
        {list.map((m) => (
          <li key={m.netuid} className="flex items-baseline justify-between gap-4 border-t border-rule py-4">
            <div className="min-w-0">
              <div>{nameOf(m.netuid)}</div>
              <div className="num text-small text-ink-3">
                SN {m.netuid} · {num(m.then, 2)}% to {num(m.now, 2)}%
              </div>
            </div>
            <div className={`num text-lead ${polarity(m.change)}`}>{signed(m.change, 2, " pt")}</div>
          </li>
        ))}
      </ul>
    </div>
  );

  return (
    <>
      <BoardHeader title="Network pulse" finding={finding} at={generatedAt} readAt={readAt} />
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

      <section aria-labelledby="emission-title" className="mt-[clamp(72px,9vw,120px)]">
        <h2 id="emission-title" className="font-display text-sub leading-none">
          Emission share, last 30 days
        </h2>
        <p className="mt-4 max-w-[60ch] text-body text-ink-2">
          Each subnet&apos;s share of all new emission, {emissionSince ? day(emissionSince) : "-"} against {day(generatedAt)}. Shares add up to
          100%, so one subnet&apos;s gain is spread as losses across the rest.
        </p>
        {movers.up.length || movers.down.length ? (
          <div className="mt-8 grid gap-12 lg:grid-cols-2">
            {moverList("Gained most", movers.up)}
            {moverList("Lost most", movers.down)}
          </div>
        ) : (
          <p className="mt-8 text-ink-2">No emission readings 30 days apart yet.</p>
        )}
      </section>

      <div className="mt-[clamp(72px,9vw,120px)] grid gap-16 lg:grid-cols-[8fr_4fr] lg:gap-12">
        <section aria-labelledby="params-title" className="min-w-0">
          <h2 id="params-title" className="font-display text-sub leading-none">
            Chain parameter changes
          </h2>
          <p className="mt-4 max-w-[60ch] text-body text-ink-2">
            Settings the chain changed for one subnet or for the whole network, newest first. TAO injection off means the chain stops adding
            TAO to that subnet&apos;s pool; its alpha emission continues. One row per setting, with every change Atlas saw.
          </p>
          <div className="mt-8 overflow-x-auto">
            <table className={table}>
              <caption className="sr-only">Chain parameter changes, one row per setting, newest first</caption>
              <thead>
                <tr>
                  <th scope="col" className={th}>Subnet</th>
                  <th scope="col" className={th}>Setting and what it means now</th>
                  <th scope="col" className={`${th} hidden text-right sm:table-cell`}>Last change</th>
                </tr>
              </thead>
              <tbody>
                {shownParams.map((r) => (
                  <tr key={`${r.netuid}-${r.setting}`} className={row}>
                    <td className={`${tdWrap} align-top`}>
                      <div>{r.netuid === null ? "Whole network" : (names.get(r.netuid) ?? "unnamed")}</div>
                      <div className="num text-small text-ink-3">
                        {r.netuid === null ? null : `SN ${r.netuid}`}
                        <span className="sm:hidden">{r.netuid === null ? "" : " · "}{day(r.observedAt)}</span>
                      </div>
                    </td>
                    <td className={`${tdWrap} align-top`}>
                      <div>{r.setting}</div>
                      <div className="text-ink-2">{r.means}</div>
                      {r.history ? <div className="mt-1 text-small text-ink-3">{r.history}</div> : null}
                    </td>
                    <td className={`${td} num hidden align-top text-right text-ink-2 sm:table-cell`}>{day(r.observedAt)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-4 text-small text-ink-3">The {shownParams.length} most recently changed settings.</p>
        </section>
        <section aria-labelledby="crossings-title" className="min-w-0">
          <h2 id="crossings-title" className="font-display text-sub leading-none">
            Gate crossings
          </h2>
          <p className="mt-4 text-body text-ink-2">
            Subnets whose demand share crossed the emission bar. Below the bar, a subnet earns no emission while the gate is on.
          </p>
          <ul className="mt-8">
            {crossings.map((c, i) => (
              <li key={i} className="border-t border-rule py-4">
                <div className="flex items-baseline justify-between gap-4">
                  <div>{nameOf(c.netuid)}</div>
                  <div className="num text-small text-ink-3">{day(c.observedAt)}</div>
                </div>
                <div className={c.direction === "fell-below" ? "text-down" : "text-up"}>{CROSSING[c.direction] ?? c.direction}</div>
                <div className="num text-small text-ink-3">
                  SN {c.netuid} · share {c.share === null ? "-" : `${num(c.share * 100, 2)}%`}, bar {c.theta === null ? "-" : `${num(c.theta * 100, 2)}%`}
                  {c.eligibility === "reversed" ? " · crossed back within 2 days" : ""}
                </div>
              </li>
            ))}
          </ul>
          {crossings.length ? null : <p className="mt-8 text-ink-2">No crossings recorded.</p>}
          <p className="mt-4 text-small text-ink-3">The {crossings.length} newest crossings.</p>
        </section>
      </div>
    </>
  );
}
