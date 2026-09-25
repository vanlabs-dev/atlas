# Mining Board Accuracy

## Why

An audit on 2026-09-25 checked the mining board three ways: against subtensor
source (`RaoFoundation/subtensor` `c004ceb`, spec 471), against live Finney
(blocks 9142678 and 9142723), and against the board's own store. The board's
arithmetic reproduces exactly from its inputs, but the model it computes is
wrong for three of its top ten, and two consumers publish a board that does
not exist.

### What is wrong, measured

- **Mechanisms are ignored.** `Incentive` is keyed by
  `NetUidStorageIndex = mecid * 4096 + netuid` (`subnets/mechanism.rs:21-40`).
  Six subnets run two mechanisms (44, 68, 87, 89, 93, 113), and chain keys
  4140, 4164, 4183, 4185, 4189 and 4209 are their mechanism-1 vectors. The
  screen reads mechanism 0 only and credits it with the whole miner pool.
  SN93, board #2 at 410.92 TAO/mo, has `MechanismEmissionSplit = [1311,
  64224]`: mechanism 0 gets 2%. Its real entrant figure is about 8 TAO/mo.
  SN44 sends 0% to mechanism 0 and is stored at 1545 TAO/mo.
- **Owner UIDs count as competitors.** `MinerBurned` is the incentive share
  that landed on owner-coldkey hotkeys (`run_coinbase.rs:733-807`), and those
  UIDs stay in the `Incentive` vector. The screen removes the burn once with
  `(1 - burn)` and then counts the owner UID as an earner and as the top-1.
  SN9, board #3, shows 3 earners and top-1 50.0%. Its owner UID 209 holds
  49.77%. Among independent miners, UID 171 holds 99.56%, so SN9 is
  winner-take-all and should be cut. SN80, board #1, is understated by 20%
  because its owner UID inflates the parity divisor.
- **Cut state is never stored.** `run_econ` writes `cut_reason = NULL` on
  every row. Only `report()` runs the ladder, in memory. The pulse briefing and
  subnt rebuild the ranking from raw rows, so they report "128 ranked, 0 cut"
  with SN120 Affine as board head. The board has 46 ranked, 82 cut, and SN120
  cut as winner-take-all. Their tests pass because the fixtures write a
  `cut_reason` that production never writes.
- **"Not minable" is inferred from absence.** A repo of 20 or more files with
  no `*miner.py` path is marked `closed` and cut. The spec says missing
  evidence is `unknown`. 22 of 43 `closed` subnets have plain miner code,
  including SN4 (`cmd/miner/main.go`), SN3 (`miner/cli.py`) and SN56
  (`miner/asgi.py`). SN3 and SN4 would rank near the top.
- **Feasibility joins stale verdicts.** Verdicts are joined on netuid alone,
  so a re-pointed, discarded, or inactive slot keeps cutting on a previous
  repository's scan. SN117 is cut on a 0-file scan from a dead epoch.
- **A zero-earner field would rank first.** With no earners, the parity model
  divides the pool by 1 and the winner-take-all rung does not fire.

### What was checked and holds

- `alpha_out` is 1.0 alpha per block on the 125 emitting subnets. It is not a
  constant: it follows the halving curve on each subnet's own alpha issuance
  (`run_coinbase.rs:226-238`). The largest issuance today is 6.62M against a
  10.5M first step, so no subnet has halved yet.
- Miner share is 0.5 x (1 - `SubnetOwnerCut`). `SubnetOwnerCut` is unset on
  chain, so the default 11796/65535 applies and the share is 0.41002. The root
  cut comes out of the validator leg only (`run_coinbase.rs:319-332`).
- Burn units are consistent: the panel and the store use 0-100, and chain
  `MinerBurned` is a 0-1 `U96F32`.
- Price: the swap pallet is a weighted Balancer pool. All 128 `SwapBalancer`
  weights are 0.5, so `SubnetTAO / SubnetAlphaIn` and the x*y=k haircut hold
  today. User liquidity is permanently disabled.
- Owner resolution is self-checking. Owner-UID incentive, weighted by each
  mechanism's emission split, matches `MinerBurned` within 1 point on all 125
  emitting subnets at block 9142723.

## What Changes

- The economics leg reads the chain at one finalized block for every figure:
  - alpha emission, owner cut and owner-cut switch
  - mechanism count and emission split
  - per-mechanism incentive
  - owner hotkeys and their UIDs
  - `MinerBurned`
  - pool reserves and balancer weight
  - registration burn, immunity and field size
  - the pool-side switch and on-chain identity

  **BREAKING** for the stored model: the TaoSwap panel is no longer an input
  to the screen.
- Economics are computed per mechanism. Owner-coldkey UIDs are removed from
  the field. The removed share is reconciled against `MinerBurned`, and a
  subnet that fails the reconciliation gets no net figure.
- The cut ladder gains a no-independent-earner rung. The winner-take-all rung
  measures the independent field. A subnet ranks on its best surviving
  mechanism.
- The miner share is derived from chain `SubnetOwnerCut` and `OwnerCutEnabled`
  under a cited 50/50 split. The hand-set `miner_share` config goes away.
- The ladder runs once per pass after feasibility, and its result (cut,
  reason, detail, rank) is stored. The board, the MCP tools, the pulse
  briefing and subnt all read the stored result. **BREAKING** for the
  consumers' re-derivation.
- Feasibility:
  - no entrypoint gives `unknown`, which never cuts
  - entrypoints are recognised across languages and package layouts
  - validator, API, migration and script paths are not entrypoints
  - an unedited template `min_compute.yml` is not a hardware declaration
  - verdicts join only the slot's current epoch and indexed commit
  - superseded verdicts are pruned
- A failed chain read writes nothing. The board keeps the last complete pass
  and shows its age.
- The MCP tools state the parity model, carry each row's own observation time,
  and return cut state on detail and history.
- Chain reads made for the screen are recorded in the live-data audit.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `mining-triage`:
  - the emission base, the miner share source and the burn handling become
    per-mechanism and chain-sourced, with owner reconciliation
  - the ladder is re-specified around the independent field and gains a rung
  - cut state is persisted once
  - feasibility absence semantics and verdict currency are tightened
  - freshness and chain-failure behaviour are restated
- `fleet-search`: the mining tools state the parity model, return persisted
  cut state on every view, and stamp each row with its own observation time.
- `live-data`: chain storage reads made on behalf of the mining screen are
  audited, and the reads are declared for the probe.

## Impact

- `fleet/atlas_fleet_mining.py`: Stage A rewritten around a chain snapshot, a
  new classify stage, the Stage B entrypoint and verdict rules, and render.
- `livedata/atlas_live.py`:
  - new declared reads in `CHAIN_READS`
  - a batched point-read helper for double-map keys (`Uids`, `OwnedHotkeys`)
  - audit records for chain reads
- `fleet/atlas_fleet_server.py`: the mining tools read persisted cut state.
- `telegram/atlas_briefing.py`, `subnt/atlas_subnt.py`: read the persisted
  rank instead of re-sorting raw rows.
- `fleet/config.json`: `miner_share` and `miner_share_source` are removed. A
  reconciliation tolerance is added.
- `mine_econ`: additive columns. `mine_mechanism`: a new per-mechanism table.
  Superseded `mine_feasibility` rows are pruned once.
- Tests:
  - consumer fixtures are produced by the real writer
  - fleet tests stop rendering into the real `var/fleet/www`
- Docs: `fleet/README.md` mining section and `docs/emission-metrics.md`.
- No new unit, port, credential or provider. Chain reads per pass rise by
  about 700 keys (320 UID lookups, 128 owner hotkey lists, and the mechanism
  and pool maps), batched at one block.
- Out of scope: choosing `budget_band` (operator decision D2), registration
  payback, and pruning-floor modelling.
