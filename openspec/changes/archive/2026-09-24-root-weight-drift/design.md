## Context

See proposal.md for why. Facts verified live on 2026-09-24 (spec 469,
block 9133830):

- `BasketConcentrationCap`: plain `StorageValue`, `u16`, no hashers. Key
  `0x658faa385070e074c85bf6b568cf055576f5acd8e01df564185576d062b0454b`.
  Raw `0x0010`, explicit value 4096. Upstream default is 4096
  (`DEFAULT_BASKET_CONCENTRATION_CAP`, `lib.rs:116`).
- `Weights[ROOT]` holds zero keys. Non-root `Weights` rows are untouched.
- `atlas_probe.py check` fails only on `RootWeightSettingEnabled` and
  `RootWeightsCap` ("missing from metadata").
- Upstream model: dividends accumulate in place on the subnet they arrive
  on, deposits mirror current holdings, composition changes only through
  `swap_basket`.

## Goals / Non-Goals

**Goals:**
- Probe passes against live Finney.
- No code path reads retired storage or `Weights[ROOT]`.

**Non-Goals:**
- No schema migration. `CREATE TABLE IF NOT EXISTS` statements for
  `root_vectors`, `root_destination_map`, and `rotation_events` are removed,
  but no `DROP` runs. Existing databases keep the tables and rows.
- `subnt` is not changed. It renders `chain_param_events` generically, and
  its test fixture row for `RootWeightsCap` is valid history.

## Decisions

1. **Add the cap as a plain `independent` watch item**, the same shape as
   `BasketTradingEnabled`: pinned `key`, `codec: u16`, `default: 4096`, no
   `hasher`. Alternative: a derived key. Rejected: plain items already use a
   pinned key and the probe checks the declaration.
2. **Remove, do not disable, the root read.** `root_rotation.enabled: false`
   would keep ~250 lines of dead code, three declared reads, and a config
   block that describes a retired mechanism. Removal is smaller to reason
   about. Git history holds the code if a `swap_basket` signal reuses parts.
3. **Drop the retired items silently.** The watch has no removal event type.
   Adding one for a one-off retirement is new code for no repeat use.
   `docs/decisions.md` records the retirement.
4. **`read_knobs` swaps `RootWeightSettingEnabled` for
   `BasketConcentrationCap`** in `KNOB_ITEMS` and deletes the
   `RootWeightsCap[0]` special key. `storage_key_blake2_concat_u16` and
   `WATCH_HASHERS` stay: `SubnetIdentitiesV3` and the netuid-keyed watch
   mechanism still use them. Only the comment that cites `RootWeightsCap`
   as the example changes.
5. **`_cmd_poll_gate` drops the reseed logic and the `root_rotation`
   summary key.** Nothing downstream reads that key except tests.
6. **Telegram**: delete `root_rotation_events`, its `_ADAPTERS` entry, the
   `root-rotation` class block, the two dead glosses, and the
   `RootWeightSettingEnabled` next-action branch. Add a gloss and a
   next-action branch for `BasketConcentrationCap`, so its transition pages
   with a "governs" line and a next step. State a share ratio for the cap
   only after the u16 normalization is confirmed in upstream `swap_basket`;
   otherwise state the raw value.
7. **Fleet**: delete the `root-rotation` entry in `LIVEDATA_MEASURED`. The
   `ingest:root-rotation` state row stays and is inert.
8. **Battery**: `KB-EX-8` keeps its terms (dividends still accumulate in
   place) and rewords the question away from "curation active". `KB-CF-4`
   accepts 469 as the grounding spec. New `KB-CF-6` tempts "validators steer root dividends with
   set_root_weights" and requires "retired" or "removed" plus "469" or
   "swap_basket".

## Risks / Trade-offs

- [A future spec re-adds a root weight mechanism] → The probe and the
  upgrade job catch new storage; a new change designs its reader.
- [The dashboard or a briefing reads `root_destination_map`] → Grep at propose
  showed no reader outside `atlas_live.py`. Tests confirm.
- [Pi DB has a stale `root-rotation` watermark] → Harmless: nothing reads
  it once the class is gone.

## Migration Plan

Hand fix on the workstation, then `git pull` on the Pi. No restart order
matters: the next hourly gate poll runs the new code. The pull does not
reach the knowledge tools: on the Pi, the operator runs
`python3 knowledge/atlas_kb.py ingest`, reads the report, then runs
`python3 knowledge/atlas_kb.py activate --run <id>`. Until then the tools
serve the old allocation facts. Rollback is
`git revert`; the tables still exist, so the old code resumes cleanly (and
reads an empty map).
