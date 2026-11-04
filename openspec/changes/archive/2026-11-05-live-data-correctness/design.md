# Design

## Context

See proposal.md (Why). State measured on 2026-11-04 during the WP12 re-check:

- **Chain rule (subtensor tag `v486`).**
  - `get_subnets_to_emit_to` keeps subnets that are non-root, have `FirstEmissionBlockNumber` set, have `SubtokenEnabled` on, and allow registration.
  - `get_shares` normalizes `SubnetMovingPrice`, scales by `(1 - MinerBurned)` and renormalizes. The result is the same as normalizing `price x (1 - burn)` once, except when every weight is zero, where the chain falls back to plain price shares.
  - `maybe_update_emission_gate_bar` re-pins theta when `block % 360 == 0`. It uses the shares computed in that block, before the block's moving prices advance.
- **Reproduction.** Head 9430724, pin 9430560. Shares computed from storage at block 9430559 put the 32nd share at 0.00832901, which equals theta at 9430560. At the pin block's own post-state the 32nd share is 0.00832899, just below theta. That explains why the hourly count reads 31 more often than 33.
- **Universe today.** SN36 is the only registered subnet outside the emit-to set. It has no first-emission block and its subtoken is off. Its weight is zero, so it changes nothing.
- **Key coverage at block 9430798** (129 registered including root):
  - Every subnet: `Burn`, `ImmunityPeriod`, `MaxAllowedUids`, `NetworkRegistrationAllowed`, `SubnetTAO`, `SubnetAlphaIn`, `SubnetAlphaOut`, `SubnetworkN`.
  - Every non-root subnet: `SubnetOwner`, `SubnetOwnerHotkey`, `MinerBurned`, `SubnetEmissionEnabled`, `SwapBalancer`. `SubnetEmissionEnabled` stays sparse in the coverage table: the existing switch-watch requirement records an absent entry as its assumed default, distinct from a failed read, and the fail-empty rule already catches a lost batch (found during apply).
  - All others are sparse: identity, mechanism items, `CollateralLockShare`, `OwnerCutEnabled`, `SubnetProtocolAlpha`, and the items missing for SN36 only (`SubnetMovingPrice`, `SubnetAlphaOutEmission`, `FirstEmissionBlockNumber`).
- **Metadata types.** `SubnetMovingPrice` is `FixedI128<U32>`, `FirstEmissionBlockNumber` is `u64`, `SubtokenEnabled` is `bool`. All three use the identity hasher. The probe already accepts these names.
- **Node state window.** About 256 blocks (measured in WP4). A pass reaches back to the block before the pin only if that block is no older than this window.
- **Panel today.** 129 rows, 7 blocks behind the chain. `dereg_context.current_block` carries the panel's block.
- **Vitals.** The provider's data date is normally UTC yesterday. At 00:xx UTC it often still serves the day before. `INSERT OR REPLACE` on `date` plus a "done for today" marker then skips that date.
- **Rehearsal (task 6.2, shipped code, workstation, scratch stores).**
  - Exact pin count 32 of 32 at pins 9430920 (pass at block 9430967) and 9433800 (pass at 9433921, universe 128 after SN36 started emitting); 9430560 matched by the earlier ad hoc read.
  - Hourly count 31 and 32 between pins; no health events; panel lag -1 and -4 blocks; 128 snapshot rows.
  - Pins 407 blocks or more back are pruned on the node, and the check records a skip.
  - At block 9431037 no subnet changed zone or side between panel and chain shares, so the first chain-share pass needs no re-seed.
  - A full pass took 48 s against the alerts unit's 20 min timeout. The live mining snapshot (block 9430993) had no failed items and no dense-missing keys.

## Goals / Non-Goals

**Goals:**
- The gate path depends on keyless RPC only.
- Every refusal leaves a health event naming its cause.
- Each defect gets a regression test that fails on the current code.

**Non-Goals:**
- Exact fixed-point replication of the runtime. Float math with a stated tolerance is enough.
- Moving the live subnets tool or the fleet signals off the panel.
- Backfilling vitals dates that were already missed.
- Deduplicating `chain_params` rows (wontfix).
- Correcting the corpus line "normalized across emit-enabled subnets" (WP13).

