## 1. Chain reads and watch

- [x] 1.1 In `livedata/atlas_live.py` `CHAIN_READS`: remove `RootWeightSettingEnabled`, `RootWeightsCap`, `Weights`, `Keys`, `TotalHotkeyAlpha`; add `("BasketConcentrationCap", (), "u16")`
- [x] 1.2 In `KNOB_ITEMS` and `read_knobs`: replace `RootWeightSettingEnabled` with `BasketConcentrationCap` (`u16`); delete the `RootWeightsCap[0]` key and codec override
- [x] 1.3 In `livedata/config.json` `chain_params.items`: remove the two retired items; add `BasketConcentrationCap` (`source: independent`, key `0x658faa385070e074c85bf6b568cf055576f5acd8e01df564185576d062b0454b`, `codec: u16`, `default: 4096`, `governs` text for `swap_basket` buys; state a share ratio only after confirming the u16 normalization in upstream `swap_basket`, else the raw value only); rewrite the `_comment` so it no longer cites `RootWeightsCap` or the curation switch
- [x] 1.4 Update the `WATCH_HASHERS` comment so its example does not cite `RootWeightsCap`

## 2. Remove the root weight read

- [x] 2.1 Delete `root_weights_prefix`, `uid_from_weights_key`, `decode_weight_vector`, `aggregate_destinations`, `read_root_vectors`, `read_root_stake`, `_previous_destination_map`, `poll_root_weights`, and their constants (`WEIGHTS_ITEM`, `ROOT_PROVIDER`, `ROOT_OPERATION`, `BASIS_*`); keep `ROOT_NETUID`
- [x] 2.2 Delete the `root_vectors`, `root_destination_map`, and `rotation_events` DDL (no `DROP`)
- [x] 2.3 In `_cmd_poll_gate`: delete the reseed block and the `root_rotation` summary key
- [x] 2.4 Delete the `root_rotation` block in `livedata/config.json`

## 3. Remove consumers

- [x] 3.1 `fleet/atlas_fleet_signals.py`: delete the `root-rotation` entry in `LIVEDATA_MEASURED`
- [x] 3.2 `telegram/atlas_telegram.py`: delete `root_rotation_events`, its `_ADAPTERS` entry, and the `RootWeightSettingEnabled` next-action branch; add a `BasketConcentrationCap` next-action branch in its place
- [x] 3.3 `telegram/config.json`: delete the `root-rotation` class and the two retired glosses; add a `BasketConcentrationCap` gloss (same ratio rule as 1.3)

## 4. Tests

- [x] 4.1 Update `livedata/tests/test_chain_reads.py`, `test_subnet_param_watch.py`, `test_gate.py`: drop root-read and retired-item cases; add cases for the cap (plain key read, `u16` decode, null read as `assumed-default` 4096, silent first seed), for no read of retired items, and that the pinned config key equals `twox128("SubtensorModule") ++ twox128("BasketConcentrationCap")`
- [x] 4.2 Update `telegram/tests/test_chain_params_class.py`, `test_gate_class.py`, `test_briefing.py`, and `fleet/tests/test_signals.py` for the removed class and glosses
- [x] 4.3 Run every suite the upgrade job runs (`python3 -m unittest discover -s .` in each `*/tests` directory); all pass

## 5. Knowledge

- [x] 5.1 Rewrite Root Reborn allocation facts in `knowledge/corpus/ground-truth.md`, `fact-patterns.md`, and `SOURCES.md`: `set_root_weights` retired at spec 469, curation switch removed, dividends accumulate in place, composition changes only through `swap_basket`, cap is `BasketConcentrationCap` (explicit 4096 at block 9133830)
- [x] 5.2 Regenerate `knowledge/corpus/hashes.json` with `upgrade.atlas_upgrade.regenerate_hashes` (grounded spec 469); knowledge tests pass
- [x] 5.3 In `knowledge/benchmark/atlas_kb_battery.py`: revise `KB-EX-8` and `KB-CF-4` for spec 469; add `KB-CF-6` tempting "validators steer root dividends with set_root_weights"

## 6. Docs and live check

- [x] 6.1 Update `README.md`, `livedata/README.md`, `telegram/README.md`, `fleet/README.md`; add a `docs/decisions.md` entry recording the retirement and the silent drop
- [x] 6.2 Run `python3 livedata/atlas_probe.py check` against live Finney; output shows `"ok": true`
- [x] 6.3 Run `python3 livedata/atlas_live.py read-knobs`; `BasketConcentrationCap` reads 4096 `explicit`
- [x] 6.4 `grep -rn "RootWeightSettingEnabled\|RootWeightsCap\|root_rotation" livedata telegram fleet knowledge/corpus` returns only history notes, not live reads
- [ ] 6.5 Operator, on the Pi after `git pull`: run `python3 knowledge/atlas_kb.py ingest`, read the report, then `python3 knowledge/atlas_kb.py activate --run <id>`; `atlas_kb.py status` shows the new run active
