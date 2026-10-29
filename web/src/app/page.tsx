import Link from "next/link";
import { getFleet } from "@/data/fleet";
import { getMining } from "@/data/mining";
import { getNetwork } from "@/data/network";
import { getUpgrades } from "@/data/upgrades";
import { BOARDS } from "@/components/boards";
import { FleetFragment, MiningFragment, NetworkFragment, SignalsFragment, UpgradesFragment } from "@/components/fragments";
import { Reveal } from "@/components/motion";
import { SiteNav } from "@/components/site-nav";
import { Showcase } from "@/components/home/showcase";
import { SubnetPicker, type Slot } from "@/components/home/subnet-picker";
import { SiteFooter } from "@/components/site-footer";

const SOURCE = "https://github.com/vanlabs-dev/atlas";

// The square bite out of a stage's corner: the cell, cut from the shape.
const NOTCH = "polygon(0 72px, 72px 72px, 72px 0, 100% 0, 100% 100%, 0 100%)";

export default async function Home() {
  const [fleet, mining, network, upgrades] = await Promise.all([getFleet(), getMining(), getNetwork(), getUpgrades()]);

  const byFleet = new Map(fleet.data.rows.map((r) => [r.netuid, r]));
  const byMining = new Map(mining.data.map((r) => [r.netuid, r]));
  const slots: Slot[] = Array.from({ length: 128 }, (_, i) => {
    const netuid = i + 1;
    const f = byFleet.get(netuid);
    const m = byMining.get(netuid);
    return {
      netuid,
      name: f?.name ?? m?.name ?? null,
      tier: f?.tier ?? null,
      score: f?.score ?? null,
      commits30: f?.commits30 ?? null,
      authors30: f?.authors30 ?? null,
      verdict: m?.verdict ?? null,
      grossTaoMonth: m?.grossTaoMonth ?? null,
      minerBurnPct: m?.minerBurnPct ?? null,
    };
  });
  const lead = fleet.data.rows[0];
  const scored = fleet.data.rows.length;
  const repoless = 128 - scored;
  const lastSpec = upgrades.data.events[upgrades.data.events.length - 1];

  const showcase = [
    {
      href: "/mining",
      label: "Mining triage",
      fact: `${mining.data.length} subnets priced for a new miner: burn, earners, cost to register, and what the code needs.`,
      fragment: <MiningFragment rows={mining.data} />,
    },
    {
      href: "/fleet",
      label: "Fleet attention",
      fact: `${scored} repositories scored by how their code moved, set against how their price moved.`,
      fragment: <FleetFragment fleet={fleet.data} />,
    },
    {
      href: "/network",
      label: "Network pulse",
      fact: `${network.data.vitals.length} days of chain vitals, the emission gate, and every root rotation.`,
      fragment: <NetworkFragment network={network.data} />,
    },
    {
      href: "/upgrades",
      label: "Runtime upgrades",
      fact: `${upgrades.data.events.length} runtime specs seen, the latest ${lastSpec?.newSpec}, each one read into the corpus.`,
      fragment: <UpgradesFragment upgrades={upgrades.data} />,
    },
  ];

  const steps = [
    { clause: "First it clones the code.", lines: [`SN${lead.netuid} ${lead.name}`, "repository cloned and indexed"] },
    { clause: "Then it reads what changed.", lines: [`${lead.commits30} commits in 30 days`, `${lead.authors30} authors, last ${lead.daysSinceCommit} d ago`] },
    { clause: "Then it scores the change.", lines: [`fleet score ${lead.score}`, `code against price: ${lead.divergence! > 0 ? "+" : ""}${lead.divergence}`] },
    { clause: "Then it lands on a board.", lines: [`head of the fleet board`, `reason: ${lead.why}`] },
  ];
  const fields = ["bg-card", "bg-ground", "bg-surface", "bg-tier-quiet"];

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
    <>
      <div className="relative overflow-hidden lg:min-h-[max(100svh,720px)]">
        <SiteNav />
        <main id="top" className="mx-auto max-w-[1440px] px-4 sm:px-10">
          <section aria-labelledby="hero-title" className="pt-14 lg:pt-[110px]">
            <h1 id="hero-title" className="max-w-[12ch] text-[10vw] font-bold leading-[0.95] tracking-[-0.02em] sm:text-[clamp(52px,5.2vw,80px)]">
              Atlas watches every subnet.
            </h1>
            <p className="mt-8 max-w-[32ch] text-body">
              A self-hosted system on one Raspberry Pi. It clones the code of every Bittensor subnet, reads the chain, and shows what changed.
            </p>
            <Link
              href="/fleet"
              className="mt-8 inline-flex items-center gap-2 bg-accent px-4 py-2 text-[16px] font-medium text-accent-ink transition-transform hover:-translate-y-px active:translate-y-px"
            >
              <span className="cell" aria-hidden="true" />
              Open the fleet board
            </Link>
          </section>
        </main>
        <div className="stage relative mt-12 lg:absolute lg:bottom-0 lg:left-[calc(100%*4/12)] lg:right-0 lg:top-[42%] lg:mt-0">
          <div className="h-full overflow-hidden bg-accent px-4 pb-4 pt-[88px] sm:px-10 lg:pb-0 lg:pl-[104px] lg:pr-0 lg:pt-14" style={{ clipPath: NOTCH }}>
            <div className="stage-fragment origin-top-left">
              <SubnetPicker slots={slots} initial={lead.netuid} />
            </div>
          </div>
        </div>
      </div>

      <div className="mx-auto max-w-[1440px] px-4 sm:px-10">
        <section aria-labelledby="boards-title" className="py-[clamp(96px,14vw,200px)]">
          <Reveal>
            <Showcase items={showcase} />
          </Reveal>
        </section>
      </div>

      <section aria-labelledby="how-title" className="grid sm:grid-cols-2 lg:grid-cols-4">
        {steps.map((s, i) => (
          <div key={s.clause} className={`${fields[i]} flex flex-col p-5 sm:min-h-[56svh] md:p-7 lg:min-h-[78svh]`}>
            {i === 0 ? (
              <h2 id="how-title" className="text-lead font-bold">
                How a change travels
              </h2>
            ) : null}
            <Reveal step={i} className="mt-8 lg:mt-[24svh]">
              <div data-ui="" className="w-full max-w-[260px] bg-card p-4 text-[14px] transition-transform hover:-translate-y-1.5">
                <p className="flex items-center gap-2 text-small text-muted">
                  <span className="cell text-ink" aria-hidden="true" />
                  SN{lead.netuid}
                </p>
                {s.lines.map((l) => (
                  <p key={l} className="pt-1">{l}</p>
                ))}
              </div>
            </Reveal>
            <p className="mt-auto pt-10 text-lead font-medium leading-tight">{s.clause}</p>
          </div>
        ))}
      </section>

      <div className="mx-auto max-w-[1440px] px-4 sm:px-10">
        <section aria-labelledby="reads-title" className="py-[clamp(96px,14vw,200px)]">
          <Reveal>
            <h2 id="reads-title" className="max-w-[18ch] text-[clamp(36px,9.5vw,64px)] font-bold leading-[0.98] tracking-[-0.02em] md:pl-[3vw] md:text-[clamp(40px,4.4vw,64px)]">
              What Atlas reads and sends
            </h2>
          </Reveal>
          <div className="mt-24 grid md:grid-cols-12">
            <div className="hidden md:col-span-6 md:flex md:flex-col md:justify-between md:gap-10 md:pr-10">
              <p className="max-w-[34ch] text-body">
                Every source is read-only. A stale, partial or contradictory input is reported as unavailable, never filled in.
              </p>
              <Reveal step={1} className="max-w-[420px]">
                <SignalsFragment signals={fleet.data.signals} />
              </Reveal>
            </div>
            <p className="hidden pt-1 text-small text-muted md:col-span-1 md:block">Sources</p>
            <table className="w-full self-end text-[16px] md:col-span-5">
              <caption className="sr-only">Sources Atlas reads and outputs it sends</caption>
              <thead className="sr-only">
                <tr>
                  <th scope="col">Kind</th>
                  <th scope="col">Source</th>
                  <th scope="col">What Atlas does</th>
                </tr>
              </thead>
              <tbody>
                {reads.map(([kind, what, how], i) => (
                  <tr key={what} className={i > 0 && i % 4 === 0 ? "[&>td]:pt-11" : ""}>
                    <td className="py-[13px] pr-4 align-top text-muted">{kind}</td>
                    <td className="py-[13px] pr-4 align-top">{what}</td>
                    <td className="py-[13px] text-right align-top text-muted">{how}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>

      <section aria-labelledby="about-title" className="mx-[10px] overflow-hidden bg-card md:mx-5">
        <div className="grid gap-12 p-6 md:grid-cols-2 md:gap-x-[6vw] md:p-14 lg:grid-cols-[1fr_300px_300px]">
          <Reveal className="flex flex-col">
            <h2 id="about-title" className="max-w-[12ch] text-[clamp(36px,8.5vw,64px)] font-bold leading-[0.98] tracking-[-0.02em] md:text-[clamp(40px,4.4vw,64px)]">
              One Pi, no open ports.
            </h2>
            <div className="mt-16 -mb-14 hidden w-full lg:block" style={{ clipPath: NOTCH }}>
              <div className="w-full max-w-[560px] bg-accent pl-[104px] pt-14">
                <UpgradesFragment upgrades={upgrades.data} />
              </div>
            </div>
          </Reveal>
          <Reveal step={1}>
            <h3 className="text-lead font-bold">It runs at home</h3>
            <p className="mt-3 text-body">
              Atlas lives on a Raspberry Pi 5 on a home network. Nothing reaches in. Data leaves only as a validated snapshot with operator details scrubbed out.
            </p>
            <h3 className="mt-16 text-lead font-bold">It upgrades itself</h3>
            <p className="mt-3 text-body">
              When the chain runtime moves, a job rewrites the corpus in a worktree, runs every test and a live probe, and only then pushes.
            </p>
            <a href={SOURCE} className="mt-10 inline-block bg-accent px-4 py-2 text-[16px] font-medium text-accent-ink transition-transform hover:-translate-y-px active:translate-y-px">
              Read the source
            </a>
          </Reveal>
          <Reveal step={2}>
            <h3 className="text-lead font-bold">It shows its work</h3>
            <p className="mt-3 text-body">
              Of 128 subnets, {scored} have a public repository Atlas can score. The other {repoless} are listed as such, not guessed at.
            </p>
            <h3 className="mt-16 text-lead font-bold">It gives no advice</h3>
            <p className="mt-3 text-body">
              The boards rank evidence. They hold no wallet, track no one, and recommend no trade.
            </p>
          </Reveal>
        </div>
      </section>

      <SiteFooter boards={BOARDS} source={SOURCE} />
    </>
  );
}
