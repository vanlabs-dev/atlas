## Why

Spec 469 ran upstream migration `migrate_remove_root_weights`
(RaoFoundation/subtensor @ `923fd1f`). It retired `set_root_weights`,
cleared `Weights[ROOT]`, killed `RootWeightSettingEnabled`, and moved the
cap from `RootWeightsCap[ROOT]` to `BasketConcentrationCap`. Atlas still
reads the retired items, so the probe fails at every run, the upgrade job
cannot pass its probe gate, and the root rotation signal reads an empty map.
Brainstorm: `docs/greenfield/root-weight-drift/01-brainstorm.md`.

## What Changes

- Remove `RootWeightSettingEnabled` and `RootWeightsCap` from the declared
  chain reads, the chain-parameter watch, and the knob read. Drop them
  silently: no retirement page. Stored history rows stay.
- Add `BasketConcentrationCap` (plain `u16`, default 4096) to the declared
  chain reads, the watch, and the knob read. Its first observation seeds
  silently.
- **BREAKING** Remove the root weight vector read, the destination map, and
  root-rotation event recording. Drop `Weights`, `Keys`, and
  `TotalHotkeyAlpha` from the declared reads.
- **BREAKING** Remove the `root-rotation` Telegram class and its fleet
  effectiveness-ledger ingestion. Existing `rotation_events`,
  `root_vectors`, `root_destination_map`, and ledger rows stay in place.
- Rewrite corpus, glosses, and docs to state the spec 469 model:
  `set_root_weights` retired, the curation switch removed, dividends
  accumulate in place, composition changes only through `swap_basket`, the
  cap is `BasketConcentrationCap` on `swap_basket` buys.
- Revise battery exchanges `KB-EX-8` and `KB-CF-4`. Add one exchange that
  tempts the stale "validators set root weights" claim.

Non-goals: no replacement rotation signal on `swap_basket`; no row
migration or deletion; no Pi rollout (tasks 7.1 to 7.4 of
`runtime-upgrade-pipeline` stay separate).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `live-data`: the watch set drops the two retired items and adds
  `BasketConcentrationCap`; the root weight vector read and root-rotation
  event requirements are removed.
- `telegram-integration`: the root-rotation delivered class is removed.

## Impact

- Code: `livedata/atlas_live.py` (`CHAIN_READS`, `KNOB_ITEMS`,
  `read_knobs`, root read functions, `_cmd_poll_gate`),
  `fleet/atlas_fleet_signals.py` (`LIVEDATA_MEASURED`),
  `telegram/atlas_telegram.py` (adapter, curation next-action).
- Config: `livedata/config.json` (`root_rotation`, `chain_params`),
  `telegram/config.json` (glosses, `root-rotation` class).
- Tests: livedata, telegram, and fleet suites that cover removed behavior.
- Knowledge: `knowledge/corpus/*`, `knowledge/benchmark/atlas_kb_battery.py`.
- Docs: `README.md`, `docs/decisions.md`, `livedata/README.md`,
  `telegram/README.md`.
- Operator: on the Pi, after `git pull`, re-ingest and activate the
  corpus (`knowledge/atlas_kb.py ingest`, then `activate --run <id>`).
- Unblocks: `python3 livedata/atlas_probe.py check` and the upgrade job's
  probe gate.
