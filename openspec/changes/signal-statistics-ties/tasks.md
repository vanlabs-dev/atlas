# Tasks

## 1. Registration read (livedata)

- [x] 1.1 Confirm `NetworkRegisteredAt` hasher, value type and default against live metadata at the finalized head; record spec and block in the `CHAIN_READS` comment. Verify: `livedata/atlas_probe.py` passes locally against live RPC.
- [x] 1.2 Add `NetworkRegisteredAt` to `CHAIN_READS` and `read_registration_blocks(config, rpc)` returning `{netuid: block}`, head block and hash, fail-closed on RPC error. Verify: new tests in `livedata/tests/` (fake RPC: decode, absent key, RPC failure) and `test_chain_reads.py` pass.

## 2. Ledger schema and vector choice (fleet-signals)

- [x] 2.1 Additive migration in `ensure_schema`: `signal_prices.reg_block`, `signal_vectors`, entry columns `anchor_at`/`entry_ts`/`reg_block`/`reason`, outcome `v2_*` columns. Verify: test opens a pre-change store fixture, migrates twice, old rows intact.
- [x] 2.2 `default_price_fetcher` stores each vector with `reg_block` and the head block; a failed registration read stores nothing. Verify: test with injected fetchers (price ok + reg fail leaves no vector, entries pending).
- [x] 2.3 One outcome evaluator: entry and exit from the earliest vector within 6 h at or after the anchor/due time; `no-vector`, `re-registered`, `unverified` reasons; baseline over netuids passing the same test. Live fill writes old and `v2_*` columns. Verify: regression tests for each defect: re-registered exit (SN82-shaped), late exit not stretched, no-vector entry unavailable, legacy-entry vs new-exit rule, baseline excludes a re-registered netuid.
- [x] 2.4 Gate-crossing ingest anchors at `COALESCE(eligibility_at, observed_at)`; horizons due from the anchor. Verify: regression test reproducing the Pi shape (eligible 48 h after crossing) shows a 1-day outcome over a real 1-day window, not 0.000%.

## 3. Effectiveness statistics and gate (fleet-signals, signal-effectiveness-gate)

- [x] 3.1 Report distinct event moments, median paired excess, moment-clustered bootstrap 95% interval (2,000 draws, fixed seed, none below 10 moments), `unavailable`/`unverified`/unscored tallies, `beats_baseline`. Verify: tests: 87 rows from 8 moments counts 8 and fails the floor; repeat run gives the same interval; interval touching zero is `beats_baseline: false`; report changes no state.
- [x] 3.2 Update `fleet/README.md` and the CLI help for the new report fields and rules. Verify: `python3 tools/readme_sync.py` reports no drift.

## 4. Rescore

- [x] 4.1 `rescore` subcommand: recompute every non-pending outcome into `v2_*` with the current registration map and gate anchors (livedata opened read-only); idempotent; original columns untouched. Verify: tests for idempotence, untouched originals, stretched gate-crossing 7-day row recomputed or `no-vector`.
- [x] 4.2 Dry run on a copy of the Pi `fleet.db` (read-only snapshot into the session scratchpad) and record before/after effectiveness figures per class in this change's notes. Verify: figures written; no Pi write.

## 5. Metrics: ties, momentum, bot filter (fleet-rotation-metrics)

- [x] 5.1 Average ranks for ties in `_percentile_ranks`. Verify: tests: 24 zeros of 113 all get 12/113; shuffled input order gives identical ranks.
- [x] 5.2 Momentum `n/a` across a registration change, excluded from the fleet median. Verify: regression test with a vector pair carrying different `reg_block` (SN16-shaped +403%).
- [x] 5.3 `metrics.bot_author_patterns` config and filter in `compute_activity` windowed counts and `a30`. Verify: test with 190 `[bot]@` commits and 10 human commits gives c30 10, a30 1; `fleet/config.json` loads.

## 6. Cue removal (fleet-rotation-metrics)

- [x] 6.1 Remove `quadrant` from report rows, `cue`/`cue_kind`/`dir_label` and promising/dangerous filters and tags from the board; neutral "points apart" thesis. Verify: dashboard tests assert no ▲/▼, no "PROMISING"/"DANGEROUS", no "hasn't priced" in the rendered page; subnt tests still pass.
- [x] 6.2 Update `fleet/README.md` board section and the metrics docstrings. Verify: grep finds no `accumulate`/`promising` in `fleet/` outside tests and history notes.

## 7. Full verification and deploy prep

- [ ] 7.1 Run every Python suite and `npm --prefix web test`. Verify: all pass.
- [ ] 7.2 End to end on the workstation: one `run_measurement` against live TaoSwap and RPC on a scratch store copy, showing a vector with `reg_block` for every netuid. Verify: output recorded.
- [ ] 7.3 Read-only Pi snapshot of the board and effectiveness before deploy, saved for the WP6 diff. Verify: files in the session scratchpad.
- [ ] 7.4 Deploy (each step operator-approved): push; stop `atlas-fleet.timer`; Pi pull; Pi fleet and livedata suites; `fleet.db` backup; `rescore`; one reconcile via `systemd-run`; board diff; start timer; operator `/restart`. Verify: newest vector has `reg_block` for all netuids; probe `ok`; board diff recorded for WP6.
- [ ] 7.5 `docs/decisions.md` entry (cue dropped, bot filter, eligibility anchor, CI rule, rescore) and handover tracker/session log. Verify: entries committed.
