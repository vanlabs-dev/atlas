# Design: Mining Board Accuracy

## Context

See proposal.md for the measured defects and the checks that held. The
requirements are in `specs/mining-triage`, `specs/fleet-search` and
`specs/live-data`. This document records how, and why this way.

Grounding used, all at subtensor `c004ceb` (spec 471) and Finney blocks
9142678 and 9142723. `ps/` below means `pallets/subtensor/src/`.

| Fact | Source |
|---|---|
| `alpha_out = get_block_emission_for_issuance(alpha_issuance)`, per subnet | `ps/coinbase/run_coinbase.rs:226-238` |
| Owner cut global `SubnetOwnerCut` u16 (default 11796), per-subnet `OwnerCutEnabled` | `ps/lib.rs:2254-2265` |
| Server half = 0.5 of post-cut alpha; root cut from validator half only | `run_coinbase.rs:319-332` |
| `MinerBurned` = owner-coldkey-hotkey incentive / total, U96F32 0..1 | `run_coinbase.rs:659-807`, `ps/lib.rs:2433` |
| Index = `mecid * 4096 + netuid`; per-mechanism `Incentive` | `ps/subnets/mechanism.rs:21-40`, `ps/lib.rs:2832` |
| `MechanismCountCurrent`, `MechanismEmissionSplit`: `Twox64Concat` | `ps/lib.rs:3523-3529` |
| `Uids`: `Identity(netuid)`, `Blake2_128Concat(hotkey)` → u16 | `ps/lib.rs:2794` |
| `OwnedHotkeys`: `Blake2_128Concat(coldkey)` → Vec<AccountId> | `ps/lib.rs:1833` |
| `SubnetAlphaOutEmission`: `Identity`, last block's value | `ps/lib.rs:1794` |
| Swap: Balancer, `SwapBalancer` quote weight Perquintill (1e18) | `pallets/swap/src/pallet/balancer.rs:66-75`, `mod.rs:110` |
| Pruning: lowest aggregate `Emission`, owner UIDs immortal up to limit | `ps/subnets/registration.rs:379-455` |

Measured and verified independently:
- 6 two-mechanism subnets.
- All 128 balancer weights at 0.5.
- 125 subnets emitting 1.0 alpha per block, and none halved (max issuance
  6.62M against a 10.5M first step).
- The owner-share-to-`MinerBurned` reconciliation holds within 0.01 on
  125/125 emitting subnets. The 3 mismatches (59, 86, 108) are non-emitting.
- Owner resolution took 128 owner coldkeys, at most 25 owned hotkeys each,
  and 320 `Uids` lookups.

## Goals / Non-Goals

**Goals:**
- One chain snapshot at one block is the only economics input.
- A per-mechanism model with the owner removed and self-checked against
  `MinerBurned`.
- The ranking is decided once and stored. Every surface reads it.
- Feasibility never cuts on absence.

**Non-Goals:**
- Choosing `budget_band` (operator decision D2 stays open). The hardware
  rung and net figure behave as today when it is null.
- Modelling registration payback, the pruning floor, or immunity survival.
  They are carried as context only.
- Correcting the knowledge corpus. `docs/emission-metrics.md:56` and
  `docs/decisions.md:334` state the 1 alpha/block constant as universal and
  are corrected here. `knowledge/corpus/` goes through its own grounding
  process and is flagged in tasks, not edited.

## Decisions

### D1. Chain snapshot replaces the TaoSwap panel

Every figure the screen uses is chain state:

| Figure | Chain source |
|---|---|
| alpha emission | `SubnetAlphaOutEmission` |
| burn | `MinerBurned` |
| pool reserves | `SubnetTAO`, `SubnetAlphaIn` |
| weight | `SwapBalancer` |
| switch | `SubnetEmissionEnabled` |
| registration burn | `Burn` |
| name | `SubnetIdentitiesV3` |

Reading them at one block removes cross-source skew. The audit measured
panel-vs-chain price gaps up to 5.4% and burn gaps up to 9 points (a tempo
boundary between the panel block and the chain block). It also removes the
TaoSwap dependency from the pass and the stale-switch attribution problem.

- Alternative, keep the panel as primary and chain as a cross-check: rejected.
  Two sources at two blocks is the defect.
- Alternative, keep the panel as corroboration only: rejected for now. It
  adds a failure mode without changing any figure. Live-data still polls the
  panel for its own purposes.

### D2. Owner set from chain, reconciled against MinerBurned

Resolve owner UIDs the way the runtime does (`get_owner_hotkeys`):
1. Read `SubnetOwner` and `SubnetOwnerHotkey`.
2. Read `OwnedHotkeys(coldkey)` for each distinct owner coldkey.
3. Read `Uids(netuid, hotkey)` for each candidate.

