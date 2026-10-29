import type { Metadata } from "next";
import { Block, BoardShell } from "@/components/board-shell";
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

  return (
    <BoardShell>
      <BoardHeader title="Mining triage" finding={finding} at={generatedAt} />
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_280px] lg:items-start">
        <Block title="Where a new miner could earn">
          <MiningTable rows={rows} />
        </Block>
        <div className="flex min-w-0 flex-col gap-4 lg:sticky lg:top-6">
          <Block title="How to read it">
            <dl className="space-y-3 text-small">
              <div>
                <dt className="text-ink">Burn</dt>
                <dd className="text-muted">Share of miner emission the subnet burns. {fullBurn} subnets burn all of it.</dd>
              </div>
              <div>
                <dt className="text-ink">Top earner</dt>
                <dd className="text-muted">Share taken by the single largest miner.</dd>
              </div>
              <div>
                <dt className="text-ink">Gross</dt>
                <dd className="text-muted">What one new slot would earn a month before costs. A dash means Atlas has no honest figure.</dd>
              </div>
              <div>
                <dt className="text-ink">Caveat</dt>
                <dd className="text-muted">Why the gross may not reach a newcomer, such as an owner who takes most of it.</dd>
              </div>
              <div>
                <dt className="text-ink">Code</dt>
                <dd className="text-muted">From a scan of the miner code. Atlas never runs it.</dd>
              </div>
            </dl>
          </Block>
        </div>
      </div>
    </BoardShell>
  );
}
