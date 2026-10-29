"use client";

import Link from "next/link";
import { useRef, useState, type KeyboardEvent } from "react";
import type { FleetTier } from "@/data/types";

export interface Slot {
  netuid: number;
  name: string | null;
  tier: FleetTier | null;
  score: number | null;
  commits30: number | null;
  authors30: number | null;
  verdict: string | null;
  grossTaoMonth: number | null;
  minerBurnPct: number | null;
}

const COLS = 16;
const TIER_CLASS: Record<string, string> = {
  head: "text-tier-head",
  mid: "text-tier-mid",
  quiet: "text-tier-quiet",
  none: "text-tier-none",
};
const TIER_WORD: Record<string, string> = {
  head: "at the head of the fleet board",
  mid: "in the middle of the fleet board",
  quiet: "quiet on the fleet board",
  none: "not scored: no public repository",
};

const fmt = (v: number | null, unit = "") => (v === null ? "-" : `${v.toLocaleString("en-GB")}${unit}`);

// The live thing: pick a subnet slot and read its row across the boards.
// Each cell is a plain link to the fleet board, so it works without script.
export function SubnetPicker({ slots, initial }: { slots: Slot[]; initial: number }) {
  const [selected, setSelected] = useState(initial);
  const refs = useRef<(HTMLAnchorElement | null)[]>([]);
  const index = slots.findIndex((s) => s.netuid === selected);
  const slot = slots[index] ?? slots[0];
  const tier = slot.tier ?? "none";

  function onKey(e: KeyboardEvent, i: number) {
    const step = { ArrowRight: 1, ArrowLeft: -1, ArrowDown: COLS, ArrowUp: -COLS }[e.key];
    if (!step) return;
    e.preventDefault();
    const next = Math.min(slots.length - 1, Math.max(0, i + step));
    setSelected(slots[next].netuid);
    refs.current[next]?.focus();
  }

  return (
    <div data-ui="" className="w-full bg-card p-5 text-ink sm:p-6 lg:w-[620px]">
      <div className="flex items-baseline justify-between gap-4 text-small text-muted">
        <span id="field-label">128 subnet slots, by fleet tier</span>
        <span>{slots.filter((x) => x.tier).length} scored</span>
      </div>
      <div className="mt-3 flex flex-col gap-6 sm:flex-row">
        <div
          role="group"
          aria-labelledby="field-label"
          className="grid w-full max-w-[336px] shrink-0 gap-[3px]"
          style={{ gridTemplateColumns: `repeat(${COLS}, minmax(0, 1fr))` }}
        >
          {slots.map((s, i) => {
            const t = s.tier ?? "none";
            const on = s.netuid === slot.netuid;
            return (
              <a
                key={s.netuid}
                ref={(el) => {
                  refs.current[i] = el;
                }}
                href={`/fleet#sn${s.netuid}`}
                tabIndex={on ? 0 : -1}
                aria-label={`Subnet ${s.netuid}${s.name ? `, ${s.name}` : ""}, ${TIER_WORD[t]}`}
                aria-current={on ? "true" : undefined}
                onClick={(e) => {
                  e.preventDefault();
                  setSelected(s.netuid);
                }}
                onKeyDown={(e) => onKey(e, i)}
                className={`aspect-square bg-current transition-transform hover:scale-125 ${TIER_CLASS[t]} ${
                  on ? "outline-2 outline-offset-1 outline-ink" : ""
                }`}
              />
            );
          })}
        </div>

        <div className="min-w-0 flex-1" aria-live="polite">
          <p className="text-lead font-bold leading-tight">
            SN{slot.netuid} {slot.name ?? "unnamed"}
          </p>
          <p className="pt-1 text-small text-muted">{TIER_WORD[tier]}</p>
          <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3 text-small">
            <div>
              <dt className="text-muted">Fleet score</dt>
              <dd className="text-body">{fmt(slot.score)}</dd>
            </div>
            <div>
              <dt className="text-muted">Commits, 30 d</dt>
              <dd className="text-body">{fmt(slot.commits30)}</dd>
            </div>
            <div>
              <dt className="text-muted">Mining code</dt>
              <dd className="text-body">{slot.verdict ?? "-"}</dd>
            </div>
            <div>
              <dt className="text-muted">Gross, TAO/mo</dt>
              <dd className="text-body">{fmt(slot.grossTaoMonth)}</dd>
            </div>
          </dl>
        </div>
      </div>
      <p className="mt-5 flex gap-6 text-small">
        <Link href={`/fleet#sn${slot.netuid}`} className="underline underline-offset-4">
          On the fleet board
        </Link>
        <Link href={`/mining#sn${slot.netuid}`} className="underline underline-offset-4">
          On the mining board
        </Link>
      </p>
    </div>
  );
}
