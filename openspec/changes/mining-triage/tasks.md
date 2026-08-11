## 1. Chain access in livedata

- [x] 1.1 Add a `twox128(pallet, item)` storage-prefix helper to
  `livedata/atlas_live.py`, pure function, no network
- [x] 1.2 Add the pinned-key self-test: derivation must reproduce
  `EmissionGateBar`, `EmissionBarRank`, and `EmissionGateExponent` from
  `gate_signal.storage_keys` exactly, and a failure must block every
  derived-key read
- [x] 1.3 Add SCALE decoders with declared scales: `u16`, `Vec<u16>` behind
  a compact length prefix in all three encoded forms, `U96F32` at 2^32, and
  `u16` normalised by `u16::MAX`
- [x] 1.4 Add `read_subnet_maps()` using `state_getKeysPaged` to enumerate
  each map prefix and `state_queryStorageAt` to read all values at one
  finalized block, returning `SubnetworkN`, `Incentive`, `MinerBurned`, and
  `CollateralLockShare` per netuid with the shared reference block
- [x] 1.5 Derive map key layout from the observed key tail rather than an
  assumed hasher, and assert a populated control map in the same pass so an
  empty map is distinguishable from a wrong prefix
- [x] 1.6 Tests: pinned-key self-test, all three compact-length forms
  including the 2-byte case a 256-element vector needs, `U96F32` at 2^32
  regression, Identity key-layout regression, empty-versus-wrong-prefix

## 2. Netuid-keyed chain-parameter watch

- [x] 2.1 Extend the chain-parameter watch to netuid-keyed items, recording
  one observation per subnet per pass against its own previous value
- [x] 2.2 Add `CollateralLockShare` to the watch set; seed first
  observations without emitting transitions, emit on a later change
- [x] 2.3 Isolate per-subnet read failures so one unreadable subnet does not
  block the rest
- [x] 2.4 Tests: dormant seed emits nothing, unset-to-nonzero emits a
  transition carrying netuid and both values, one bad subnet does not blind
  the pass

## 3. Mining store

- [x] 3.1 Create `fleet/atlas_fleet_mining.py` with additive `mine_econ`,
  `mine_feasibility`, and `mine_state` tables in `var/fleet/fleet.db`, with
  the primary keys and `_pct` unit suffixes from the design
- [x] 3.2 Add the 90-day prune on `mine_econ`, reusing the
  `signal_prices` delete-below-cutoff pattern
- [x] 3.3 Add config: GPU rent bands, burn ceiling, retention horizon,
  holding period, and the inert kill-switch flag
- [x] 3.4 Tests: schema creation is additive and idempotent, prune bounds
  the table, kill-switch makes the screen inert

## 4. Stage A economics screen

- [x] 4.1 Source the protocol miner share from `atlas-kb` with its citation
  and record it; block the computation if no citation is available
- [x] 4.2 Compute miner-accessible alpha as observed emission times the
  sourced share times `(1 - miner_burn)`, applying the burn exactly once
- [x] 4.3 Compute competition from the `Incentive` vector: earner count,
  top-1 share, top-10 share, median earner alpha per day
- [x] 4.4 Compute the constant-product exit haircut against `alpha_in_pool`
  and `root_in_pool`, recorded as its own field
- [x] 4.5 Compute net TAO per month and the staking baseline, and enforce
  the rule that no net figure is produced when any input was null or a leg
  failed
- [x] 4.6 Implement the three failure paths: panel unavailable keeps prior
  rows and renders last-known with age, chain unavailable persists rows with
  `chain-unavailable` confidence and no net figure, per-subnet failure marks
  that subnet unknown only
- [x] 4.7 Tests: burn applied once, no net figure on incomplete read, each
  failure path, percentage unit regression

## 5. Stage B feasibility scan

- [x] 5.1 Scan each active slot over `fleet_files_fts` for
  `min_compute.yml`, miner entrypoint path, GPU tells, and hosted-API tells,
  recording `file:line` evidence
- [x] 5.2 Sha-gate the scan by `(netuid, epoch, sha)` so it recomputes only
  when a slot's commit moves
- [x] 5.3 Emit the verdict from a module-constant closed set; absent
  evidence yields `unknown`, never `possible`
- [x] 5.4 Confirm the scan never builds, installs, tests, or executes subnet
  code
- [x] 5.5 Tests: evidence citation present, moved commit rescans, missing
  evidence yields unknown, no execution path exists

## 6. Stage C ranking and board

