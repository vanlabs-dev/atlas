# Design

## Context

- All code is in `fleet/atlas_fleet_mining.py`, which runs in three stages:
  - Stage A, economics: `subnet_economics`, `mechanism_economics`.
  - Stage B, feasibility: `scan_slot`, sha-gated.
  - Stage C, the ladder: `classify_cut`, `decide`. It stores the result once.
- Every surface reads the stored result: `report`, `render_html`, the
  `atlas-fleet` MCP tools in `fleet/atlas_fleet_server.py`, and subnt
  `mining_facts`.
- Rent and net are computed in Stage A today, before feasibility is known.

Verified on 2026-11-03:
- Pi `fleet.db`, pass 2026-11-02 23:28 UTC.
- A fresh read-only snapshot at block 9422785, taken through
  `read_mining_snapshot` from the workstation.

Today's runtime:
- `atlas-fleet.timer` runs every 6 h and includes the mining pass.
- `hermes-gateway` MCP children import the module.
- `atlas-subnt.timer` is masked. The briefing is off.

## Goals / Non-Goals

**Goals:**
- The headline follows what real low-end earners get.
- Hardware and rent are honest per subnet.
- Thin-pool slippage covers the subnet's own sale pressure.
- Prune risk is a rung.
- GPU evidence is read across the miner subtree.
- The MCP board is compact.

**Non-Goals:**
- No read of `Tempo` or `Dividends`. Prune risk uses a configured floor.
- No Telegram class for consensus switches.
- No price-decay forecast over time.
- No change to the web export or subnt payload (WP6).
- No change to the cut order before winner-take-all.

## Decisions

1. **Entrant = min(parity, p25 earner).**
   - p25 uses linear interpolation over the independent earners' alpha/day
     in that mechanism.
   - With a fresh snapshot, today's effect is SN8 147.6 → 0.07 alpha/day,
     lium.io 48.4 → 0.35 and SOMA 47.6 → 0.05. SN4, SN9 and SN90 keep their
     place, because their few earners do earn that much.
   - **Alternative rejected:** expected value scaled by earners over
     registered UIDs. The operator noted that registered slots are mostly
     idle and rotate out, so they are neither competitors nor a divisor.
   - The rejected "zero-earner cut" would have cut 7 of the top 10 on an
     arbitrary threshold.

2. **Zero-earning slots are context only.** The row carries `subnetwork_n`
   and the independent earner count. No new column is needed.

3. **Prune risk uses a config floor in blocks.** It cuts when `uids_full`
   is set and `immunity_period < mining.min_immunity_blocks`. The default is
   720, two default tempos of 360.
   - Reading `Tempo` would change `SUBNET_MAP_ITEMS` and couple to the
     frozen probe module (WP5).
   - Today it cuts SN53 (1 block) and SN118 (300). SN8 (1200) survives.

4. **Required band is decided in Stage C.**
   - Stage A stores gross only.
   - Stage C joins feasibility, derives `required_band`, sets
     `rent_band`/`rent_tao_month` on the row, writes `net_tao_month` on each
     mechanism and the row, ranks on net, and stores `payback_days`.
   - Band order is `cpu` < `consumer-gpu` < `datacenter-gpu`, sorted by the
     bands' `vram_gb`.
   - Required band: `possible` is `cpu`. Declared VRAM gives the smallest
     band covering it. `needs-gpu` without VRAM gives the smallest GPU band,
     marked assumed (operator decision 2026-11-03). Unknown or unscanned
     gives the budget band, marked assumed.
   - Measured with the v4 rules on the Pi plus the fresh snapshot: assuming
     80 GB would have cut 13 subnets (SN9, SN120, SN14 from the top 10).
     With 24 GB assumed, the hardware rung cuts none today: no repo declares
     more than 24 GB (declared: 4, 8, 8, 16, 24, 24).
   - `budget_band` null: every survivor is unrated `no-budget-band`.
   - `baseline_tao_month` and `staking_apy_pct` are retired: the column
     stays and is always null.

