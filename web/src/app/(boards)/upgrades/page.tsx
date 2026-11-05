import type { Metadata } from "next";
import { BoardHeader } from "@/components/board-header";
import { getUpgrades } from "@/data/upgrades";
import type { Release } from "@/data/types";
import { day, mean as avg, num } from "@/lib/format";
import { AREAS, bundledText, chainFiles, heat, HEAT_STEPS } from "@/lib/upgrades";

export const metadata: Metadata = { title: "Runtime upgrades" };

const DAY_MS = 86_400_000;
const MAP_ROWS = 12;
const HEAT = ["bg-s2", "bg-accent/20", "bg-accent/45", "bg-accent/70", "bg-accent"] as const;

export default async function UpgradesPage() {
  const { generatedAt, data } = await getUpgrades();
  const events = data.events;
  if (!events.length) {
    return <BoardHeader title="Runtime upgrades" finding="No runtime upgrade is recorded in this window." at={generatedAt} />;
  }
  const first = events[0];
  const last = events[events.length - 1];
  const spanDays = (Date.parse(last.observedAt) - Date.parse(first.observedAt)) / DAY_MS;
  const gaps = events.slice(1).map((e, i) => (Date.parse(e.observedAt) - Date.parse(events[i].observedAt)) / DAY_MS);
  const mean = avg(gaps);
  const longest = gaps.length ? Math.max(...gaps) : null;

  const bySpec = new Map(data.releases.filter((r) => !r.pending).map((r) => [r.spec, r]));
  const pending = data.releases.find((r) => r.pending) ?? null;
  const finding =
    `${events.length} runtime upgrades in ${Math.round(spanDays)} days${mean === null ? "" : `, one every ${num(mean, 1)} days on average`}. ` +
    (pending ? `The chain runs spec ${last.newSpec}; spec ${pending.spec} is merged and waiting.` : `The latest is spec ${last.newSpec}, on ${day(last.observedAt)}.`);

  const log = events
    .map((e, i) => ({ e, gap: i === 0 ? null : gaps[i - 1], r: bySpec.get(e.newSpec) ?? null }))
    .reverse();
  const maxChain = Math.max(1, ...data.releases.map(chainFiles));
  const mapRows: { label: string; sub: string; r: Release }[] = [
    ...(pending ? [{ label: String(pending.spec), sub: "waiting", r: pending }] : []),
    ...log.filter((x) => x.r).map((x) => ({ label: String(x.e.newSpec), sub: day(x.e.observedAt), r: x.r as Release })),
  ].slice(0, MAP_ROWS);

  const lines = (r: Release) => [r.headline2, r.headline3].filter((h): h is string => Boolean(h));
  const chips = (r: Release) => AREAS.filter((a) => r[a.key] > 0).map((a) => a.label);

  return (
    <>
      <BoardHeader title="Runtime upgrades" finding={finding} at={generatedAt} />

      {pending ? (
        <section aria-labelledby="pending-title" className="grid gap-6 rounded-[10px] border-l-[3px] border-accent bg-s1 p-6 sm:grid-cols-[auto_1fr_auto] sm:items-center">
          <div>
            <h2 id="pending-title" className="text-small uppercase tracking-[0.08em] text-accent">
              Merged, waiting
            </h2>
            <div className="num mt-1 font-display text-[clamp(40px,5vw,56px)] leading-none">{pending.spec}</div>
          </div>
          <div className="min-w-0">
            <p className="text-lead">{pending.headline ?? "No feature or fix commits recorded"}</p>
            <p className="mt-1 text-small text-ink-3">
              In the repository since {day(pending.since)}, not on chain yet.
              {pending.bundled ? ` Includes spec${pending.bundled.includes(",") ? "s" : ""} ${pending.bundled}.` : ""}
            </p>
            <ul className="mt-3 flex flex-wrap gap-1.5">
              {chips(pending).map((c) => (
                <li key={c} className="rounded-full border border-rule px-2.5 py-0.5 text-small text-ink-2">{c}</li>
              ))}
            </ul>
          </div>
          <div className="num sm:text-right">
            <div className="text-lead">{num(pending.files)}</div>
            <div className="text-small text-ink-3">files changed</div>
          </div>
        </section>
      ) : null}

      <section aria-labelledby="map-title" className="mt-[clamp(56px,7vw,96px)]">
        <h2 id="map-title" className="font-display text-sub leading-none">
          What each upgrade touched
        </h2>
        <p className="mt-4 max-w-[60ch] text-body text-ink-2">
          Files changed in each part of the subtensor code, per upgrade. Runtime, pallets, EVM and node change how the chain behaves; SDK, docs and
          tooling do not.
        </p>
        <div className="mt-8">
          <div className="grid grid-cols-[52px_repeat(7,minmax(0,1fr))_36px] items-center gap-1 sm:grid-cols-[96px_repeat(7,minmax(0,1fr))_64px]" role="table" aria-label="Files changed per area, per upgrade">
            <div role="row" className="contents">
              <div role="columnheader" className="pb-2 text-small text-ink-3">Spec</div>
              {AREAS.map((a) => (
                <div key={a.key} role="columnheader" className="pb-2 text-center text-small text-ink-3">
                  <span className="sm:hidden">{a.short}</span>
                  <span className="hidden sm:inline">{a.label}</span>
                </div>
              ))}
              <div role="columnheader" className="pb-2 text-right text-small text-ink-3">Files</div>
            </div>
            {mapRows.map(({ label, sub, r }) => (
              <div key={label} role="row" className="contents">
                <div role="rowheader" className="num leading-tight">
                  {label}
                  <span className={`block text-small ${r.pending ? "text-accent" : "text-ink-3"}`}>{sub}</span>
                </div>
                {AREAS.map((a) => (
                  <div
                    key={a.key}
                    role="cell"
                    title={`${a.label}: ${num(r[a.key])} files`}
                    aria-label={`${a.label}: ${num(r[a.key])} files`}
                    className={`h-9 rounded-[3px] ${HEAT[heat(r[a.key])]}`}
                  />
                ))}
                <div role="cell" className="num text-right text-small text-ink-2">
                  {num(r.files)}
                </div>
              </div>
            ))}
          </div>
        </div>
        <p className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-2 text-small text-ink-3">
          <span>Files:</span>
          {HEAT.map((cls, i) => (
            <span key={cls} className="inline-flex items-center gap-1.5">
              <i className={`inline-block h-3 w-5 rounded-[2px] ${cls}`} />
              {i === 0 ? "0" : i === HEAT.length - 1 ? `${HEAT_STEPS[i]}+` : `${HEAT_STEPS[i]} to ${HEAT_STEPS[i + 1] - 1}`}
            </span>
          ))}
        </p>
      </section>

      <dl className="mt-[clamp(56px,7vw,96px)] grid gap-4 sm:grid-cols-3">
        {[
          { value: num(events.length), label: `upgrades in ${Math.round(spanDays)} days` },
          { value: num(mean, 1), label: "days between upgrades, on average" },
          { value: num(longest, 1), label: "days in the longest quiet stretch" },
        ].map((k) => (
          <div key={k.label} className="rounded-[10px] bg-s1 px-5 py-4">
            <dd className="num font-display text-[clamp(36px,4vw,48px)] leading-none">{k.value}</dd>
            <dt className="mt-2 text-small text-ink-2">{k.label}</dt>
          </div>
        ))}
      </dl>

      <section aria-labelledby="log-title" className="mt-[clamp(56px,7vw,96px)]">
        <h2 id="log-title" className="font-display text-sub leading-none">
          Every upgrade, newest first
        </h2>
        <p className="mt-4 max-w-[60ch] text-body text-ink-2">
          The main changes are the release&apos;s own commit titles, with merges, version bumps and build fixes left out. The bar is chain code
          files changed.
        </p>
        <ol className="mt-8">
          {log.map(({ e, gap, r }) => (
            <li key={e.newSpec} className="grid gap-x-6 gap-y-3 border-t border-rule py-6 sm:grid-cols-[120px_1fr_200px]">
              <div>
                <div className="num font-display text-[28px] leading-none">{e.newSpec}</div>
                <div className="num mt-1.5 text-small text-ink-3">{day(e.observedAt)}</div>
                {gap === null ? null : <div className="num text-small text-ink-3">{num(gap, 1)} days later</div>}
              </div>
              <div className="min-w-0">
                {r ? (
                  <>
                    <p className="text-lead leading-snug">{r.headline ?? "No feature or fix commits recorded"}</p>
                    {lines(r).length ? (
                      <ul className="mt-1.5 grid gap-1 text-body text-ink-2">
                        {lines(r).map((l) => (
                          <li key={l}>{l}</li>
                        ))}
                      </ul>
                    ) : null}
                    {bundledText(r.bundled) ? <p className="mt-1.5 text-small text-accent">{bundledText(r.bundled)}</p> : null}
                    <ul className="mt-3 flex flex-wrap gap-1.5">
                      {chips(r).map((c) => (
                        <li key={c} className="rounded-full border border-rule px-2.5 py-0.5 text-small text-ink-2">{c}</li>
                      ))}
                    </ul>
                  </>
                ) : (
                  <p className="text-ink-2">No repository record for this upgrade.</p>
                )}
                <p className="num mt-3 text-small text-ink-3">
                  {e.prevSpec === null ? "" : `From spec ${e.prevSpec} · `}
                  {e.block === null ? "block -" : `block ${e.block.toLocaleString("en-GB")}`}
                </p>
              </div>
              {r ? (
                <div className="num">
                  <div className="text-small text-ink-2">
                    {r.partial ? "at least " : ""}
                    {num(chainFiles(r))} chain files · {num(r.files)} in all
                  </div>
                  <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-s2">
                    <i className="block h-full bg-accent" style={{ width: `${Math.max(1, (100 * chainFiles(r)) / maxChain)}%` }} />
                  </div>
                  <div className="mt-2 text-small text-ink-3">
                    {num(r.commits)} commits · +{num(r.adds)} / −{num(r.dels)} lines
                  </div>
                </div>
              ) : (
                <div />
              )}
            </li>
          ))}
        </ol>
      </section>
    </>
  );
}
