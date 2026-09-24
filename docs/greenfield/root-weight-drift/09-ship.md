# root-weight-drift: ship

Session 4, 2026-09-24. Verify PASS (`08-verify.md`). Change archived to
`openspec/changes/archive/2026-09-24-root-weight-drift/`. Main specs
`live-data` and `telegram-integration` synced.

## What shipped

- `CHAIN_READS` drops `RootWeightSettingEnabled`, `RootWeightsCap`,
  `Weights`, `Keys`, and `TotalHotkeyAlpha`, and adds
  `BasketConcentrationCap`. The live probe passes at spec 469.
- The chain-parameter watch and `read-knobs` read `BasketConcentrationCap`
  (plain `u16`, default 4096, pinned key). The retired items were dropped
  silently; their history rows stay.
- The root weight vector read, destination map, `rotation_events`
  recording, the Telegram `root-rotation` class, and its fleet ledger
  ingestion are removed. Tables and rows stay. No `DROP`.
- The cap gets a Telegram gloss and a next-action line. The u16 scale
  (65535 = 100%, 4096 = 1/16) was confirmed in upstream `lib.rs` at
  `923fd1f` (review finding R5).
- Corpus, battery (`KB-EX-8`, `KB-CF-4` revised, `KB-CF-6` added; 36
  exchanges), `README.md`, component READMEs, and `docs/decisions.md`
  state the spec 469 model.

## Deviations from the plan

- The netuid-keyed watch tests now use a fixture item
  (`CollateralLockShare`, identity hasher), per design decision R6.
- The generic bool-watch tests use `BasketTradingEnabled` in place of
  the retired switch.
- `knowledge/tests` battery counts moved from 24 to 25 grounded
  exchanges. The 0.9 floor boundary is unchanged: 2 misses pass, 3 fail.

## Follow-ups

- **Operator, task 6.5 (open):** on the Pi, after `git pull`, run
  `python3 knowledge/atlas_kb.py ingest`, read the report, then
  `python3 knowledge/atlas_kb.py activate --run <id>`. Confirm with
  `python3 knowledge/atlas_kb.py status`.
- Re-run the retrieval battery on the Pi against the new corpus run. The
  last accepted run predates `KB-CF-6`.
- The `runtime-upgrade-pipeline` dry run (tasks 7.1 to 7.4) is unblocked.
- A `swap_basket` rotation signal is a separate change if wanted.
