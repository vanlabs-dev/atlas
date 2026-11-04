# Proposal

## Why

The 2026-11-02 audit (A13, A14, A16, A18) found places where `atlas-live` turns a missing or old value into a plain answer:

- a missing miner burn counts as zero burn;
- a key missing from a per-subnet map reads as the runtime default ("the owner owns nothing");
- the gate trusts a TaoSwap panel without checking its block or its row count;
- a lagging TaoStats head can record a spec change;
- network vitals lose whole data dates.

None of these is producing a wrong page today. On 2026-11-04 the panel was 7 blocks behind and its worst share error was 0.73%. But every one of them fails silently when it happens.

The WP12 re-check also showed that the chain's own share pipeline can be reproduced exactly from chain storage. At block 9430559, shares built from `SubnetMovingPrice`, `MinerBurned` and the chain's emit-to universe gave the 32nd share equal to the theta the chain pinned at the next block (0.00832901). The provider is therefore not needed on the alert path.

## What Changes

- **Gate shares come from the chain.** The gate reads each subnet's moving price, miner burn, emission switch and the emit-to filters (first-emission block set, subtoken enabled, registration allowed) at the gate's own finalized block. It then computes shares the way subtensor v486 does. The TaoSwap panel no longer feeds shares or crossing events. **BREAKING** (behaviour): a panel outage no longer stops gate events; a chain read failure does.
- **The universe matches the chain.** This replaces the recorded "accepted deviation", in which the panel's non-root set stood in for the emit-to set.
- **An exact check at each theta pin.** In rank mode, when the pass is close enough to the last 360-block pin for the node to still hold the state, Atlas recomputes shares at the block before the pin. It expects exactly N shares at or above the theta read at the pin. Any difference records a health event. The hourly count check with tolerance 1 stays for the blocks between pins.
- **Dense maps fail per subnet.** Each per-subnet storage item declares whether every registered subnet (or every non-root subnet) holds a key. A key missing from a dense item is a per-netuid read failure, never the runtime default. The empty-batch rule stays only for the existing fail-empty set.
- **The panel is checked, not trusted.** The subnets panel is no longer cut at 130 rows. Each snapshot stores the panel's own block next to the chain block. If the panel lags the chain by more than a configured number of blocks, or has fewer non-root rows than the chain has non-root subnets, the pass records a health event and writes no snapshot rows.
- **Spec observations need fresh, rising data.** The TaoStats path records a spec only from a `fresh` reading. A spec lower than the last one seen is recorded only from RPC. From any other source it records a health event and leaves the last-seen value unchanged.
- **Vitals are keyed on the data date.**
  - A row is written once per provider data date and never replaced.
  - A response that is not `fresh` (older than the configured `max_upstream_age_s`) records a health event and writes nothing.
  - The hourly pass retries until the provider serves the newest expected date (UTC yesterday), so a lag between 1 and 2 days no longer skips a date.
- **Not changed:**
  - `chain_params` keeps one row per observation (operator decision: wontfix).
  - Dates already missed are not backfilled.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `live-data`:
  - demand-share source and universe;
  - rank cross-check (exact pin check added);
  - batched map reads (dense-item coverage);
  - panel snapshot (panel block, lag and row-count refusal, no truncation);
  - spec observation (fresh and monotonic rules);
  - daily network vitals (data-date keying, freshness, no overwrite).

## Impact

- **Code:** `livedata/atlas_live.py`:
  - `run_gate_pass` and the share function;
  - `read_subnet_maps` coverage;
  - `_pp_subnets_taoswap`;
  - `record_panel_snapshot` and the `panel_snapshot` schema (new `panel_block` column, added by `ALTER`);
  - `record_spec_observation` and its callers;
  - `run_vitals_daily`.
- **Config:** `livedata/config.json` gate keys:
  - `panel_max_lag_blocks`;
  - `pin_check_max_age_blocks`.
- **Chain reads:**
  - Three new `CHAIN_READS` items: `SubnetMovingPrice` (`FixedI128<U32>`), `FirstEmissionBlockNumber` (`u64`), `SubtokenEnabled` (`bool`).
  - New `EXPECTED_DEFAULTS` entries for the two value-query items whose unset value is substituted.
  - These are probe-coupled. Since WP5 the upgrade job cannot edit `livedata/`, so a runtime rename of these items becomes an operator fix.
- **Other components:**
  - Readers of `panel_snapshot.demand_share` (the briefing, which is off) now get chain-based shares.
  - `fleet/atlas_fleet_signals.py` calls the panel on its own and is not affected.
- **Deploy:**
  - A Pi pull.
  - A probe run before the next hourly pass.
  - An operator `/restart` so `atlas-live` loads the new code.
  - The `poll-gate` and `poll-chain-head` timers pick it up on their next run.
- **RPC load:**
  - One extra batched map read per gate pass.
  - About two thirds of passes add one historical read for the pin check.
