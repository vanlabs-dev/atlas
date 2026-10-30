"use client";

import { useSyncExternalStore } from "react";
import { freshness, STALE_AFTER_HOURS } from "@/data/freshness";

// The page is static, so the age is computed in the browser, to the minute.
// The server and the first paint show the produced time on its own.
const MINUTE = 60_000;
const subscribe = (tick: () => void) => {
  const id = setInterval(tick, MINUTE);
  return () => clearInterval(id);
};
const currentMinute = () => Math.floor(Date.now() / MINUTE);
const noMinute = () => null;

export function DataAge({ at }: { at: string }) {
  const minute = useSyncExternalStore(subscribe, currentMinute, noMinute);
  const now = minute === null ? null : new Date(minute * MINUTE);

  const produced = new Date(at).toLocaleString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
    timeZoneName: "short",
  });
  const f = now ? freshness(at, now) : null;

  return (
    <p className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-small text-ink-3">
      <span>
        Data from <time dateTime={at}>{produced}</time>
        {f ? `, ${f.label}` : null}
      </span>
      {f?.stale ? (
        <span
          className="rounded-[4px] bg-down px-1.5 font-medium text-ground"
          title={`Older than ${STALE_AFTER_HOURS} hours`}
        >
          Stale
        </span>
      ) : null}
    </p>
  );
}