## Decisions

1. **One batched share read at the gate block.**
   - `run_gate_pass` reads these items through `read_subnet_maps` at the block `poll_gate_state` already pinned: `SubnetworkN`, `SubnetMovingPrice`, `MinerBurned`, `FirstEmissionBlockNumber`, `SubtokenEnabled`, `NetworkRegistrationAllowed`, `SubnetEmissionEnabled`.
   - That is about 900 keys in 4 query chunks.
   - The same maps are handed to `watch_subnet_emission_switch(maps=...)`, which then makes no read of its own. The pass therefore adds one batched read, not two.
   - Alternative considered: per-key reads. Rejected, because the values would come from different blocks.
2. **The share function is pure.**
   - `chain_demand_shares(values, failures)` returns the shares, the per-netuid enabled flags and the universe.
   - Any failure of a share item for a universe member returns no shares, with the reason. This covers `MinerBurned`, `SubnetMovingPrice` when the key is present but undecodable, and the filter items.
   - When every weight is zero, the function returns plain price shares, as the chain does.
   - `compute_demand_shares` (panel-based) is removed. Its only caller is `run_gate_pass`.
3. **Snapshot shares are chain shares.** `panel_snapshot.demand_share` takes the chain share for the netuid, so the briefing and the alert price lookups keep working without a schema rename.
4. **Coverage table next to `SUBNET_MAP_ITEMS`.**
   - `SUBNET_MAP_COVERAGE = {item: "all" | "non-root"}`. Unlisted items are sparse.
   - When any dense item is requested, `read_subnet_maps` also enumerates `SubnetworkN` at the same block (one extra prefix) to get the universe.
   - A dense item's missing netuid goes into `failures[item][netuid] = "absent from dense map"`.
   - Separately, the existing `returned < requested` check moves from the fail-empty set to every item. It fails the whole item, because it means the query response itself was truncated.
   - Alternative considered: fail the whole item on any missing key. Rejected, because one late registration would blind every consumer of the item.
   - A test pins the table against the coverage measured above, so a later change to it is deliberate.
5. **Consumers of the new per-netuid failures.**
   - Owner resolution already maps a failure to an unknown owner (`SubnetOwner undecodable` becomes a generic reason).
   - The mining snapshot, `live_hyperparams` and the switch watch already carry `failures`. The apply step checks each call site and adds a test where one treats a failure as a default.
6. **Panel checks.**
   - `_pp_subnets_taoswap` drops `rows[:130]`.
   - A row whose `id` is not an int fails the panel (`FatalLiveError`), so the row is not skipped later.
   - `record_panel_snapshot` gains a `panel_block` argument and column (nullable `ALTER`).
   - The pass writes snapshot rows only when two conditions hold:
     - `chain_block - panel_block <= gate_signal.panel_max_lag_blocks` (default 300, about 1 h);
     - the panel's non-root row count is at least the chain's non-root `SubnetworkN` count.
   - Otherwise it records health events `panel-lagging` or `panel-short`.
   - A panel with no block counts as lagging.
   - The pass summary records the observed lag on every pass, so the default can be tuned from data.
7. **Exact pin check.**
   - In rank mode, with pass block B and pin P = B - B % 360, the check runs when `B - P + 1 <= gate_signal.pin_check_max_age_blocks` (default 240, under the 256 window). The steps:
     - read `EmissionGateBar` and `EmissionBarRank` at P;
     - read the share maps at P - 1;
     - compute shares;
     - count shares `>= theta x (1 - 1e-6)`.
   - Expected: N, or every positive share when fewer than N are positive. Anything else records `pin-check-divergence`.
   - A read error at P - 1 (pruned state) records `skipped` in the summary with no health event.
   - Results go to three new nullable `gate_state` columns: `pin_block`, `pin_above_count` and `pin_status` (`checked`, `divergent`, or `skipped: <reason>`). The status is on the pass's own row because the Pi keeps no journal (added during apply).
   - About two thirds of hourly passes qualify.
   - Why the epsilon: Atlas sums floats while the chain uses truncating U64F64. At the pin, s_N equals theta, so a strict `>=` could flip on rounding. The measured gap to the next share was 3% (0.00807796 against 0.00832901), far above 1e-6.
   - Alternative considered: exact fixed-point arithmetic. Rejected as out of proportion for a health check.
