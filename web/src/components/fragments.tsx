// Small, real pieces of the boards, used as the pictures of the home page.
// Each root carries data-ui: it follows the app-screen rules inside.

import type { Fleet, MiningRow, Network, SignalEvent, Upgrades } from "@/data/types";

const n = (v: number | null, digits = 0) =>
  v === null ? "-" : v.toLocaleString("en-GB", { maximumFractionDigits: digits });

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div data-ui="" className="h-full bg-card p-5 text-[14px] text-ink">
      <p className="pb-3 text-small text-muted">{title}</p>
      {children}
    </div>
  );
}

export function MiningFragment({ rows }: { rows: MiningRow[] }) {
  const top = rows
    .filter((r) => r.grossTaoMonth !== null)
    .sort((a, b) => (b.grossTaoMonth ?? 0) - (a.grossTaoMonth ?? 0))
    .slice(0, 12);
  return (
    <Panel title="Mining triage, top gross per month">
      <table className="w-full">
        <thead className="text-small text-muted">
          <tr>
            <th className="pb-2 text-left font-normal">Subnet</th>
            <th className="pb-2 text-left font-normal">Code</th>
            <th className="pb-2 text-right font-normal">TAO/mo</th>
          </tr>
        </thead>
        <tbody>
          {top.map((r) => (
            <tr key={r.netuid}>
              <td className="py-1">SN{r.netuid} {r.name}</td>
              <td className="py-1 text-muted">{r.verdict ?? "-"}</td>
              <td className="py-1 text-right">{n(r.grossTaoMonth, 1)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  );
}

export function FleetFragment({ fleet }: { fleet: Fleet }) {
  const head = fleet.rows.slice(0, 12);
  return (
    <Panel title="Fleet attention, top of the board">
      <table className="w-full">
        <thead className="text-small text-muted">
          <tr>
            <th className="pb-2 text-left font-normal">Subnet</th>
            <th className="pb-2 text-right font-normal">Commits, 30 d</th>
            <th className="pb-2 text-right font-normal">Score</th>
          </tr>
        </thead>
        <tbody>
          {head.map((r) => (
            <tr key={r.netuid}>
              <td className="py-1">SN{r.netuid} {r.name}</td>
              <td className="py-1 text-right">{n(r.commits30)}</td>
              <td className="py-1 text-right">{r.score}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  );
}

export function NetworkFragment({ network }: { network: Network }) {
  const days = network.vitals.slice(-14);
  const last = days[days.length - 1];
  const values = days.map((d) => d.subnetsSharePct ?? 0);
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  return (
    <Panel title="Network pulse, stake in subnets">
      <p className="text-[40px] font-bold leading-none">{n(last?.subnetsSharePct ?? null, 2)}%</p>
      <p className="pt-1 text-small text-muted">of all staked TAO, {last?.date}</p>
      <svg viewBox={`0 0 ${days.length * 10} 60`} className="mt-5 h-24 w-full" aria-label={`Daily share over ${days.length} days, from ${lo}% to ${hi}%`} role="img">
        {values.map((v, i) => {
          const h = hi === lo ? 30 : 8 + ((v - lo) / (hi - lo)) * 52;
          return <rect key={i} x={i * 10 + 1} y={60 - h} width={8} height={h} fill="currentColor" />;
        })}
      </svg>
      <p className="flex justify-between text-small text-muted">
        <span>{days[0]?.date}</span>
        <span>{last?.date}</span>
      </p>
    </Panel>
  );
}

export function UpgradesFragment({ upgrades }: { upgrades: Upgrades }) {
  const recent = upgrades.events.slice(-12).reverse();
  return (
    <Panel title="Runtime upgrades, latest specs">
      <ul>
        {recent.map((e) => (
          <li key={e.newSpec} className="flex items-baseline justify-between gap-4 py-1">
            <span>
              Spec {e.prevSpec} to {e.newSpec}
            </span>
            <span className="text-muted">{e.observedAt.slice(0, 10)}</span>
          </li>
        ))}
      </ul>
    </Panel>
  );
}

const SIGNAL_WORD: Record<string, string> = {
  "econ-code": "Economics code changed",
  "narrative-cluster": "Several subnets moved together",
  "signal-digest": "Daily digest",
  watchlist: "Watchlist hit",
};

export function SignalsFragment({ signals }: { signals: SignalEvent[] }) {
  return (
    <Panel title="Rotation signals, most recent first">
      <ul>
        {signals.slice(0, 10).map((e, i) => (
          <li key={i} className="flex items-baseline justify-between gap-4 py-1">
            <span>
              {e.netuid !== null ? `SN${e.netuid} ` : ""}
              <span className="text-muted">{SIGNAL_WORD[e.class] ?? e.class}</span>
            </span>
            <span className="shrink-0 text-muted">{e.createdAt.slice(5, 10)}</span>
          </li>
        ))}
      </ul>
    </Panel>
  );
}
