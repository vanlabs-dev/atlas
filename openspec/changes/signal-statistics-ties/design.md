# Design

## Context

See proposal.md (Why). The facts below were measured read-only on 2026-11-03
and shape the approach.

- **Price vectors.** `signal_prices` holds every fleet price vector since
  2026-07-19: 398 vectors. Of the 397 gaps, 183 are up to 6 h, 189 are
  6 to 7 h, and 25 are longer, up to 24 h.
  Retention is 120 days, so every filled outcome can be recomputed from
  stored vectors today.
- **Gate-crossing anchors.** `gate_events` carries `eligibility_at`. Every
  gate-crossing has a stored vector within 0.3 to 5.4 h of its crossing.
- **Registration block.** `NetworkRegisteredAt` (SubtensorModule, identity
  hasher on the u16 netuid, u64 block) has 128 entries at block 9423800.
- **No historical state.** The public RPC has no archive state ("State
  already discarded" at block 9420000), so a netuid's past registration
  blocks cannot be read. Only the current one can.
- **Block times.** `panel_snapshot` gives 1,496 (block, observed_at) pairs
  since 2026-08-31, at 12.015 s per block.
- **Who runs the code.** Signals, metrics and the board run only in
  `atlas-fleet.service`. The MCP servers do not import them. The Telegram
  scan reads `signal_entries.price_tao` and `status` (`recorded`/`late`) for
  cluster lines.
- **Bot authors.** In the last 30 days, 8,214 commits across the clones. Bot
  addresses include `lium-loop[bot]` (190 commits),
  `harnyx-validator-version-bump-bot[bot]` (79), `dependabot[bot]` (16) and
  `github-actions@github.com` (10).

## Goals / Non-Goals

**Goals:**
- One function decides each outcome. The live fill and `rescore` both call
  it.
- Stored rows stay readable by every existing reader.

**Non-Goals:**
- No tier change. No change to `telegram/config.json`.
- No change to subnt or the web export. Both belong to WP6, and the export
  hold stays.
- Branch-pulse churn is not attributed to authors. `changed_tips` still
  counts bot pushes.

## Decisions

1. **Registration read in livedata.**
   - Add `NetworkRegisteredAt` (identity hasher, u64) to `CHAIN_READS`.
   - Add `read_registration_blocks(config, rpc)`: paged keys plus one
     `state_queryStorageAt` at the finalized head. It returns
     `{netuid: block}`, the head block number and the block hash.
   - No expected default: an absent key means "no subnet" and is never
     substituted.
   - `default_price_fetcher` calls it after the TaoSwap fetch. Either
     failing means no vector this pass.
   - Rejected: reusing the fleet repo `epoch`. It tracks repo identity, not
     chain registration.

2. **Schema (additive, `ensure_schema` migration).**
   - `signal_prices`: add `reg_block`. Add `signal_vectors (ts PRIMARY KEY,
     block_number)`.
   - `signal_entries`: add `anchor_at`, `entry_ts`, `reg_block`, `reason`.
   - `signal_outcomes`: add `v2_status`, `v2_reason`, `v2_entry_ts`,
     `v2_exit_ts`, `v2_return_pct`, `v2_baseline_pct`, `v2_excess_pct`,
     `v2_rules` (integer rules version, 2).
   - Old columns stay. New live fills still write `status`,
     `exit_price_tao`, `return_pct` and `baseline_return_pct` with the
     corrected values, so the Telegram reader and `status` keep working.
     `rescore` writes only `v2_*`.
   - Each pass also re-anchors old gate crossings, then writes `v2_*`
     scores for settled rows that have none, once a vector with
     registration blocks exists. `rescore` does the same for every settled
     row, with a fresh chain map. Found during apply: without this, the
     first pass after deploy scored old gate rows from the crossing.
   - The effectiveness report reads only `v2_*` and counts rows without
     `v2_rules` as unscored.

3. **Choosing a vector.**
   - `vector_at_or_after(t, grace)` returns the earliest vector with
     `t <= ts <= t + 6 h`. Entry uses the anchor time, exit uses the due
     time.
   - No vector after the window has passed: the row is unavailable
     (`no-vector`).
   - Rejected: the nearest vector on either side. A vector before the anchor
     would measure a price from before the alert.

4. **Same-subnet test.**
   - Both vectors carry `reg_block`: the return counts when the two are
     equal, otherwise reason `re-registered`.
   - Entry vector is legacy (NULL) and the exit vector is new: clean when
     `block_time(exit.reg_block) <= entry_ts - 1 h`.
   - Both are legacy: `rescore` reads the current map `R`.
     - `block_time(R) <= entry_ts - 1 h`: clean.
     - `block_time(R)` inside the window: `re-registered`.
     - `block_time(R)` after the exit: `unverified`. About 78 of 1,559
       filled rows today, 6 of them gate-crossings.
   - `block_time` interpolates between `signal_vectors` and `panel_snapshot`
     anchors. Before the first anchor it extrapolates at 12.015 s per block,
     labelled assumed in code.
   - The baseline median uses only netuids that pass the same test for that
     window.

5. **Gate-crossing anchor.**
   - The ingest reads `COALESCE(eligibility_at, observed_at)` and stores it
     as `anchor_at`. `created_at` keeps the crossing time.
   - Horizons fall due from `anchor_at`, and `rescore` recomputes due times
     from it. The source store is still opened read-only.

6. **Statistics.**
   - An event moment is the entry vector (`v2_entry_ts`).
   - Excess is the subnet return minus the baseline over the same window.
   - The bootstrap resamples whole moments: 2,000 draws with
     `random.Random(20261103)`, the median of the pooled excess per draw,
     and the 2.5 and 97.5 percentiles. Below 10 moments the report prints no
     interval.
   - `meets_promotion_sample` means moments >= the floor and the horizon is
     readable. `beats_baseline` means `ci_low > 0`.
   - Rejected: clustering by event id. Root-rotation would then show 87
     "independent" events from 8 market windows.

7. **Ties.** `_percentile_ranks` groups equal values and assigns
   `(first + last) / 2 + 0.5` over n. Order-independent.

8. **Bot filter.**
   - `metrics.bot_author_patterns`: case-insensitive regexes on the author
     email. The default list is `\[bot\]@`, `^(github-)?actions?@github\.com$`
     and `^(dependabot|renovate)`.
   - `compute_activity` skips matching commits for windowed counts and
     `a30`. All-time context totals stay unfiltered and labelled as context.
   - The filter takes effect on the next pass, because activity is
     recomputed from `git log` every pass.

9. **Cue removal.**
   - `score_subnet` stops returning `cue`/`cue_kind`. The score weights are
     unchanged: divergence magnitude still scores.
   - The board drops the glyph, `dir_label`, and the promising/dangerous
     filters and tags.
   - The divergence thesis becomes "Activity rank N, price rank M: K points
     apart."
   - The metrics report drops `quadrant`.
   - Rejected: shadow-measuring the cue (operator decision 1A).

## Risks / Trade-offs

- [`NetworkRegisteredAt` is renamed by a runtime] → The probe fails hourly
  and pages. Price vectors stop until it is fixed: measurement stalls, and
  alerts do not.
- [The 6 h grace and a 6 h timer leave some horizons unavailable] → Measured
  in `rescore` output before deploy. The figure is reported, not hidden. The
  grace is a code constant, so changing it is a code change.
- [Fewer filled rows after the rescore] → Intended. The report shows
  `unavailable` and `unverified` tallies next to the figures.
- [Rescore writes fleet.db] → Backup copy first, new columns only,
  idempotent.
- [subnt's `why_phrase` still says "building faster than the price
  reflects"] → Out of scope (public, masked timer). Listed for WP6.

## Migration Plan

1. Before the Pi pull, save the board (`build_board` read-only) and the
   effectiveness output. `ensure_schema` now adds columns, so the backup
   must come before anything opens fleet.db with the new code: the pass,
   `rescore`, and the `effectiveness` and `status` CLIs.
2. Stop `atlas-fleet.timer`. Run `git pull` on the Pi, then the fleet and
   livedata test suites.
3. Back up fleet.db with `conn.backup()`. Run `rescore`, then
   `effectiveness`.
4. Run one reconcile pass via `systemd-run`. Check that one vector holds a
   `reg_block` for every netuid. Diff the board against step 1.
5. Start the timer. The operator runs a Telegram `/restart` so `atlas-live`
   loads `CHAIN_READS`.

Rollback: revert the commits. The added columns are ignored by old code.
Restore the backup only if a write went wrong.
