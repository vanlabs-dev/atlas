# Tasks

## 1. Schema and config

- [x] 1.1 Add the `mine_econ` columns `pool_days`, `payback_days` and `required_band`, and the `mine_mechanism` columns `parity_alpha_day`, `indep_p25_alpha_day` and `indep_median_alpha_day`. Add an additive `ALTER` path for `mine_mechanism` in `ensure_schema`. Verify: a test opens an old-shape store, runs `ensure_schema` twice, and finds every column.
- [x] 1.2 Update the `mining` block in `fleet/config.json`:
  - `budget_band` set to `consumer-gpu`
  - `rent_bands` set to 1.5 and 6.3, with `rent_source`
  - `min_immunity_blocks` 720
  - `subnet_sale_fraction` 1.0
  - `_comment` updated

  Retire `staking_apy_pct` and `daily_sale_fraction` into `RETIRED_CFG_KEYS`. Bump `MODEL_VERSION` to 3 and `MINING_VERSION` to 0.3.0. Verify: `load_config` passes and the retired-key note test covers both keys.

## 1b. Live-data context reads

- [x] 1b.1 Add `SubnetEpochConsensus`, `NullPruningTarget`, `ValidatorPermit`, `LastUpdate`, `Weights`, `BlockAtRegistration` and `Axons` to `CHAIN_READS`, with hashers and types from v486 `lib.rs`. Add the substituted defaults to `EXPECTED_DEFAULTS`, with bytes taken from a local probe run. Verify: `livedata/tests/test_chain_reads.py` passes, and `python3 livedata/atlas_probe.py` passes against finney.
- [x] 1b.2 Add the codecs `Vec<bool>`, `Vec<u64>`, `Vec<(u16,u16)>`, `EpochConsensus` and the `AxonInfo` block prefix, plus the two-part key tail reader. Verify with regression tests:
  - each codec decodes a known payload and rejects a truncated one
  - consensus index 2 fails closed
  - the axon decoder returns only the block
  - a mechanism-1 weight key maps to `(netuid, mecid, uid)`
- [x] 1b.3 Read the context in `read_mining_snapshot` at the snapshot block:
  - `BlockAtRegistration` as point reads for uid below `SubnetworkN`
  - per-item fail isolation

  Verify with tests:
  - a failed context item leaves `ok` true, with the context marked unread
  - every context value carries the snapshot block

## 2. Entrant figure (D1, D2)

- [x] 2.1 In `mechanism_economics`, compute the parity share, the p25 and median earners (interpolated), and entrant = min(parity, p25). Verify with regression tests:
  - long tail: parity 147.6, p25 0.07, so entrant 0.07
  - few strong earners: entrant = parity
  - the owner UID is excluded from the percentile set
  - 3 earners of 255 slots: no scaling and no cut
- [x] 2.2 Update `PARITY_MODEL` to state the min rule, the at-spot valuation and the haircut assumption. Verify: the tests that assert the model text is present still pass, with the new wording.

## 3. Haircut and pool depth (D5)

- [x] 3.1 Compute the haircut from `alpha_out_day * subnet_sale_fraction`, and store `pool_days`. Verify with a regression test: 7,200/day into a pool of 89,898 alpha matches `exit_haircut_pct` for 7,200 alpha, and `pool_days` is about 12.5. An unknown pool gives no haircut and no figure.

## 4. Ladder: prune risk and hardware (D3, D6)

- [x] 4.1 Add the `prune-risk` rung after winner-take-all. Verify with regression tests:
  - full with immunity 1 against 720 is cut, and the detail carries both numbers
  - open with immunity 1 survives
  - unknown immunity or fullness survives
- [x] 4.2 Move rent and net into Stage C:
  - `required_band` from feasibility
  - hardware cut when required > budget
  - net = gross minus required-band rent, on the row and on each mechanism
  - rank on net
  - `budget_band` null makes every survivor unrated `no-budget-band`
  - `baseline_tao_month` stays null

  Verify with regression tests:
  - `needs-gpu` with no VRAM under consumer survives, netted at 1.5 and marked assumed
  - 48 GB declared under consumer is cut with both numbers in the detail
  - 16 GB declared survives and is netted at 1.5
  - unknown is costed at the budget band and marked assumed
  - a null band ranks nothing
- [x] 4.3 Store `payback_days` = `reg_cost_tao` / (net / 30) when net > 0, else null. Verify: 0.5 TAO at 15 TAO/month gives 1.0, and net ≤ 0 gives null.

## 5. Feasibility scanner v4 (D4)