Then compute Σ_m split_m × owner_share_m and compare it with `MinerBurned`
(default tolerance 0.01 absolute, configurable). This is a self-test of the
whole owner and mechanism model at no extra read cost. A mismatch blocks the
figure for that subnet only.

- Alternative, drop the UID whose share matches `MinerBurned`: rejected.
  It is ambiguous on multi-owner-UID subnets and silently wrong on
  multi-mechanism ones (SN93's 25.69% of mechanism 0 is 0.51% subnet-wide).
- Alternative, read the full `Keys` map (about 32k keys): rejected. It
  costs 100x for the same answer.
- Cap: 256 owned hotkeys per coldkey (observed max 25). Over the cap, the
  subnet's owner set is unread and it is unrated.

### D3. Per-mechanism rows in a new table

Add a `mine_mechanism` table keyed (ts, netuid, mecid) holding:
- split
- independent earner count, top-1 and top-10
- owner share
- the mechanism miner pool and its independent pool
- the entrant and incumbent alpha per day
- the rung the mechanism failed, if any

`mine_econ` keeps one row per subnet and gains:
- `rank`, `rank_mecid` and `unrated_reason`
- `owner_share_pct`, `owner_reconcile_delta`
- `balancer_quote`, `immunity_period`, `uids_full`
- `alpha_issuance`
- `miner_share` with its source block

The existing `cut_reason` and `cut_detail` are finally written. All changes
are additive.

- Alternative, a JSON column of mechanisms on `mine_econ`: rejected.
  `mining_history` needs per-mechanism series, and JSON blocks indexed
  queries.

### D4. Stage order and atomicity

`run_pass`:
1. **econ**: builds all rows in memory and inserts them in one transaction.
2. **feasibility**: sha-gated, unchanged cadence.
3. **classify**: runs the ladder over this pass's rows joined to current
   verdicts, and updates `cut_reason`, `cut_detail`, `rank`, `rank_mecid`
   and `unrated_reason` in one transaction.
4. **render**.

Classify runs only when econ committed rows in this pass. A failed econ
leaves the previous pass as the latest complete one, which classify never
touches. Because feasibility changes can move cuts, classify always
re-runs over the latest pass. It is idempotent. The consumers read `rank`
and the cut columns and nothing else.

- Alternative, consumers call `report()`: rejected. subnt and the briefing
  would need the fleet module and config, and `mining_history` would still
  have no cut history.

### D5. Ranking rule

Among surviving mechanisms:
1. The headline is the highest entrant TAO/month.
2. Order is by net where rent is known, else gross, descending, with ties
   broken by netuid.
3. A subnet without a figure is unrated, never ranked last.

The entrant figure for mechanism m:

```
indep_pool_m  = alpha_out/day × miner_share × split_m × (1 − owner_share_m)
entrant_m     = indep_pool_m / (indep_earners_m + 1)
gross_m       = entrant_m × price × (1 − haircut) × 30
```

It is undefined when `indep_earners_m == 0`.

`miner_share = 0.5 × (1 − owner_cut × enabled)`. The 0.5 carries a citation
to `run_coinbase.rs:326-329`, stored in `mine_state`. The `miner_share` and
`miner_share_source` config keys are removed. A leftover key is ignored with
a logged note, never used.

### D6. Price and haircut from the balancer

- Price: `p = (1 − q)/q × SubnetTAO / SubnetAlphaIn`, with q the quote
  weight as Perquintill / 1e18.
- Haircut: the weighted-pool sell formula
  `Δtao = T × (1 − (A / (A + Δα))^((1−q)/q))`, compared with `Δα × p`. At
  q = 0.5 this reduces to today's x·y=k.
- A missing reserve or weight makes the haircut unknown, which blocks the
  figure (it is no longer silently 0).

### D7. Feasibility entrypoints and verdicts

**Entrypoint patterns**, in precedence order, over indexed paths with
excluded components removed:
- `neurons/miner*.py`, `neuron/miner*.py`
- `<pkg>/miner/__main__.py`, `<pkg>/miner/main.py`, `miner/cli.py`,
  `miner/run*.py`
- `cmd/miner/main.go`, `*/miner/*.go`
- `src/bin/miner*.rs`, `*/miner/src/main.rs`
- `miner*/...` package or TS entry (`miner/index.ts`, `miner/src/index.ts`)

**Excluded components:** `validator*`, `api`, `routes`, `migrations`, `test*`,
`scripts` (for `register*` and `*_miner` helpers), `docs`, `examples`,
`vendor`, `node_modules`.

**Verdicts:** `possible`, `needs-gpu` and `unknown` are produced. `closed`
and `stub` stay in the closed set but are produced only on positive cited
evidence, and the scanner has no such rule yet, so they are not produced.
This is deliberate: "no evidence" must not become "cut".

**Template detection:** a `min_compute.yml` whose normalized content
fingerprint matches the bittensor subnet template is recorded as `template`
evidence and ignored for VRAM and GPU. Build the fingerprint from the SN60
and SN33 clones (the observed unedited copies, "NVIDIA A100" at lines 25-30)
and verify it against the upstream template before shipping.

**VRAM evidence line:** searched within the miner section only (L2).

**Keying:**
- Scans are keyed on `index_state.indexed_sha`, not `slots.local_sha`.
- A slot whose indexed sha differs from its local sha is skipped as "index
  behind".
- `latest_feasibility` joins `slots` on (netuid, epoch, indexed sha, status
  active). Anything else is stale or unscanned.
- Rows superseded for a slot are deleted at insert.
- Bump `SCAN_VERSION` to 3.

### D8. Freshness and staleness

- `feasibility_ts` becomes the max `scanned_at` of joined verdicts.
- The board states econ age and block. It warns when the age is over
  `stale_after_hours` (default 18 = 6h pass × 3, matching the fleet
  staleness multiplier).
- MCP `mining_subnet` stamps the row's own ts.

### D9. Live-data additions

Declare these in `CHAIN_READS` so the hourly probe and the upgrade job cover
them:

| Pallet | Items |
|---|---|
| SubtensorModule | `SubnetAlphaOutEmission`, `SubnetOwnerCut`, `OwnerCutEnabled`, `MechanismCountCurrent`, `MechanismEmissionSplit`, `SubnetOwner`, `SubnetOwnerHotkey`, `OwnedHotkeys`, `Uids`, `SubnetTAO`, `SubnetAlphaIn`, `SubnetAlphaOut`, `SubnetProtocolAlpha`, `Burn`, `ImmunityPeriod`, `MaxAllowedUids` |
| Swap | `SwapBalancer` |

Other changes:
- `read_subnet_maps` learns `Twox64Concat` netuid tails and mechanism-index
  keys. `Incentive` is returned keyed by (netuid, mecid), and keys at or
  above 4096 are no longer dropped.
- A new batched point-read helper builds double-map and account keys from
  the declared hashers, at the same block hash, under a key cap.
- Chain reads write an audit row in the same retention store as provider
  calls. The operation is `chain_storage`, with items, key counts, block
  and error category, and no values.

### D10. Test isolation

- Fleet tests must pass an explicit temp `dashboard.www_dir`. A guard test
  fails if a test run writes under the repo's `var/`.
- Consumer fixtures for the briefing and subnt are built by running the
  real classify over seeded econ rows.

## Risks / Trade-offs

- [One chain snapshot is a single point of failure for the pass] → A failed
  read writes nothing and the board serves the last complete pass with a
  staleness warning. The chain leg was already mandatory for competition
  figures.
- [Reconciliation could fail broadly after a runtime change to the burn
  definition] → Every subnet would become unrated, not wrong. The count of
  unrated subnets is shown on the board and in the briefing. The upgrade job
  and probe already watch spec changes.
- [Entrypoint patterns will still miss exotic layouts] → The miss is now
  `unknown` (shown as unverified, not cut), so the cost is a missing
  annotation, not a false exclusion.
- [Removing the panel drops TaoSwap's friendly names] → Names already come
  from chain identity by spec. Chain names win.
- [Per-mechanism ranking changes the head and the top ten at deploy] → The
  first post-deploy briefing will report large top-ten churn. The migration
  records a `model_version` in `mine_state`, and consumers suppress top-ten
  deltas across a model version change and say so once.
- [SubnetAlphaOutEmission is the last block's value] → For a subnet whose
  first emission block has not arrived, or that just stopped, the value is
  0. Such a subnet is unrated ("not emitting"), never ranked on 0.

## Migration Plan

1. Additive schema: new `mine_econ` columns and the `mine_mechanism` table
   in `ensure_schema`, following the existing `_MINE_ECON_ADDED` pattern.
2. `SCAN_VERSION` 3 wipes and rescans feasibility on the first pass. That
   is about 128 slots over the FTS index, with no network.
3. Deploy with `git pull` on the Pi. The first fleet pass writes the new
   model. `model_version` bumps to 2.
4. Verify on the Pi, read-only, before the next briefing:
   - SN93 entrant is about 8 TAO/mo
   - SN9 is cut winner-take-all
   - SN80 is about +25% against the old figure, same price
   - SN3, SN4 and SN56 are not cut not-minable
   - briefing and board counts are identical
   - reconciliation passes on all emitting subnets
5. Rollback: revert the commit. The old code ignores the added columns and
   table. Old rows remain valid for the old model. `mining.enabled=false`
   remains the kill switch.

## Open Questions

- The exact tolerance for reconciliation beyond 0.01. Tune it from the first
  week of stored `owner_reconcile_delta` values. This does not change the
  design.
