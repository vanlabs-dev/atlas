# Rotation Signal Gate

## Why

Atlas pages about 6.6 times a day and the operator reports the stream is not
useful. Atlas already measured this and nobody read the measurement. The
effectiveness ledger built by `fleet-signals` (2026-07-19) reports, over every
signal since it was deployed, that `econ-code` has no edge against the fleet
baseline:

| econ-code | n | median signal | median baseline | edge |
|---|---:|---:|---:|---:|
| 1 day | 212 | -0.278% | -0.305% | +0.03pp |
| 7 day | 185 | -2.175% | -1.873% | **-0.30pp** |
| 30 day | 109 (108 pending) | -4.275% | -7.625% | +3.35pp, half-filled |

`econ-code` is 106 of the 199 alerts delivered in the last 30 days. At n=185
and n=212 it is indistinguishable from the baseline at one day and worse at
seven. The 30-day row cannot be read yet: half its outcomes are pending and
only the older, selected half has matured.

The routing is decoupled from the judge's own reasoning. Of 189 econ verdicts
in 30 days, 121 route to `instant` and 108 of those are `reshuffle`; only 2
claimed an emission direction. Their `why_it_matters` contradicts the tier
they were given: "the diff shows no caller activating this allocation"
(netuid 67, med, paged), "the diff shows no direct reward or emission change"
(netuid 14, med, paged), "without showing changes to reward amounts or the
payout path" (netuid 71, med, paged). `reshuffle` is intra-subnet miner
ranking. The operator is not mining those subnets.

`gate-crossing` is structurally noisy rather than badly tuned. 55 crossings in
30 days across 25 netuids, **18 of them reversing within 48 hours**, and 9
netuids producing 33 of the 55. The bar is pinned to rank 32, so a subnet is
always marginal by construction. A crossing at the bar is a state, not an
event, and hysteresis cannot fix a detector pointed at the wrong thing.

Meanwhile the largest observable rotation signal on the network is unread.
Root stake is 5,290,553 TAO of 7,313,368 staked (72%, `network_vitals`
2026-09-08) and since spec 449 (2026-08-27) its dividends are directed by
public per-validator `set_root_weights` vectors, capped at 1/16 per
destination. `grep` across `livedata/`, `fleet/`, `telegram/` and `knowledge/`
finds no read of `Weights[ROOT]`. Atlas watches the master switch and the cap
and is blind to what curation does with them.

The operator has stated the purpose of the alert stream: **capital rotation**.
Every class must earn its place against that, measured, or not page.

## What Changes

- **A shared effectiveness ledger, lifted out of `fleet-signals`.** The
  measurement machinery (`_ensure_measurement_rows`,
  `fleet/atlas_fleet_signals.py:1311`) is already class-agnostic: it keys on
  any `instant` event, resolves netuid members, snapshots an entry price
  through the live-data layer and fills outcome rows against a fleet baseline
  over identical windows. It is wired only to `signal_events`. Any
  netuid-scoped alert class becomes eligible to feed it.
- **A `shadow` tier, and a promotion rule.** A netuid-scoped class in `shadow`
  records and is measured but never pages. It is promoted to `instant` only by
  an explicit operator decision taken against a filled 7-day ledger read that
  beats the fleet baseline. This inverts today's default, where a class ships
  on plausibility and is measured never.
- **Demotions from the evidence already collected.** `econ-code` drops from
  `instant` to `briefing`: it keeps recording, keeps its ledger rows maturing,
  keeps riding the daily pulse, and stops paging. `subnet-registry` renames
  drop to `briefing`. Neither is deleted, so both can still prove the call
  wrong.
- **Gate-crossing pages durable side changes only.** A confirmed crossing that
  reverses within a configured window is recorded and never paged, and the
  briefing carries a standing "at the bar" line instead. Detection, hysteresis
  and the existing per-netuid cooldown are unchanged.
- **Root weight vectors become a watched chain read.** At the existing hourly
  gate-poll block, over the same keyless finney RPC: one `state_getKeys` on
  the `Weights` prefix at netuid 0, then one `state_queryStorageAt` for every
  returned key at the finalized head. Verified live 2026-09-09 at block
  0xab6d1b7b: 20 validator entries, 1833 payload bytes, 96 distinct
  destination netuids, largest aggregate destination 5.24% against the 6.25%
  cap. `state_getPairs` is refused by the public endpoint (code 4003) and is
  not used.
- **A `root-rotation` alert class, starting in `shadow`.** Per-validator
  vectors and the aggregate destination map are stored per pass; a material
  shift in the aggregate mix records an event and enters the ledger. It does
  not page until it has earned promotion under the rule above.

Not breaking for any store: additive tables and columns, tier changes in
config, one new chain read. No new provider, credential, port, service or
model. `mining-triage` and the `fail-closed` schedule gap are explicitly out
of scope.

## Capabilities

### New Capabilities

- `signal-effectiveness-gate`: the shared, class-agnostic measurement ledger;
  the `shadow` tier; the promotion rule that an operator decision against a
  filled ledger read is the only path from `shadow` to `instant`; and the
  requirement that a demoted class keeps recording and keeps being measured.

### Modified Capabilities

- `live-data`: a new requirement for reading per-validator root weight vectors
  at the gate-poll finalized block through the existing batched multi-key read
  and derived-key self-test, and storing the per-validator vectors plus the
  aggregate destination map; and a modification to "Gate-crossing events are
  durable, hysteresis-guarded, and lifecycle-safe" so a crossing that reverses
  inside the durability window is recorded but not eligible to page.
- `fleet-signals`: "Instant events capture alpha-price context at creation"
  and "Outcome horizons are measured against a fleet baseline" generalize from
  fleet signal events to any netuid-scoped alert class; "Econ-code changes are
  detected by path and alerted per range with a per-netuid cooldown" changes
  the delivery tier to `briefing` while leaving detection and the cooldown
  intact.
- `telegram-integration`: the `shadow` tier joins the delivery tiers and
  suppresses sending while still recording; the fleet-signal class tier map
  and "Gate-crossing is an instant-tier class with per-netuid cooldown" are
  updated; a `root-rotation` class is added with its own render and gloss.

## Impact

- **Code:** `livedata/atlas_live.py` (root weight vector read, decode of
  `Vec<(u16, u16)>`, aggregate destination map, storage), `livedata/config.json`
  (`root_rotation` block, gate-crossing durability window),
  `fleet/atlas_fleet_signals.py` (ledger entry point generalized, tier
  constants), `fleet/config.json` (econ-code tier),
  `telegram/atlas_telegram.py` (`shadow` tier handling, `root-rotation`
  adapter), `telegram/config.json` (tiers, class, `governs`, voice gloss).
- **Schema:** new tables for root vectors and the aggregate map; the ledger
  entry tables gain a class/source column so non-fleet classes can be entered.
  Additive only.
- **Tests:** `livedata/tests` (key derivation, decode, batched read, reversal
  guard), `fleet/tests/test_signals.py` (generalized ledger, shadow tier),
  `telegram/tests` (tier routing, new class render, shrink order).
- **Docs:** `README.md` status, `docs/decisions.md` (the effectiveness read
  that justified each demotion, recorded with its numbers), `fleet/README.md`,
  `livedata/README.md`.
- **Device:** one `git pull`; two additional keyless RPC calls per hourly
  pass; no new unit, timer, port or credential. Alert volume is expected to
  fall from about 6.6 a day to 1 or 2.
- **Reversibility:** every demotion is a tier value in config; the root read
  is inert if its config block is disabled; `shadow` is the default for the
  new class, so nothing new can page by accident.