- [x] 5.1 Scan the miner subtree, the entrypoint and `min_compute`:
  - strong-token regex gives `needs-gpu`
  - weak tokens give `gpu-mention` evidence with no verdict change
  - cap of `max_subtree_files`
  - `SCAN_VERSION` "4"

  Verify with regression tests:
  - `torch.cuda` in `miner/model.py` while the entrypoint is clean gives `needs-gpu` with that path and line
  - `torch.cuda` in a miner subtree with no recognised entrypoint gives `needs-gpu`
  - a README that says "no GPU needed" stays `possible` with mention evidence
  - validator and test paths are ignored
  - the scan-version bump invalidates stored verdicts

## 5b. Activity facts and consensus tracker

- [x] 5b.1 Compute `registered_7d`, `weighted_uids`, `widest_weight_row`, `axons_served_7d` and `consensus_mode` in Stage A, and add them to the `mine_econ` migration. Verify with regression tests:
  - a stale validator row (last update outside the cutoff) is not counted
  - a row from a UID without a permit is not counted
  - top-5 rows give a widest row of 5
  - an unread input gives null, not 0
  - no stored column holds an address
- [x] 5b.2 Add the `mine_consensus_events` table. On each committed pass, record a switch when the mode differs from the last recorded mode. Unknown modes record nothing. Verify with tests:
  - the first pass of 128 subnets records 0 events
  - Yuma to Null records 1 event with its block
  - unknown records 0 events
  - no row reaches `chain_param_events`
- [x] 5b.3 Null rounding check (design 14) on the real SN120 data from a fresh snapshot. Record the result in design.md. If needed, switch Null earner figures to `Emission`, with a test.

## 6. Surfaces (D9, D10, labels)

- [x] 6.1 Board HTML:
  - "entrant TAO/mo at spot (model)"
  - alpha/day columns for entrant, parity, p25 and median
  - "N earning of M slots"
  - payback, pool days, required band (marked assumed where it applies)
  - "no GPU evidence found" for `possible`
  - "enter at rank" dropped
  - each activity fact with its exact definition, and the rounding note
  - a consensus section: count per mode, the Null list with "since", the Null flag, and the pruning flag
  - no use of "active" or "idle" anywhere on the page

  Verify with render tests that assert those strings and their absence.
- [x] 6.2 Add `compact_view` and use it for MCP `mining_board`, with cut and unrated rows as netuid, name and reason. Update the tool descriptions with the at-spot label and model. Verify with server tests:
  - each row's key set equals the compact set
  - a store with no new columns returns nulls without an error
  - `mining_subnet` still returns every column
- [x] 6.3 Add `triage/README.md`, which marks the folder as an August 2026 snapshot that nothing reads. Run `python3 tools/readme_sync.py` and confirm it has no diff, or commit its output.

## 7. Consumers and full suite

- [x] 7.1 Update the fixtures in `fleet/tests/mining_fixtures.py`, `subnt/tests` and `telegram/tests` for the new columns and `MODEL_VERSION` 3. Verify: the agreement tests (board, briefing, subnt head and counts) pass.
- [x] 7.2 Run every Python suite with the handover loop, plus `npm --prefix web test`. Verify: all pass.
- [x] 7.3 Rehearsal on the workstation (not the proof; 8.2 and 8.3 are):
  - stream the tables the screen reads (`slots`, `index_state`, `fleet_files`, the needed `fleet_files_fts` rows, `mine_*`) from the Pi over ssh with a `mode=ro` reader into a scratch store; no file is written on the Pi
  - run `run_econ`, `run_feasibility` and `run_classify` on it with a fresh `read_mining_snapshot` (watches not run)
  - read `report()` and `compact_view` from it

  Verify: the ranked head, the cut counts per rung and the compact payload size are recorded in this change's design notes.

## 8. Deploy (each step needs operator approval)

- [x] 8.1 Push.
- [x] 8.2 On the Pi, in order:
  - stop `atlas-fleet.timer`, and confirm `atlas-fleet.service` is inactive
  - `git pull`
  - run `python3 livedata/atlas_probe.py` before the next hourly probe timer, so a probe failure shows up before it pages
  - run `fleet/tests`, `livedata/tests` and `subnt/tests`
  - run one `python3 fleet/atlas_fleet_mining.py pass`; it migrates, rescans 107 slots, writes a model-3 pass and runs the two parameter watches, as a timer pass would

  Verify: `status` shows `model_version` 3, and `mining.html` shows the new labels.
- [x] 8.3 Operator `/restart` in Telegram (it reloads the `atlas-fleet` and `atlas-live` MCP servers), then an operator ask in Telegram that makes the running `atlas-fleet` MCP child call `mining_board`. Verify: the MCP audit log shows the call, and the reply carries the compact rows and the at-spot label.
- [x] 8.4 Start `atlas-fleet.timer`. Verify: `list-timers` shows the next run.
- [x] 8.5 Update the tracker and session log in the handover: the WP6 notes and the fixture-export hold. Then archive the change.
