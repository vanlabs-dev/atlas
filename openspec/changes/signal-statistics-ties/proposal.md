# Proposal

## Why

The effectiveness ledger decides which alert classes may page, but it
mismeasures them (audit items C13, D7, D8, 2026-11-02, re-verified
2026-11-03):

- A reused netuid joins two different subnets into one price series. 12
  netuids were re-registered since 2026-07-19. Twelve filled outcomes
  compare one subnet's price with its successor's (SN82 +2533%, SN92 +1302%,
  SN116 +492%). Board momentum has the same defect today: SN16 shows +403% and
  SN36 +404% over 7 days, both new subnets in reused slots.
- Gate-crossings enter the ledger at eligibility, about 48 h after the
  crossing, but their horizons are due from the crossing. All 24 1-day
  outcomes are 0.000%. Their "7-day" windows span 4.7 to 5.0 days.
- The promotion floor counts rows, not events: 87 root-rotation rows come
  from 8 event moments. Medians are unpaired, and there is no interval.
- Tied percentile ranks follow netuid order: 24 subnets tied at zero activity
  spread over ranks 0.004 to 0.208, which moves attention scores by up to
  about 12 points.
- The board's ▲ promising / ▼ dangerous cue and the accumulate/fade quadrant
  are trading cues that have never been measured. The activity that drives
  them counts bot commits.

## What Changes

- Each stored price vector also records each netuid's `NetworkRegisteredAt`
  block, read from chain through a declared chain read. A return counts only
  when both ends belong to the same registration. The rule applies to ledger
  outcomes, the fleet baseline and board momentum.
- Entry and exit prices come from the first stored vector at or after the
  anchor time and at or after the due time, within a 6 h grace. A horizon
  with no such vector is `unavailable`, never filled late with a different
  window.
- Gate-crossings are anchored at `eligibility_at`, the time the alert can
  page. Their horizons fall due from that time.
- A one-time `rescore` command recomputes every filled outcome from the stored
  vectors under the new rules. It writes new columns and keeps the old ones.
- `effectiveness` reports:
  - distinct event moments
  - the median paired excess return (subnet return minus fleet median over
    the same window)
  - a 95% interval from a bootstrap that resamples whole event moments, with
    a fixed seed
- The promotion floor counts distinct event moments.
- **BREAKING (gate rule):** a class beats the baseline only when the
  interval's lower bound is above zero.
- Percentile ranks give ties the average rank.
- **BREAKING (board):** the direction cue, the promising/dangerous filters,
  the direction labels, the directional thesis sentences and the quadrant
  regions are removed. Divergence stays as a neutral "apart" fact.
- Activity counts skip commits from bot and CI author addresses, matched by a
  configured list of patterns.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `fleet-signals`: price vectors carry the registration block; entries and
  outcomes are filled from stored vectors within a grace window and are
  `unavailable` across a re-registration; gate-crossings are anchored at
  eligibility; the effectiveness report states event counts, the median
  excess return and an interval; rescore of past rows.
- `signal-effectiveness-gate`: the floor counts distinct event moments;
  "beats the baseline" means the interval's lower bound is above zero.
- `fleet-rotation-metrics`: tied percentile ranks are averaged; momentum
  is `n/a` across a re-registration; activity excludes bot and CI authors;
  the quadrant regions and the direction cue are removed from the report
  and the board.

## Impact

- Code:
  - `fleet/atlas_fleet_signals.py` (schema columns, measurement,
    effectiveness, `rescore`)
  - `fleet/atlas_fleet_metrics.py` (ranks, momentum, activity)
  - `fleet/atlas_fleet_dashboard.py` (cue, filters, thesis)
  - `fleet/config.json`
  - `livedata/atlas_live.py`: a `NetworkRegisteredAt` chain read in
    `CHAIN_READS`, plus a reader
- Probe coupling: the hourly probe, the upgrade job's probe gate and the
  `atlas-live` MCP server load `CHAIN_READS`. A runtime that renames
  `NetworkRegisteredAt` then fails the probe.
- Pi:
  - `atlas-fleet.service` is the only process that runs signals, metrics and
    the board.
  - A Telegram `/restart` is needed for the `atlas-live` MCP server.
  - `rescore` writes `fleet.db` once, after a backup.
- Decision log: `gate-crossing` (instant) and `watchlist` (instant) already
  fail the floor. No tier changes in this change. Tiers move only by
  operator decision.
- WP6:
  - Scores, tiers, `div_signed`, the diverging count and `momentum_7d`
    change on the board, in subnt and in the held fixtures.
  - `cue_kind` is no longer produced, so `web/scripts/allowlist.ts` must
    drop `cueKind`.
  - The fixture export hold stays.
