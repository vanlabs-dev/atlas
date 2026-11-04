# Tasks

## 1. Chain reads and coverage

- [x] 1.1 Add `SubnetMovingPrice` (`FixedI128<U32>`, codec `i96f32`), `FirstEmissionBlockNumber` (`u64`) and `SubtokenEnabled` (`bool`) to `CHAIN_READS`, plus the `i96f32` decoder (signed, 16 bytes, fails closed on any other length). Add `EXPECTED_DEFAULTS` entries for each item whose unset value Atlas substitutes (`SubtokenEnabled` false; `SubnetMovingPrice` zero, a gap). Record the spec and block in a comment. Verify: `python3 livedata/atlas_probe.py check` passes against live RPC; `test_chain_reads.py` and the defaults-table test pass; decoder tests cover a negative value and a wrong length.
- [x] 1.2 Add `SUBNET_MAP_COVERAGE` (`all` / `non-root`) per the design Context table. `read_subnet_maps` enumerates `SubnetworkN` at the same block whenever a dense item is requested, and records a dense item's missing netuid as `failures[item][netuid] = "absent from dense map"`. Move the `returned < requested` whole-item check to every item; keep the empty-batch rule for `SUBNET_MAP_FAIL_EMPTY` only. Verify: tests (fake RPC) for a missing `SubnetOwner` key, a truncated key list for `Burn`, a sparse identity absence still unset, and a short query response for a non-fail-empty item; a test pins the coverage table.
- [x] 1.3 Check every `read_subnet_maps` consumer (owner resolution, mining snapshot, `live_hyperparams`, switch watch, `read_knobs`, registration blocks) for a per-netuid failure being read as a default. Fix any that do, and change the owner reason text to a generic one. Verify: one test per consumer that sees a dense-map failure and does not output the default; `livedata` and `fleet` suites pass.

## 2. Chain-native gate shares

- [x] 2.1 Pure `chain_demand_shares(values, failures)`: universe filter, `price x (1 - clamp(burn, 0, 1))` normalized, all-zero fallback to price shares, per-netuid enabled flags, no shares plus a reason on any share-item failure for a universe member. Remove `compute_demand_shares`. Verify: unit tests for the SN36 case (outside the universe, no share), a missing burn (no shares, reason names the item and netuid), a zero price (in the universe with zero weight), the all-zero fallback, and emission-disabled kept.
- [x] 2.2 `run_gate_pass` reads the share maps at the `poll_gate_state` block and passes them to `watch_subnet_emission_switch(maps=...)`. Shares, sides, events and the tolerance check use chain shares. Panel failure no longer returns early. A failed share read records a health event and returns with no events. Verify: gate tests with a fake RPC: panel down still records a crossing; chain share read failure records none; the switch watch makes no read of its own; existing `test_gate.py` scenarios pass, with fixtures updated from panel shares to chain maps.
- [ ] 2.3 Exact pin check per design decision 7. Add nullable `gate_state.pin_block` and `pin_above_count` (additive `ALTER`), config `gate_signal.pin_check_max_age_blocks` (240) and the 1e-6 relative epsilon. Record skips in the pass summary. Verify: tests: exact N is silent; N-1 records `pin-check-divergence`; fewer than N positive expects all positive; a pruned-state error is a skip with no health event; a pass older than the max age skips; q-mass mode skips; migration runs twice on an old store.
- [ ] 2.4 Gate alert wording: change the details line to "Demand and cutoff (the emission bar): chain RPC." and update the docstring at `telegram/atlas_telegram.py:2034`. Verify: `telegram/tests/test_gate_class.py` updated and passing.

## 3. Panel checks

- [ ] 3.1 `_pp_subnets_taoswap`: drop `rows[:130]`; a row whose `id` is not an int raises `FatalLiveError`. Verify: tests: 140-row fixture keeps 140; a bad id fails validation; the live subnets tool test still passes.
- [ ] 3.2 `record_panel_snapshot` takes `panel_block` (new nullable column, additive `ALTER`) and stores the chain share. The pass writes rows only when the lag is within `gate_signal.panel_max_lag_blocks` (300) and the non-root row count is at least the chain's non-root count. Otherwise it records health event `panel-lagging` or `panel-short`. Every pass summary carries the lag. Verify: tests for a lagging panel, a short panel, a missing panel block, and a good panel (rows carry both blocks and the chain share); migration runs twice.

## 4. Spec observation

- [ ] 4.1 `run_operation` records a `chain_head_taostats` reading only when it is `fresh`. `record_spec_observation` refuses a lower spec from any source other than `rpc` with health event `spec-regression-unconfirmed` and leaves `meta` unchanged. Verify: tests: aged TaoStats head records nothing; lower spec from TaoStats records nothing plus the health event; lower spec from RPC records an event with source `rpc`; the existing spec-observation tests pass.

## 5. Vitals

- [ ] 5.1 `run_vitals_daily` per design decision 10: the expected date is UTC yesterday; no call when that row exists; `INSERT OR IGNORE`; anything not `fresh` writes nothing and records `vitals-aged` at most once per expected date. Verify: tests: provider lagging one more day is retried with no write and no replace; expected date stored makes no call; aged response gives one health event over two passes; a new date is inserted; an invalid response gives a health event as today.

## 6. Docs, rehearsal, deploy

- [ ] 6.1 Update `livedata/README.md`, `docs/emission-metrics.md` (share source and universe), the `gate_signal` config comments, and the `live-data` spec references to the panel as share source. Add a `docs/decisions.md` entry: option A, the reversal of the accepted-universe deviation, `chain_params` wontfix, and pin-check reasoning. Verify: `python3 tools/readme_sync.py` reports no drift; `grep -n "TaoSwap panel" livedata telegram docs` shows no share-source claim.
- [ ] 6.2 Workstation rehearsal (read-only, scratch store): run the new share read and the pin check against live finney at three or more blocks, and compare with the panel shares and the Pi's newest `gate_state` theta. Verify: an exact pin count at each block where the check runs; findings recorded in this change's design.md Context.
- [ ] 6.3 Every Python suite passes, locally and in bwrap with `--unshare-net` (the upgrade job's gate). Verify: the README test loop and the sandbox run both show no failure.
- [ ] 6.4 Deploy (each step needs operator approval): push; Pi pull with `atlas-alerts.service` idle; Pi `livedata/tests` and `telegram/tests`; `python3 livedata/atlas_probe.py check` on the Pi; operator `/restart`. Verify: after the next :15 pass, a read-only check per design Migration Plan step 5; next UTC day, step 6.
- [ ] 6.5 Archive and sync specs after the operator confirms the live check. Verify: `openspec validate --strict` passes before the archive; the main `live-data` spec shows the new requirements.
