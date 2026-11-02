import Link from "next/link";
import { getBlockAnchor } from "@/data/chain";
import { getFleet } from "@/data/fleet";
import { getMining } from "@/data/mining";
import { getNetwork } from "@/data/network";
import { getUpgrades } from "@/data/upgrades";
import { BOARDS } from "@/components/boards";
import { Flight, type FlightRow } from "@/components/home/flight";
import { LeadPanel, type LeadRow } from "@/components/home/lead-panel";
import { BandBlock } from "@/components/home/band-block";
import { CountUp, Reveal } from "@/components/home/reveal";
import { day, num, signed } from "@/lib/format";

const sum = (xs: number[]) => xs.reduce((a, b) => a + b, 0);
const tone = (v: number | null) => (v === null || v === 0 ? "" : v < 0 ? "dn" : "up");
const arrow = (v: number | null) => (v === null || v === 0 ? "" : v < 0 ? "▼ " : "▲ ");

export default async function Home() {
  const [fleet, mining, network, upgrades, anchor] = await Promise.all([
    getFleet(),
    getMining(),
    getNetwork(),
    getUpgrades(),
    getBlockAnchor(),
  ]);
  const { rows, counts, activity } = fleet.data;
  const at = fleet.generatedAt;

  const byRow = new Map(rows.map((r) => [r.netuid, r]));
  const byDaily = new Map(activity.map((a) => [a.netuid, a.daily]));
  const names = new Map(mining.data.map((m) => [m.netuid, m.name]));
  const c30 = (d: number[] | null) => (d ? sum(d.slice(-30)) : null);
  const c7 = (d: number[]) => sum(d.slice(-7));

  // All 128 slots, then the field's sediment order: no code at the back, then silent, then by 30-day commits.
  const slots = Array.from({ length: 128 }, (_, i) => {
    const n = i + 1;
    const r = byRow.get(n);
    const daily = byDaily.get(n) ?? null;
    return { n, r, name: r?.name ?? names.get(n) ?? null, daily, c30: c30(daily), tot: daily ? sum(daily) : 0 };
  });
  const flightRows: FlightRow[] = [...slots]
    .sort((a, b) => (a.daily ? 1 : 0) - (b.daily ? 1 : 0) || (a.c30 ?? 0) - (b.c30 ?? 0) || (a.daily && b.daily ? a.tot - b.tot : 0))
    .map((s) => ({ n: s.n, name: s.name, head: s.r?.tier === "head", c30: s.c30, daily: s.daily }));

  const read = slots.filter((s) => s.daily);
  const total = sum(read.map((s) => s.c30 ?? 0));
  const silent = read.filter((s) => s.c30 === 0).length;
  const lead = rows[0];
  const lr = (r: (typeof rows)[number]): LeadRow => ({
    n: r.netuid, name: r.name, score: r.score, why: r.why, daily: byDaily.get(r.netuid) ?? null,
    c7: r.commits7, c30: r.commits30, a30: r.authors30, dsc: r.daysSinceCommit, m7: r.momentum7d, m30: r.momentum30d,
  });

  // The band: who wrote the month's commits, as one proportional bar.
  const byC = [...read].sort((a, b) => (b.c30 ?? 0) - (a.c30 ?? 0));
  const top = byC.slice(0, 7);
  const topSum = sum(top.map((s) => s.c30 ?? 0));
  const top5 = byC.slice(0, 5);

  const watch = rows.slice(3, 12);
  const cold = rows.filter((r) => r.cold).slice(0, 6);
  const busy = [...read].sort((a, b) => c7(b.daily!) - c7(a.daily!)).slice(0, 6);

  const specs = upgrades.data.events.slice(-8);
  const gaps = specs.map((e, i) => (i ? Math.round((Date.parse(e.observedAt.slice(0, 10)) - Date.parse(specs[i - 1].observedAt.slice(0, 10))) / 864e5) : 0));
  const meanGap = sum(gaps.slice(1)) / (gaps.length - 1);
  const maxGap = Math.max(...gaps.slice(1), 1);

  const lastVitals = network.data.vitals[network.data.vitals.length - 1];
  const lastSpec = upgrades.data.events[upgrades.data.events.length - 1];
  const cpu = mining.data.filter((r) => r.verdict === "possible").length;
  const facts: Record<string, string> = {
    "/mining": `${cpu} of ${mining.data.length} subnets have miner code that runs on a CPU.`,
    "/fleet": `${rows.length} repositories scored by how their code moved, set against price.`,
    "/network": `Subnets hold ${num(lastVitals?.subnetsSharePct ?? null, 2)}% of staked TAO, read daily for ${network.data.vitals.length} days.`,
    "/upgrades": `${upgrades.data.events.length} runtime specs seen. The latest is ${lastSpec?.newSpec}, on ${lastSpec ? day(lastSpec.observedAt) : "-"}.`,
  };

  const reads: [string, [string, string][]][] = [
    ["Code", [["Every subnet repository", "cloned, indexed, never run"], ["The subtensor source", "verified clone, change records"]]],
    ["Chain", [["Finney RPC", "spec, emission gate, parameters"]]],
    ["Markets", [["TaoSwap, TaoStats, CoinGecko", "fail-closed readers"]]],
    ["Facts", [["Validated corpus", "each fact carries its date"]]],
    ["Out", [["Telegram", "the few changes worth reading"], ["subnt.dev", "this site, from a scrubbed snapshot"]]],
  ];

  const spark = (d: number[]) => {
    const last = d.slice(-30);
    const mx = Math.max(1, ...last);
    const pts = last.map((c, i) => [(i / 29) * 104, 28 - (c / mx) * 26] as const);
    const path = (ps: (readonly [number, number])[]) => ps.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`).join("");
    return (
      <svg className="spark" viewBox="0 0 104 30" preserveAspectRatio="none" aria-hidden="true">
        <path className="draw" pathLength={1} d={path(pts.slice(0, 24))} />
        <path className="draw last" pathLength={1} d={path(pts.slice(23))} style={{ transitionDelay: "700ms" }} />
      </svg>
    );
  };

  return (
    <main className="home -mt-16 md:-mt-[76px]">
      <Flight
        rows={flightRows}
        leadN={lead.netuid}
        generatedAt={at}
        anchor={anchor}
        stops={
          <ol className="stops">
            <li className="stop">
              <h2>One row for every subnet</h2>
              <p>
                128 rows, 90 days deep. <strong>{128 - read.length} subnets</strong> have no code Atlas can read; they lie at the back as dotted lines.
              </p>
            </li>
            <li className="stop">
              <h2>Ninety days to today</h2>
              <p>
                Each mark is one subnet on one day, as tall as its commits. <strong>{silent} subnets</strong> went silent in the last 30 days.
              </p>
            </li>
            <li className="stop">
              <h2>The busiest code, up close</h2>
              <p>
                <strong>{counts.diverging} subnets</strong> show code and price moving 40 points or more apart. {lead.name} leads the fleet board.
              </p>
            </li>
          </ol>
        }
      >
        <h1 id="hero-title" className="font-display text-hero leading-[0.9] tracking-[-0.045em]">
          Atlas reads all 128 Bittensor subnets.
        </h1>
        <p className="lede">
          Code, chain and market, from one Raspberry Pi at home. In the last 30 days it read <strong>{num(total)} commits</strong> across{" "}
          <strong>{read.length} repositories</strong>.
        </p>
        <div className="acts">
          <Link className="btn" href="/fleet">
            Open the fleet board
          </Link>
          <a className="ul" href="#reads">
            What it reads
          </a>
        </div>
      </Flight>

      <section className="band" aria-labelledby="band-title">
        <h2 id="band-title" className="sr-only">
          The last 30 days in figures
        </h2>
        <div className="wrap">
          <div>
            <div className="val fig">
              <CountUp value={total} ms={1400} />
            </div>
            <div className="lab2">
              commits read in 30 days, across <b>{read.length}</b> repositories
            </div>
          </div>
          <div className="min-w-0">
            <Reveal className="seg">
              {top.map((s, i) => (
                <div key={s.n} className={i === 0 ? "top" : ""} style={{ flex: s.c30 ?? 0, transitionDelay: `${i * 70}ms` }} title={`${s.name}, ${num(s.c30)} commits`}>
                  <b>{s.name}</b>
                  <span>{num(s.c30)}</span>
                </div>
              ))}
              <div className="rest" style={{ flex: total - topSum, transitionDelay: "490ms" }}>
                <b>{read.length - 7} others</b>
                <span>{num(total - topSum)}</span>
              </div>
            </Reveal>
            <div className="lab2 mt-2.5">Where the commits went: the top 7 wrote {Math.round((100 * topSum) / total)}%</div>
            <ul className="seglegend">
              {top5.map((s) => (
                <li key={s.n}>
                  <b>{s.name}</b>
                  <span>{num(s.c30)}</span>
                </li>
              ))}
              <li>
                <span>{read.length - 5} others</span>
                <span>{num(total - sum(top5.map((s) => s.c30 ?? 0)))}</span>
              </li>
            </ul>
          </div>
          <dl className="bfigs" data-ui="">
            <div>
              <dd><b className="rd"><CountUp value={counts.diverging} ms={1000} /></b></dd>
              <dt className="lab2">Code and price apart</dt>
            </div>
            <div>
              <dd><b><CountUp value={counts.cold} ms={1000} /></b></dd>
              <dt className="lab2">Gone cold</dt>
            </div>
            <div>
              <dd><b><CountUp value={counts.invisible} ms={1000} /></b></dd>
              <dt className="lab2">No public repository</dt>
            </div>
            <div>
              <dd><b><BandBlock anchor={anchor} /></b></dd>
              <dt className="lab2">est. block</dt>
            </div>
          </dl>
        </div>
      </section>

      <div className="wrap">
        <section className="sec" aria-labelledby="lead-title">
          <h2 className="headline2" id="lead-title">
            {counts.diverging} subnets show code and price apart. {lead.name} leads.
          </h2>
          <p className="sub3">
            Apart means 40 points or more between how the code moved and how the price moved. Scored {day(at)} from {rows.length} repositories.
          </p>
          <div className="lead-grid">
            <LeadPanel heads={rows.slice(0, 3).map(lr)} generatedAt={at} />
            <aside className="watch" aria-labelledby="watch-title">
              <h2 id="watch-title">Next on the board</h2>
              <p className="cap">Squares: code this week, code this month, three or more authors, price up over 30 days, emission route visible.</p>
              <Reveal as="ul" className="wrows">
                {watch.map((s) => {
                  const checks = [(s.commits7 ?? 0) > 0, (s.commits30 ?? 0) > 0, (s.authors30 ?? 0) >= 3, (s.momentum30d ?? 0) > 0, !s.emissionOpaque];
                  const last = s.daysSinceCommit === null ? "no commits read" : s.daysSinceCommit === 0 ? "committed today" : `last commit ${s.daysSinceCommit} days ago`;
                  return (
                    <li key={s.netuid} className="wrow">
                      <Link href={`/fleet#sn${s.netuid}`} data-ui="">
                        <div>
                          <div className="n">{s.name ?? "unnamed"}</div>
                          <div className="s">
                            SN {s.netuid} · {last}
                          </div>
                        </div>
                        <div className="boxes" role="img" aria-label={`${checks.filter(Boolean).length} of 5`}>
                          {checks.map((c, i) => (
                            <i key={i} className={c ? "p" : ""} style={{ transitionDelay: `${i * 40}ms` }} />
                          ))}
                        </div>
                        <div className={`c ${tone(s.momentum30d)}`}>{signed(s.momentum30d, 1, "%")}</div>
                      </Link>
                    </li>
                  );
                })}
              </Reveal>
              <Link className="ul more" href="/fleet">
                All {rows.length} scored subnets
              </Link>
            </aside>
          </div>
        </section>
      </div>

      <section className="boardsfield" aria-labelledby="boards-title">
        <div className="wrap">
          <h2 id="boards-title">Four boards</h2>
          <ul className="boards">
            {BOARDS.map((b) => (
              <li key={b.href}>
                <Link href={b.href}>
                  <span className="bn">{b.label}</span>
                  <span className="q">{b.question}</span>
                  <span className="f">{facts[b.href]}</span>
                </Link>
              </li>
            ))}
          </ul>
        </div>
      </section>

      <div className="wrap">
        <section className="sec cols" aria-label="Cold code, busy code, runtime upgrades">
          <div className="col">
            <h2>Gone cold</h2>
            <p className="cap">{counts.cold} subnets on the board stopped committing while their token kept trading. Days since the last commit.</p>
            <ul className="prows" data-ui="">
              {cold.map((s) => (
                <li key={s.netuid} className="prow">
                  <div>
                    <div className="n">{s.name}</div>
                    <div className="w">
                      SN {s.netuid} · price 30 d{" "}
                      <span className={tone(s.momentum30d)}>
                        {arrow(s.momentum30d)}
                        {signed(s.momentum30d, 1, "%")}
                      </span>
                    </div>
                  </div>
                  <div className="x fig">
                    {s.daysSinceCommit}
                    <small>d</small>
                  </div>
                </li>
              ))}
            </ul>
          </div>
          <div className="col">
            <h2>Busiest this week</h2>
            <p className="cap">Commits in the last 7 days. The line is 30 days of commits; the bright end is this week.</p>
            <Reveal as="ul" className="prows" threshold={0.2}>
              {busy.map((s) => {
                const a30 = byRow.get(s.n)?.authors30 ?? null;
                return (
                  <li key={s.n} className="prow" data-ui="">
                    <div>
                      <div className="n">{s.name}</div>
                      <div className="w">
                        {num(c7(s.daily!))} commits · {a30 ?? "no"} {a30 === 1 ? "author" : "authors"} this month
                      </div>
                    </div>
                    {spark(s.daily!)}
                  </li>
                );
              })}
            </Reveal>
          </div>
          <div className="col">
            <h2>Runtime upgrades</h2>
            <p className="cap">
              {upgrades.data.events.length} specs seen. Lately the runtime changes every {num(meanGap, 1)} days on average.
            </p>
            <Reveal as="table" className="ups">
              <caption className="sr-only">Latest runtime specs and the days between them</caption>
              <thead>
                <tr>
                  <th scope="col">Spec</th>
                  <th scope="col">Seen</th>
                  <th scope="col" className="r">
                    Days since the last
                  </th>
                </tr>
              </thead>
              <tbody>
                {specs
                  .map((e, i) => ({ e, g: gaps[i] }))
                  .slice(1)
                  .reverse()
                  .map(({ e, g }, k) => (
                    <tr key={e.newSpec}>
                      <td>{e.newSpec}</td>
                      <td>{day(e.observedAt)}</td>
                      <td className="r">
                        <span className={`gapbar${k === 0 ? " hot" : ""}`} style={{ width: Math.max(4, (g / maxGap) * 72), transitionDelay: `${k * 80}ms` }} />
                        {g}
                      </td>
                    </tr>
                  ))}
              </tbody>
            </Reveal>
          </div>
        </section>

        <section className="sec reads" id="reads" aria-labelledby="reads-title" style={{ scrollMarginTop: 32 }}>
          <div>
            <h2 id="reads-title">What it reads</h2>
            <p>Every source is read-only. A stale, partial or contradictory input is reported as unavailable, never filled in.</p>
          </div>
          <div className="rgrid">
            {reads.map(([kind, xs]) => (
              <div key={kind}>
                <h3>{kind}</h3>
                <ul>
                  {xs.map(([what, how]) => (
                    <li key={what}>
                      {what}
                      <span>{how}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </section>
      </div>
    </main>
  );
}
