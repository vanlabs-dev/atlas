# root-weight-drift: brainstorm

Session 1, 2026-09-24. Approved direction: full retirement.

## Cause

Upstream migration `migrate_remove_root_weights`
(`pallets/subtensor/src/migrations/migrate_remove_root_weights.rs`,
RaoFoundation/subtensor @ `923fd1f`) is in the live spec 469 runtime. It:

1. Retires the `set_root_weights` extrinsic and clears every `Weights[ROOT]`
   vector. No vector is seeded in its place. Validators change basket
   composition only through `swap_basket`.
2. Kills the `RootWeightSettingEnabled` gate ("nothing reads it any more").
3. Moves the cap from `RootWeightsCap[ROOT]` to `BasketConcentrationCap`
   (plain `StorageValue`, `u16`, no hashers). The cap now guards
   `swap_basket` buys only. A governance-set cap survives the move.

Non-root `Weights` rows are untouched.

## Effect on Atlas

- `livedata/atlas_probe.py check` fails at block 9133811: both items
  "missing from metadata". The hourly watch pages and every upgrade attempt
  fails the probe gate.
- The chain-parameter watch reads two dead keys as unset defaults.
- The `root_rotation` read (change `rotation-signal-gate`) runs over an empty
  `Weights[ROOT]`. The rotation signal is silently dead.
- The corpus, `docs/decisions.md`, `README.md`, and Telegram glosses still
  describe allocation by `set_root_weights` and the gate as live.

## Goal

Make Atlas match the spec 469 runtime: read no retired storage, watch the
cap where it now lives, and state the new allocation model correctly.

## Success signals

- `python3 livedata/atlas_probe.py check` returns `"ok": true` against live
  Finney.
- `CHAIN_READS` holds no retired item. `BasketConcentrationCap` is watched.
- No code path reads `Weights[ROOT]`.
- Corpus and docs state: `set_root_weights` retired, gate removed, cap is
  `BasketConcentrationCap` on `swap_basket` buys.
- All test suites pass.

## Constraints / non-goals

- Do not build a replacement rotation signal on `swap_basket`. Separate
  change if wanted.
- Keep stored `rotation_events` and chain-param history. Do not migrate or
  delete rows.
- The runtime upgrade job does not trigger for this (corpus is already
  grounded at 469). This is a hand fix.
- The Pi rollout tasks 7.1 to 7.4 stay separate. This change unblocks their
  dry run.

## Options considered

1. **Probe unblock only.** Drop both items, fix corpus facts. Leaves the
   rotation read on an empty map. Rejected: leaves a silent dead signal.
2. **Full retirement.** Chosen.
3. **Full retirement plus a `swap_basket` rotation signal.** Rejected for
   now: needs its own research into keyless reads of `BasketShares` and trade
   events.

## Chosen direction

Full retirement:

- Remove `RootWeightSettingEnabled` and `RootWeightsCap` from `CHAIN_READS`,
  the `chain_params` watch list, and their tests.
- Add `BasketConcentrationCap` to `CHAIN_READS` and the watch as an
  independent plain `u16` item. First observation seeds silently.
- Remove the `root_rotation` read code, its config block, and its tests.
  Drop `Weights`, `Keys`, and `TotalHotkeyAlpha` from `CHAIN_READS` if
  nothing else uses them.
- Rewrite corpus Root Reborn allocation facts, Telegram glosses,
  `docs/decisions.md`, `README.md`, and component READMEs.

## Open questions (for Session 2)

- `fleet/atlas_fleet_signals.py` and `telegram/atlas_telegram.py` read
  `rotation_events`. Decide: remove those consumers, or keep them reading
  history only.
- Default of `BasketConcentrationCap` (`lib.rs:116`) and the live value.
  Confirm before seeding the watch default.
- Should the watch record a one-time "retired" transition for the two dead
  items, or drop them silently?
- Does the knowledge-base battery need new exchanges for the retired
  extrinsic?
