import type { Metadata } from "next";
import { Figures } from "@/components/board-shell";
import { BoardHeader } from "@/components/board-header";
import { MiningTable } from "@/components/boards/mining-table";
import { getMining } from "@/data/mining";
import { headline, order, readBlock } from "@/lib/mining";

export const metadata: Metadata = { title: "Mining triage" };

export default async function MiningPage() {
  const { generatedAt, data } = await getMining();
  const rows = order(data);
  const block = readBlock(rows);
  const fullBurn = rows.filter((r) => (r.minerBurnPct ?? 0) >= 99.95).length;
  const at = block === null ? "the read block's spot price" : `the spot price at block ${block.toLocaleString("en-GB")}`;

  const notes = [
    ["Rank", "Atlas's order for one new independent miner, after hardware cost at a band it does not publish. Cut subnets follow, with the reason."],
    ["Model estimate", `Not a quote: what one new miner would earn a month if paid like the lower quarter of today's independent miners, or an equal share if that is lower. Valued at ${at}, after the slippage of selling the subnet's daily emission. Before hardware cost. A dash means Atlas has no honest figure.`],
    ["Code", "From a scan of the miner code. Atlas never runs it. \"No GPU code found\" means the scan found none, not that a CPU is enough."],
    ["Burn", `Share of miner emission the subnet burns. ${fullBurn} subnets burn all of it.`],
    ["Top earner", "Share taken by the single largest miner, not counting the subnet owner."],
  ];

  return (
    <>
      <BoardHeader title="Mining triage" finding={headline(rows)} at={generatedAt} />
      <MiningTable rows={rows} />
      <div className="mt-[clamp(72px,9vw,120px)] grid gap-12 lg:grid-cols-[4fr_8fr] lg:gap-16">
        <Figures
          items={[
            { value: rows.filter((r) => r.rank !== null).length, label: "ranked by Atlas" },
            { value: rows.filter((r) => r.verdict === "possible").length, label: "with no GPU code found" },
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