5. **Haircut = slippage of `alpha_out_day * subnet_sale_fraction`** into the
   read-block pool.
   - Default fraction is 1.0. This is conservative: everyone who receives
     alpha sells it the same day.
   - The model ignores the same day's TAO injection. The label says so.
   - It replaces the own-sale haircut, which is one part of that flow, and
     `daily_sale_fraction` is retired.
   - New `pool_days = alpha_in_pool / alpha_out_day`.

6. **Scanner v4.**
   - Miner subtree: any indexed path with a component matching `miner*` or
     `neurons`, minus the `exclude_path_parts` and validator components.
     Files are capped by `max_subtree_files` (default 400) in path order.
   - Strong tokens are matched in source and dependency files
     (`requirements*.txt`, `pyproject.toml`, `Dockerfile*`, `*.yml`).
   - Weak tokens are matched in any subtree file as `gpu-mention`.
   - A strong token gives `needs-gpu` even with no recognised entrypoint:
     positive evidence wins over a missing entrypoint. Absence of both stays
     `unknown`.
   - Read-only sweep with these rules on the Pi: 10 `possible` and 6
     `unknown` slots move to `needs-gpu`. The largest miner subtree is 390
     files.
   - Matching is by regex with word boundaries.
   - `SCAN_VERSION` goes to `"4"`, which invalidates all stored verdicts.
     The next pass rescans 107 slots from FTS. The read-only sweep on the Pi
     took seconds, so it stays well inside the service timeout.

7. **Compact MCP board.**
   - `report()` keeps its full shape for the HTML board.
   - A new `compact_view(view)` builds the MCP rows. Dropped from the board
     row:
     - `displacement_rank`
     - raw reserves and issuance
     - the per-mechanism dump
   - Every compact field is read with `.get()`, so a store that has not
     migrated returns nulls, not an error.

8. **Schema.**
   - `ensure_schema` gains a `mine_mechanism` added-column list.
   - The MCP path never migrates (`mode=ro`).
   - The deploy runs one mining pass right after the pull, so the window
     with an old schema is minutes long. The code tolerates it either way.

9. **`MODEL_VERSION` 3, `MINING_VERSION` 0.3.0.** The briefing and subnt
   already suppress top-ten deltas across a version change.

10. **Rent config.**
    - `consumer-gpu` 1.5 TAO/month: RTX 4090 secure $0.45/h x 720 h =
      $324, at TAO $222.13.
    - `datacenter-gpu` 6.3 TAO/month: H100 spot $1.95/h = $1,404.
    - `rent_source` records "lium ls 2026-11-03; TAO $222.13 Taostats".
    - Rent stays hand-set. Atlas makes no network calls of its own.

11. **Context reads (measured on the Pi, 2026-11-03, finney entrypoint).**

    | Item | Keys | Time |
    |---|---|---|
    | current mining snapshot | | 48 s |
    | `BlockAtRegistration` (enumerated) | 38,868 | 351 s |
    | `Axons` | 6,623 | 83 s |
    | `Weights` | 1,527 | 17 s |
    | `ValidatorPermit`, `LastUpdate`, `Emission` | about 130 each | 3 to 4 s each |

    - The node keeps state for 256 blocks (refused at 260 blocks back), about
      51 minutes. The new reads add about 7.5 minutes, so everything is read
      at one pinned block.
    - `BlockAtRegistration` uses point reads for `(netuid, uid)` with uid
      below `SubnetworkN`. That is about 30,200 keys, with no enumeration
      and no stale entries (38,868 enumerated against 30,207 registered).
    - `Weights` and `LastUpdate` are keyed by `NetUidStorageIndex`. The key
      reader gains a two-part identity tail `(index u16, uid u16)`.
    - Codecs: `Vec<bool>`, `Vec<u64>`, `Vec<(u16,u16)>`, `EpochConsensus`
      (u8 index, 0 Yuma, 1 Null, anything else fails closed), and an
      `AxonInfo` prefix decoder that reads the first 8 bytes (`block: u64`)
      and nothing else. Each codec gets a regression test.
    - A context failure is per item and per subnet. It marks the context
      unread and leaves the economics read intact.