8. **Hourly tolerance check unchanged.** It now counts chain shares instead of panel shares. The tolerance stays at 1.
9. **Spec observation.**
   - `run_operation` calls `record_spec_observation` for `chain_head_taostats` only when `freshness_status == "fresh"`.
   - `record_spec_observation` refuses a lower `new_spec` unless `values["source"] == "rpc"`. A refusal records health event `spec-regression-unconfirmed` and does not touch `meta`.
   - The RPC path keeps recording a lower spec, because a runtime rollback is real.
10. **Vitals keyed on the data date.**
    - `expected = UTC today - 1 day`. If `network_vitals` already has that date, the pass makes no call.
    - Otherwise it fetches stats and price:
      - an invalid response records a health event (as today);
      - a `freshness_status` other than `fresh` records `vitals-aged`, at most once per expected date (dedupe key in `meta`);
      - a date already stored writes nothing (`INSERT OR IGNORE`);
      - a new date is inserted.
    - `META_VITALS_DATE` is no longer read; it stays in `meta` and does no harm.
    - Worst case: 2 keyless calls per hour while the provider lags.
11. **Alert wording.** The gate-crossing details line changes from "Demand: TaoSwap panel. Cutoff (the emission bar): chain RPC." to "Demand and cutoff (the emission bar): chain RPC." The function docstring changes to match.

## Risks / Trade-offs

- [The three new `CHAIN_READS` items couple to the hourly probe. A runtime rename pages `probe-drift`, the upgrade job's probe gate fails, and since WP5 the job cannot fix `livedata/`] → Accepted (operator chose option A). The probe page names the item, and the fix is a one-line declaration.
- [A runtime change to the share formula (for example a new filter) makes chain-native shares silently wrong] → The pin check catches it within about a day, because a formula change moves the count at the pin. A spec bump also triggers the upgrade job's review of the coinbase diff.
- [The pin check reads historical state that a node may prune earlier than 256 blocks] → It is recorded as skipped, not as a failure. The skip rate shows in the pass summary.
- [A dense map that is not dense after an upgrade (for example a new subnet without `SubnetEmissionEnabled`) shows up as per-netuid failures] → The failures are visible and fail closed. Only the coverage table needs editing.
- [Panel lag threshold of 300 blocks is a guess] → It affects snapshot rows only, not alerts. The lag is logged every pass for tuning.
- [The briefing's snapshot rows now stop on panel lag or a short panel] → The briefing is off (WP3). When it is re-enabled, missing rows read as missing, not as zero.

## Migration Plan

1. Workstation rehearsal, read-only:
   - run the new share function and the pin check against live finney at three or more blocks;
   - compare with the panel shares and the stored `gate_state` theta;
   - expect an exact pin count.
2. Push. Before the Pi pull, check that `atlas-alerts.service` is not running (the pass fires at :15 each hour).
3. Pi pull. Run `livedata/tests`. Run `python3 livedata/atlas_probe.py check`, which must pass with the three new items at the live spec.
4. Operator `/restart`, so the `atlas-live` MCP child loads the new code. The timers pick it up on their next run.
5. After the next :15 pass, check read-only:
   - the newest `gate_state` row has `above_count` and either `pin_block`/`pin_above_count` or a recorded skip;
   - no new `pin-check-divergence`, `panel-lagging` or `panel-short` health events;
   - snapshot rows carry `panel_block`;
   - `gate_events` behave as before.
6. Next UTC day: a vitals row for UTC yesterday exists, and no row was replaced.

Rollback: revert the commits and pull. The new columns are nullable and the old code ignores them. Nothing is migrated in place.

## Open Questions

- Default for `panel_max_lag_blocks`: 300 until a week of logged lags exists. It can be tuned in config without a spec change.
