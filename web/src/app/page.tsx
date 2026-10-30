import Link from "next/link";
import { getBlockAnchor } from "@/data/chain";
import { getFleet } from "@/data/fleet";
import { getMining } from "@/data/mining";
import { getNetwork } from "@/data/network";
import { getUpgrades } from "@/data/upgrades";
import { BOARDS, SOURCE } from "@/components/boards";
import { Figures, row, table, td, th } from "@/components/board-shell";
import { Strata, type StrataSlot } from "@/components/home/strata";
import { Lane } from "@/components/lane";
import { day, num, polarity, signed } from "@/lib/format";
import { WHY } from "@/lib/words";

const sum = (xs: number[]) => xs.reduce((a, b) => a + b, 0);

export default async function Home() {
  const [fleet, mining, network, upgrades, anchor] = await Promise.all([
    getFleet(),
    getMining(),
    getNetwork(),
    getUpgrades(),
    getBlockAnchor(),
  ]);
  const { rows, counts, activity } = fleet.data;

  const byRow = new Map(rows.map((r) => [r.netuid, r]));
  const byDaily = new Map(activity.map((a) => [a.netuid, a.daily]));
  const slots: StrataSlot[] = Array.from({ length: 128 }, (_, i) => {
    const netuid = i + 1;
    const r = byRow.get(netuid);
    return {
      netuid,
      name: r?.name ?? null,
      tier: r?.tier ?? null,
      why: r?.why ?? null,
      divergence: r?.divergence ?? null,
      momentum30d: r?.momentum30d ?? null,
      daily: byDaily.get(netuid) ?? null,
    };
  });
  const read = activity.filter((a) => a.daily);
  const commits30 = sum(read.map((a) => sum((a.daily as number[]).slice(-30))));
  const lead = rows[0];
  const head = rows.slice(0, 8);

  const lastVitals = network.data.vitals[network.data.vitals.length - 1];
  const lastSpec = upgrades.data.events[upgrades.data.events.length - 1];
  const cpu = mining.data.filter((r) => r.verdict === "possible").length;
  const facts: Record<string, string> = {
    "/mining": `${cpu} of ${mining.data.length} subnets have miner code that runs on a CPU.`,
    "/fleet": `${rows.length} repositories scored by how their code moved, set against price.`,
    "/network": `Subnets hold ${num(lastVitals?.subnetsSharePct ?? null, 2)}% of staked TAO, read daily for ${network.data.vitals.length} days.`,
    "/upgrades": `${upgrades.data.events.length} runtime specs seen. The latest is ${lastSpec?.newSpec}, on ${lastSpec ? day(lastSpec.observedAt) : "-"}.`,
  };

  const reads = [
    ["Code", "Every subnet repository", "cloned, indexed, never run"],
    ["Code", "The subtensor source", "verified clone, change records"],
    ["Chain", "Finney RPC", "spec, emission gate, parameters"],
    ["Markets", "TaoSwap, TaoStats, CoinGecko", "fail-closed readers"],
    ["Facts", "Validated corpus", "each fact carries its date"],
    ["Out", "Telegram", "the few changes worth reading"],
    ["Out", "subnt.dev", "this site, from a scrubbed snapshot"],
  ];

  return (
    <main>
      <Strata slots={slots} initial={lead.netuid} anchor={anchor}>
        <h1 id="hero-title" className="font-display text-hero leading-[0.96] tracking-[-0.025em]">
          Atlas reads all 128 Bittensor subnets.
        </h1>
        <p className="mt-7 text-lead text-ink-2 sm:max-w-[34ch]">
          Code, chain and market, from one Raspberry Pi at home. In the last 30 days it read{" "}
          <strong className="font-medium text-ink">{num(commits30)} commits</strong> across{" "}
          <strong className="font-medium text-ink">{read.length} repositories</strong>.
        </p>
        <div className="mt-9 flex flex-wrap items-center gap-7">
          <Link
            href="/fleet"
            className="inline-flex h-[46px] items-center rounded-[4px] bg-ink px-5 font-medium text-ground transition-colors duration-150 hover:bg-accent-2"
          >
            Open the fleet board
          </Link>
          <a href="#reads" className="border-b border-ink-3 pb-0.5 font-medium transition-colors duration-150 hover:border-ink" /* taste-skill-ignore: secondary action is an underlined text link (DESIGN.md) */>
            What it reads
          </a>
        </div>
      </Strata>

      <div className="mx-auto max-w-[1320px] px-4 sm:px-8">
        <section aria-labelledby="fleet-title" className="grid gap-10 pb-[clamp(96px,11vw,140px)] pt-[clamp(96px,12vw,160px)] lg:grid-cols-[4fr_8fr] lg:gap-16">
          <div>
            <h2 id="fleet-title" className="font-display text-section leading-none tracking-[-0.02em]">
              Fleet attention
            </h2>
            <p className="mt-5 max-w-[30ch] text-[18px] text-ink-2">
              {counts.diverging} subnets show code and price moving 40 points or more apart. {lead.name} leads.
            </p>
            <div className="mt-12">
              <Figures
                items={[
                  { value: counts.diverging, label: "code and price apart" },
                  { value: counts.cold, label: "gone cold this month" },
                  { value: counts.emission, label: "emission routes changed" },
                  { value: counts.invisible, label: "with no public repository" },
                ]}
              />
            </div>
          </div>
          <div className="min-w-0">
            <div className="overflow-x-auto">
              <table className={table}>
                <caption className="sr-only">Top of the fleet board</caption>
                <thead>
                  <tr>
                    <th scope="col" className={th}>Subnet</th>
                    <th scope="col" className={`${th} text-right`}>Score</th>
                    <th scope="col" className={`${th} hidden md:table-cell`}>Why it ranks</th>
                    <th scope="col" className={`${th} hidden text-right md:table-cell`}>Commits, 30 d</th>
                    <th scope="col" className={`${th} text-right`}>Price, 30 d</th>
                    <th scope="col" className={`${th} text-right`}>Last 30 days</th>
                  </tr>
                </thead>
                <tbody>
                  {head.map((r) => (
                    <tr key={r.netuid} className={row}>
                      <td className={td}>
                        <Link href={`/fleet#sn${r.netuid}`} className="hover:text-accent-2">
                          <span className="num mr-2.5 text-ink-3">{r.netuid}</span>
                          {r.name ?? "unnamed"}
                        </Link>
                      </td>
                      <td className={`${td} num text-right`}>{r.score}</td>
                      <td className={`${td} hidden text-ink-2 md:table-cell`}>{r.why ? (WHY[r.why] ?? r.why) : "-"}</td>
                      <td className={`${td} num hidden text-right md:table-cell`}>{num(r.commits30)}</td>
                      <td className={`${td} num text-right ${polarity(r.momentum30d)}`}>
                        {signed(r.momentum30d, 1, "%")}
                      </td>
                      <td className={td}>
                        <Lane daily={byDaily.get(r.netuid) ?? null} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Link href="/fleet" className="mt-8 inline-block border-b border-ink-3 pb-0.5 font-medium transition-colors duration-150 hover:border-ink" /* taste-skill-ignore: secondary action is an underlined text link (DESIGN.md) */>
              All {rows.length} scored subnets
            </Link>
          </div>
        </section>

        <section aria-labelledby="boards-title" className="pb-[clamp(96px,11vw,140px)]">
          <h2 id="boards-title" className="font-display text-section leading-none tracking-[-0.02em]">
            Four boards
          </h2>
          <ul className="mt-10 grid gap-2">
            {BOARDS.map((b) => (
              <li key={b.href}>
                <Link
                  href={b.href}
                  className="grid gap-2 rounded-[10px] py-6 transition-colors duration-150 hover:bg-s1 md:grid-cols-[4fr_4fr_4fr] md:items-baseline md:gap-8 md:px-5"
                >
                  <span className="font-display text-[clamp(28px,3vw,40px)] leading-none">{b.label}</span>
                  <span className="text-ink-2">{b.question}</span>
                  <span className="text-[15px] text-ink-3">{facts[b.href]}</span>
                </Link>
              </li>
            ))}
          </ul>
        </section>

        <section id="reads" aria-labelledby="reads-title" className="grid scroll-mt-8 gap-10 pb-[clamp(96px,11vw,140px)] lg:grid-cols-[4fr_8fr] lg:gap-16">
          <div>
            <h2 id="reads-title" className="font-display text-section leading-none tracking-[-0.02em]">
              What it reads
            </h2>
            <p className="mt-5 max-w-[32ch] text-[18px] text-ink-2">
              Every source is read-only. A stale, partial or contradictory input is reported as unavailable, never filled in.
            </p>
          </div>
          <table className={table}>
            <caption className="sr-only">Sources Atlas reads and outputs it sends</caption>
            <thead>
              <tr>
                <th scope="col" className={th}>Kind</th>
                <th scope="col" className={th}>Source</th>
                <th scope="col" className={`${th} hidden sm:table-cell`}>What Atlas does</th>
              </tr>
            </thead>
            <tbody>
              {reads.map(([kind, what, how]) => (
                <tr key={what}>
                  <td className={`${td} text-ink-3`}>{kind}</td>
                  <td className={td}>
                    {what}
                    <span className="block text-[14px] text-ink-2 sm:hidden">{how}</span>
                  </td>
                  <td className={`${td} hidden text-ink-2 sm:table-cell`}>{how}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <section aria-labelledby="about-title" className="grid gap-10 lg:grid-cols-[4fr_8fr] lg:gap-16">
          <h2 id="about-title" className="font-display text-section leading-none tracking-[-0.02em]">
            How it runs
          </h2>
          <div className="grid gap-x-12 gap-y-10 sm:grid-cols-2">
            <div>
              <h3 className="text-lead font-medium">At home, closed</h3>
              <p className="mt-2 text-ink-2">
                Atlas lives on a Raspberry Pi 5 on a home network. Nothing reaches in. Data leaves only as a validated snapshot with operator details scrubbed out.
              </p>
            </div>
            <div>
              <h3 className="text-lead font-medium">It upgrades itself</h3>
              <p className="mt-2 text-ink-2">
                When the chain runtime moves, a job rewrites the corpus in a worktree, runs every test and a live probe, and only then pushes.
              </p>
            </div>
            <div>
              <h3 className="text-lead font-medium">It shows its gaps</h3>
              <p className="mt-2 text-ink-2">
                Atlas scores {rows.length} of 128 subnet slots. The other {128 - rows.length} have no public repository or code it cannot read, and stay unscored rather than guessed at.
              </p>
            </div>
            <div>
              <h3 className="text-lead font-medium">It gives no advice</h3>
              <p className="mt-2 text-ink-2">
                The boards rank evidence. They hold no wallet, track no one, and recommend no trade.{" "}
                <a href={SOURCE} className="text-ink underline decoration-ink-3 underline-offset-4 transition-colors duration-150 hover:text-accent-2">
                  Read the source
                </a>
                .
              </p>
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}