12. **Activity facts.**
    - Registrations in 7 days: registration block ≥ snapshot block − 50,400.
    - Weighted UIDs: the union of nonzero targets over rows whose source UID
      holds `ValidatorPermit` and whose `LastUpdate` for that mechanism is
      within `ActivityCutoff` (already read for `live_hyperparams`).
    - Widest row: the maximum count of nonzero targets in those rows.
    - Axons: entries with block ≥ snapshot block − 50,400.
    - v486 removes an axon on UID replacement and trimming
      (`subnets/uids.rs:126`, `:364`), so the count holds no deregistered
      hotkeys.
    - These facts are stored in the `mine_econ` columns `registered_7d`,
      `weighted_uids`, `widest_weight_row`, `axons_served_7d` and
      `consensus_mode`.

13. **Consensus tracker lives in the fleet store, not the parameter watch.**
    - Every `chain_param_events` row becomes an instant
      `chain-parameter-change` alert.
    - Under the operator's "record, no alert" decision, a mining-owned
      table `mine_consensus_events (netuid, prev_mode, new_mode,
      block_number, ts)` and the per-pass `consensus_mode` column hold the
      history.
    - The first pass seeds without events. Events are never pruned (small).
    - "Since" is the switch block or "first seen by Atlas" with its date.
    - SN82 holds an explicit Yuma entry. That does not show it ever ran
      Null.
    - Promoting this to an alert later is a separate change.

14. **Null rounding check.**
    - The Null guide says the reported u16 incentive is quantized and does
      not drive payouts.
    - During apply, compare the incentive-derived p25 on SN120 (694 UIDs)
      with the per-UID `Emission` (exact alpha) for UIDs without a validator
      permit.
    - If they differ by more than one rounding step, Null subnets take
      their earner figures from `Emission`, and the board labels which
      source was used. The result is recorded here.

15. **Owner pruning flag.** A pending `NullPruningTarget` below `SubnetworkN`
    is shown with both numbers. v486 trimming spares owner and immune UIDs
    and removes the lowest-emission UIDs first. It is a flag, not a cut.

## Risks / Trade-offs

- **Seven more probed items.** A runtime rename of any of them fails the
  hourly probe and the upgrade job's gate. The reader fix is the
  operator's.
- **The pass grows to about 8.5 minutes of chain reads.** Load on the public
  endpoint rises every 6 hours. If the node's state window shrinks below
  the read time, the pinned read fails. The context then goes unread and
  the economics still stand.

- **p25 on 2 or 3 earners is coarse.** The parity cap bounds it. The view
  shows both figures.
- **Strong-token false positives** (a `"cuda"` default in shared code)
  become hardware cuts under the consumer band. The cut detail cites path
  and line, so it can be argued with.
- **Unknown verdicts (42 of 107) are assumed to fit the budget band.** The
  view marks them "assumed".
- **The conservative haircut slightly over-penalises deep pools.** The
  effect is under 1% for pools over 2M alpha.
- **The TAO price moves rent in TAO terms.** TAO fell 27% in 30 days. Rent
  needs a manual refresh, and the date is in the config.
- **The web fixture export publishes `net_tao_month` and `cut_reason`.**
  With a band set, they leak rent and the band name onto the public site.
  The leak lists match `budget_band` and "budget band", not
  `above-budget-band`. Operator decision: hold every fixture export until
  WP6. The export runs by hand, and `atlas-subnt.timer` is masked.
- **SN4 Targon leads at about 934 TAO/month with no GPU evidence.** The
  figure follows the evidence as read. It is a reason to read the cut and
  evidence columns, not proof that a CPU miner earns it.