- [x] 6.1 Implement the ordered cut ladder: gate, burn ceiling, infeasible
  verdict, hardware floor above band; record the rung and triggering value
  for every exclusion
- [x] 6.2 Rank survivors by net TAO per month and emit the ranked JSON
  report with excluded subnets retrievable
- [x] 6.3 Render `var/fleet/www/mining.html` atomically, LAN-only, carrying
  both the economics and feasibility timestamps
- [x] 6.4 Tests: ladder order, every exclusion carries a reason, golden-file
  render alongside `test_dashboard.py`

## 6b. On-chain identity rung (added 2026-08-12)

- [x] 6b.1 Read `SubnetIdentitiesV3` in the same batched single-block pass
  and decode only the leading `subnet_name` field, permissively
- [x] 6b.2 Persist `subnet_name` and a four-valued `identity_state`
  (named / placeholder / absent / unread) on `mine_econ`, migrating the
  columns into a store that predates them
- [x] 6b.3 Add the `identity-placeholder` rung after the gate and before
  burn, matching a configurable placeholder set against the name's
  normalised first token, quoting the chain name in the reason
- [x] 6b.4 Fail open at the map and closed at the subnet: an unreadable
  identity map leaves the rung inert, an absent entry for one netuid cuts
- [x] 6b.5 Show the on-chain name on the board, escaped
- [x] 6b.6 Tests: live placeholder strings, first-token not substring,
  absent versus unread, ladder order, migration, escaping
- [x] 6b.7 Deployed 2026-08-12: all twelve are flagged (3/39/81
  `deprecated`, 16/42 `unknown`, 94 `pending...`, 73 `Parked`, 47
  `wait (reproduce paper)`, 57/84/86/103 absent) and none is ranked. Only
  4 leave AT this rung — 3, 39, 81, 94; the other eight were already
  gate-disabled and leave earlier, which is the ladder working as ordered

## 6c. Winner-take-all rung (added 2026-08-12)

- [x] 6c.1 Add the `winner-take-all` rung after burn and before
  feasibility, on a configurable `top1_ceiling_pct` (operator: 95%)
- [x] 6c.2 Evaluate on top-1 SHARE, not earner count, and record both in
  the reason; a null share does not cut
- [x] 6c.3 Tests: ten-earner 100% case, wide-but-captured field, contested
  fields survive, null share, ladder order both sides, configurable ceiling
- [x] 6c.4 Deployed 2026-08-12 at block 8823306: 128 observed, **36
  ranked**, 92 cut, of which 17 at this rung. Ranked fell by exactly the 9
  predicted; the other 8 were previously leaving later at `not-minable`
  (31 -> 23) and now leave here instead, which is the ladder reporting the
  earlier and truer reason. 107 Minos (top-1 89.8%) is the new head.

## 7. Stage C2 MCP surface

- [x] 7.1 Add `mining_board(limit?, include_cut?)` to
  `fleet/atlas_fleet_server.py`, bounded result size
- [x] 7.2 Add `mining_subnet(netuid)` returning every economics field with
  its reference block and every feasibility finding with evidence path and
  scanned commit
- [x] 7.3 Add `mining_history(netuid, field?)` reporting
  `insufficient-history` until two observations exist
- [x] 7.4 Enforce read-only posture: `mode=ro`, structured
  `mining-screen-unavailable` on a missing store, dual timestamps on every
  response, unscanned distinct from infeasible
- [x] 7.5 Tests: absent store returns a named error, single observation is
  not a trend, no tool mutates state, bounded payload

## 8. Wiring and deployment

- [x] 8.1 Run the mining pass inline and fail-isolated after
  `atlas_fleet_metrics.run_pass`, with no new systemd unit
- [x] 8.2 Verify a screen failure does not fail the enclosing pass or affect
  reconcile, signals, or metrics
- [x] 8.3 Run the full fleet suite off-device and confirm it stays green
- [x] 8.4 Deployed by `git pull` on the Pi 2026-08-12; both suites green
  on-device (360 fleet, 146 livedata), the pass renders the board at
  block 8823247 (128 observed / 45 ranked / 83 cut), and `mining_board`
  and `mining_subnet` answer with both timestamps

## 9. Documentation

- [x] 9.1 Add the mining-triage section to `fleet/README.md`
- [x] 9.2 Amend `prd.md` §22 and the README "Next step" to record that
  mining triage lands ahead of Phase 6
- [x] 9.3 Record the `CollateralLockShare` watch entry and the dormancy
  finding in `docs/decisions.md`
- [x] 9.4 Record the open questions from the design as dated items,
  including the two-week budget-band decision clock
