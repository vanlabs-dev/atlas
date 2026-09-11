# Pulse Briefing

## Why

The Telegram channel delivered 333 alerts between 2026-07-12 and 2026-08-31,
about 45 a week lately, and the operator reads none of them. The delivery
ledger and the source stores show why: 55% were `econ-code` pages (182,
about two a day, because the judge rates 64% of every scoring-file diff as
`high` or `med` against a rubric that defines neither word); 18% were
`gate-crossing` pages, of which 36 of 78 happened within 25% of theta (the
same subnets hovering: SN9 crossed 13 times) and 9 carried a share of
exactly zero (a panel gap, not demand vanishing); `repository-update` pages
open with "not verified effect"; and `chain-runtime-upgrade` says "450 to
452" while the release subject that explains it sits unread in the repo
store. Meanwhile the four events that changed the network this summer (Root
Reborn curation switching on, the first subnet arming miner collateral, two
release trains) arrived shaped exactly like the noise.

The operator's stated need is a finger on the Bittensor and subnet pulse. A
pulse is a state sampled on a rhythm and read as change since the last
sample, not an event stream. Atlas already stores the state: 820 hourly
theta readings, 19,866 alpha prices, 11,520 per-subnet economics rows, 6,944
model and dependency adoptions, commit cadence for 104 clones, and a
40-field panel per subnet fetched hourly and discarded. What is missing is
the vessel, and one small table.

## What Changes

- **A daily pulse briefing** as a new Telegram message class, composed from
  stores only, at a configured hour, with a longer weekly edition on a
  configured weekday. Fixed sections in fixed order: network (runtime and
  release subject, rule switches, theta and above-bar count, TAO/USD, total
  staked, subnet stake share, new accounts), subnets over 7 days (alpha price
  movers, demand-share movers, capital flow, dereg watch, contested
  ownership), code (subnets that pushed, material incentive changes,
  re-points), narrative (model-id adoptions and clusters), mining board
  (head, entries and exits), atlas (providers, cross-check status, quota,
  last ingest). Every line is a recorded fact with a delta against the
  previous edition; lines whose inputs are missing say so or are omitted,
  never estimated. The last line is the next action or the board link.
- **Delivery tiers.** Every class carries a tier: `instant` or `briefing`.
  Instant by default: `chain-runtime-upgrade`, `chain-parameter-change`, a
  new subnet-registry event (a netuid appearing, disappearing, or changing
  identity), and an Atlas fail-closed condition persisting beyond a
  configured window. Everything else (`econ-code`, `gate-crossing`,
  `repository-update`, `fleet-signal` digests, `schema-drift`,
  `knowledge-ingestion`) becomes briefing input. Historical instant rate
  under this split: about one a week.
- **Runtime upgrade carries meaning.** The `chain-runtime-upgrade` message
  states the release subject and top touched areas from the matching
  repository range when one is recorded, so one message explains the upgrade
  instead of two that explain nothing.
- **A per-poll panel snapshot** in livedata: for each subnet, each hourly
  pass persists the computed demand share and the panel fields the briefing
  reads (moving and spot price, emission share and its 1d/30d evolution,
  inflow, outflow, 24h volume, holders, market cap, active miners, miner
  burn, dereg risk and prune rank, contested and takeover flags, name).
  Bounded retention. Two keyless daily calls persist network vitals
  (`network_stats`, `price_daily`). No TaoStats quota is used.
- **Gate crossing stops flapping.** A zero moving price is a missing
  observation for side tracking, not a crossing to zero. A subnet that
  crosses more than a configured number of times inside a configured window
  is flagged as hovering; its crossings are recorded with that annotation
  and reported as a count in the briefing, not individually.
- **The judge gets a scale.** The prompt defines `high` (changes who is paid
  or how much, visibly within an epoch, in the weight or emission path),
  `med` (changes scoring inputs or parameters without changing the payout
  path), `low` (refactors or tests in scoring files), `none` (cosmetic), with
  the same anchors recorded in the spec. All verdicts route to the briefing
  (high listed with its one-line verdict, med counted, low and none dropped
  from the briefing but kept in the store). The high-stakes floor keeps its
  meaning as "never dropped from the store or the count".
- **Class demotions are configuration.** Each class's tier is a config
  field; setting any class back to `instant` restores today's behaviour for
  that class. The briefing itself has an `enabled` flag.

Not breaking for stores: all tables are additive. Breaking for the operator's
inbox by design: six classes stop paging.

## Capabilities

### New Capabilities

- `pulse-briefing`: a scheduled Telegram briefing composed from recorded
  state only, with fixed sections, deltas against the previous edition,
  bounded size, and a weekly edition.

### Modified Capabilities

- `live-data`: per-poll panel snapshot with computed demand share and
  bounded retention; daily network vitals; a zero moving price is a missing
  observation for side tracking; hovering subnets are flagged and their
  crossings annotated.
- `telegram-integration`: classes carry a delivery tier and only `instant`
  classes page; the runtime-upgrade message carries the release subject and
  touched areas; the gate-crossing and fleet-signal class requirements are
  restated at briefing tier by default; a subnet-registry instant class is
  added.
- `econ-alert-intelligence`: the verdict scale is anchored in the prompt and
  the spec; routing sends verdicts to the briefing instead of paging, with
  the high-stakes floor preserved as a never-dropped guarantee.

## Impact

- **Code:** `telegram/atlas_telegram.py` (briefing builder, tier routing,
  once-per-day and once-per-week watermarks, runtime merge, subnet-registry
  class), `telegram/config.json` (tiers, briefing schedule and section
  config), `livedata/atlas_live.py` (`panel_snapshot`, `network_vitals`,
  zero-price handling, hovering flag, two daily calls),
  `livedata/config.json`, `fleet/atlas_econ_judge.py` (rubric),
  `fleet/atlas_fleet_signals.py` (routing), tests in all three suites.
- **Store:** `var/livedata/livedata.db` gains `panel_snapshot` (bounded) and
  `network_vitals`; `var/telegram/telegram.db` gains briefing watermarks.
- **External load:** two keyless TaoSwap calls per day. Zero TaoStats quota.
- **Schedule:** no new unit. The briefing runs inside the hourly `scan` when
  the configured hour is reached and the day's watermark is unset.
- **Docs:** `telegram/README.md`, `README.md`, `docs/decisions.md` (the
  overdue gate calibration read is closed by the hovering rule and the
  evidence above).
- **Out of scope:** model-written prose in the briefing, a personal
  watchlist, reaction-based feedback, and the mining `budget_band` decision.
