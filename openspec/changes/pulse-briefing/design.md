## Context

See proposal.md, Why. The notifier runs hourly as an `ExecStartPost` on the
repotrack unit, after the chain-head and gate polls, and consumes every
source read-only past a durable watermark. Classes are configured in
`telegram/config.json`; the render path is house-style HTML with a plain
fallback and a 3,500-character cap. Livedata already fetches the TaoSwap
panel hourly, computes demand shares, and persists gate state and events.
The fleet pass runs every six hours and owns prices, economics, activity,
adoptions, verdicts, and the mining board. The voice canon requires the last
line to be the next action or the last fact.

Constraints: no new unit, port, credential, or provider; tests off-device
under `unittest`; the Pi is acceptance; the Telegram cap forces bounded
output; nothing in the briefing may be a model-generated number.

## Goals / Non-Goals

**Goals:**

- One daily message the operator reads, one weekly message with trend.
- Instant pages only for events where a day of latency costs something.
- Every alerting behaviour reversible by configuration.
- Zero new provider quota.

**Non-Goals:**

- Model-written prose. A later change may add a two-sentence summary through
  the locked-down Hermes one-shot; this change ships a deterministic
  template so the briefing can be trusted on autopilot.
- A personal watchlist or reaction-based feedback.
- Changing the attention board or mining board rendering.
- Deciding the mining budget band.

## Decisions

**D1. Briefing lives in the notifier, gated by watermarks, not a new unit.**
The hourly scan already runs; a `briefing` step checks the configured hour
and a per-edition watermark (`briefing:daily:<date>`,
`briefing:weekly:<iso-week>`) in the ledger. A missed hour catches up on the
next scan that day. Alternative: a dedicated timer. Rejected: a second unit
needs sudo to install, and the once-per-day guarantee is a watermark either
way.

**D2. Snapshot the panel in livedata, in the gate poll's pass.** The poll
already validates the panel and computes shares; persisting a bounded row
set per pass costs no call. Retention 90 days (about 280k rows at 128
subnets hourly, tens of MB), pruned per pass. Alternative: have the notifier
read the response cache. Rejected: the cache holds one payload per
operation, so no history.

**D3. Deltas compare editions, movers compare window ends.** Figures with a
single current value (theta, spec, quota) compare against the previous
edition's persisted figure set, stored in the ledger as JSON per edition.
Movers (price, share, flow) compare the newest snapshot against the first
snapshot at or after the window start. This avoids re-deriving yesterday's
briefing and makes the first edition explicit.

**D4. Tier is a class field, not a separate allowlist.** Each class gets
`"tier": "instant" | "briefing"`. Routing sits in one place in the scan;
the class builders are unchanged so an operator flipping a tier back gets
exactly today's message. Briefed events get a new ledger status `briefed`
so the ledger stays the single record and de-dup keeps working.

**D5. Runtime merge reads the repository store, does not wait for it.** The
upgrade page joins `spec_upgrades` to `change_ranges` on the spec delta at
render time. Both clocks are hourly and the repo range often lands the same
hour; when it has not, the message says so and the briefing's network
section fills the subject the next day. Alternative: hold the upgrade page
until the range exists. Rejected: the live-chain event is the fact worth
paging on time.

**D6. Hovering is decided in livedata, consumed downstream.** A count of
crossings per netuid in a rolling window (default: more than 2 in 7 days)
sets a flag on `gate_sides`; events written while flagged carry
`hovering=1`. The notifier and briefing read the annotation. Alternative:
widen hysteresis for everyone. Rejected: SN9's 5.6x share swings are
genuine, and a band wide enough to hold it would hide real crossings on
stable subnets. The calibration read's own note pointed this way.

**D7. Judge anchors are configuration rendered into the prompt.** The four
definitions live in `fleet/config.json` under the judge block and are
injected verbatim, so a future re-anchoring is a config change with a
recorded diff. The spec fixes the meaning; the config fixes the words.

**D8. Section priority for truncation, lowest first:** narrative, code,
mining, atlas, subnets; network is never cut. Whole lines only, with an
"n lines omitted" trailer. Two messages maximum by default.

**D9. Subnet-registry detection from the snapshot set.** A netuid appearing
or disappearing between consecutive snapshots, or a chain-name change, pages
at instant tier. The panel is the same source the gate poll trusts, and the
first snapshot seeds silently. Dereg risk (`risk_level`, `prune_rank`,
`is_immune`) is a briefing line, not a page.

**D10. Fail-closed page is a health-store read.** One message when a
component's `integration_health` shows only failures for longer than a
configured window (default 6 hours), keyed by outage start so it pages once
per outage.

## Risks / Trade-offs

- [The operator misses a real cliff event because gate crossings no longer
  page] → Crossings still record and appear next morning as movers; the
  tier flip is one config line; a watchlist is the right future fix, not a
  wider instant list.
- [Snapshot growth on the Pi's NVMe] → 90-day prune per pass; size checked
  in acceptance and recorded.
- [The briefing overflows two messages on a busy week] → Priority
  truncation with an explicit omission count; weekly edition allowed three
  messages.
- [Anchored rubric still over-rates] → The weekly atlas line reports the
  verdict distribution; a second anchoring is a config change. Target: high
  under 5 per week.
- [Vitals endpoints drift] → They already pass contract validation; a
  failure records health and the line says unavailable.
- [The delta JSON in the ledger diverges from the sections over time] →
  Figure keys are versioned with the briefing template; an unknown key
  renders no delta rather than a wrong one.

## Migration Plan

1. Off-device: livedata snapshot, vitals, zero-price and hovering rules;
   notifier tiers, briefing builder, runtime merge, registry and
   fail-closed classes; judge anchors and routing; all suites green.
2. Push; `git pull` on the Pi. Snapshot and vitals begin on the next hourly
   pass; the first snapshot seeds the registry set silently.
3. Ship with all tiers at today's values (everything instant) and the
   briefing enabled. Read two daily editions (the first has no deltas).
4. Flip the six classes to `briefing` in one commit. Rollback for any class
   is its tier field; rollback for the briefing is `enabled: false`.
5. Record the first weekly edition and the instant count for the week in
   the decision log; close the gate calibration read with the hovering
   evidence.

## Open Questions

- Whether the weekly edition should carry the effectiveness-ledger line
  (signal picks versus fleet median at 30 days). The data exists; adding the
  line later changes no spec.
- The exact hour and weekday. Config values; default 07:00 local and
  Sunday.
