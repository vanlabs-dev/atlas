import type { Metadata } from "next";
import { Figures } from "@/components/board-shell";
import { BoardHeader } from "@/components/board-header";
import { MiningTable } from "@/components/boards/mining-table";
import { getMining } from "@/data/mining";
import { num } from "@/lib/format";

export const metadata: Metadata = { title: "Mining triage" };

export default async function MiningPage() {
  const { generatedAt, data } = await getMining();
  const rows = [...data].sort((a, b) => (b.grossTaoMonth ?? -1) - (a.grossTaoMonth ?? -1));
  const cpu = rows.filter((r) => r.verdict === "possible");
  const best = cpu.find((r) => r.grossTaoMonth !== null);
  const fullBurn = rows.filter((r) => (r.minerBurnPct ?? 0) >= 99.95).length;

  const finding = best
    ? `${cpu.length} of ${rows.length} subnets have miner code that runs on a CPU. The highest gross among them is SN${best.netuid} ${best.name}, at ${num(best.grossTaoMonth, 1)} TAO a month.`
    : `${rows.length} subnets priced for a new miner.`;

  const notes = [
    ["Burn", `Share of miner emission the subnet burns. ${fullBurn} subnets burn all of it.`],
    ["Top earner", "Share taken by the single largest miner."],
    ["Gross", "What one new slot would earn a month before costs. A dash means Atlas has no honest figure."],
    ["Caveat", "Why the gross may not reach a newcomer, such as an owner who takes most of it."],
    ["Code", "From a scan of the miner code. Atlas never runs it."],
  ];

  return (
    <>
      <BoardHeader title="Mining triage" finding={finding} at={generatedAt} />
      <MiningTable rows={rows} />
      <div className="mt-[clamp(72px,9vw,120px)] grid gap-12 lg:grid-cols-[4fr_8fr] lg:gap-16">
        <Figures
          items={[
            { value: cpu.length, label: "with miner code that runs on a CPU" },
            { value: rows.filter((r) => r.verdict === "needs-gpu").length, label: "that need a GPU" },
            { value: fullBurn, label: "that burn all miner emission" },
          ]}
        />
        <section aria-labelledby="read-title">
          <h2 id="read-title" className="font-display text-sub leading-none">
            How to read it
          </h2>
          <dl className="mt-8 grid gap-x-12 gap-y-6 sm:grid-cols-2">
            {notes.map(([term, text]) => (
              <div key={term}>
                <dt className="font-medium">{term}</dt>
                <dd className="mt-1 text-ink-2">{text}</dd>
              </div>
            ))}
          </dl>
        </section>
      </div>
    </>
  );
}
