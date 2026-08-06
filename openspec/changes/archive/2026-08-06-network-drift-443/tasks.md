## 1. Config and codecs

- [x] 1.1 Add `EmissionBarRank` to `gate_signal.storage_keys` in `livedata/config.json` with the pinned key `0x658faa385070e074c85bf6b568cf0555d33bd686290d014475513443305882be`, and add `EmissionBarRank: 32` to `assumed_defaults`; extend the block comment with the v443 code reference and the note that the v441 release notes' "64" is wrong
- [x] 1.2 Add a `chain_params` config block: `enabled` (default false), `above_count_tolerance`, and a watch list where each item carries `source` (`gate-poll` or `independent`), `codec`, `default`, `governs` (short description), and — for independent items — `key`. Seed with the three bar parameters sourced from the gate poll, plus `RootWeightSettingEnabled` (`0x658faa385070e074c85bf6b568cf055543f3dc4dfa03eb004921d663110b49b0`, bool, default false, independent)
- [x] 1.3 Add `decode_u16` and `decode_bool` alongside `decode_u64f64` in `livedata/atlas_live.py`; `decode_bool` MUST reject a correct-length payload that is neither encoded true nor encoded false, not only wrong lengths
- [x] 1.4 Add a codec dispatch keyed by the item's declared codec, so no call site assumes `U64F64`

## 2. Livedata schema

- [x] 2.1 Add `rank INTEGER`, `rank_provenance TEXT`, `bar_mode TEXT`, `above_count INTEGER` to `gate_state` as additive columns, leaving existing rows NULL
- [x] 2.2 Add `prev_theta REAL` to `gate_events` as an additive column, leaving existing rows NULL
- [x] 2.3 Create the `chain_params` observation table (item, value, provenance, observed_at, block_number, block_hash)
- [x] 2.4 Create the `chain_param_events` transition table (item, prev_value, new_value, prev_provenance, new_provenance, observed_at, block_number) with the id ordering the notifier watermark reads

## 3. Gate poll learns the bar mode

- [x] 3.1 Add `EmissionBarRank` to `_GATE_ITEMS`, decoded as u16 with bounds [0, 65535] and null persisted as the configured default marked `assumed-default`
- [x] 3.2 Derive `bar_mode` from the effective rank (`rank` when N > 0, `q-mass` when N == 0) and persist it with every observation
- [x] 3.3 Persist rank, rank provenance, and bar mode in the `gate_state` insert
- [x] 3.4 Return the decoded N, q, and h with provenances from `poll_gate_state` for the watch to consume, and retire the ephemeral `params_changed` boolean as the record of change (the durable path in group 4 replaces it)
- [x] 3.5 Include rank, its provenance, and the bar mode in the gate `status` output

## 4. Chain-parameter watch

- [x] 4.1 Persist the gate poll's decoded N, q, and h as watched-item observations at the gate observation's reference block, with no second storage read
- [x] 4.2 Read independently sourced items at the gate poll's already-obtained finalized block hash when the gate pass runs
- [x] 4.3 Run the watch over independently sourced items even when `gate_signal.enabled` is false, obtaining its own finalized head, so a curation-switch flip survives a gate rollback
- [x] 4.4 Persist one observation per item per pass, with per-item failure isolation for independent items: a failed or malformed read records a health event and persists nothing for that item while the others still persist
- [x] 4.5 Record a transition event when a persisted value differs from the most recent previously persisted value for that item; no hysteresis, no confirmation window
- [x] 4.6 Seed the first ever observation of an item without recording a transition (no previous value to differ from)
- [x] 4.7 Suppress transition emission when only the provenance changed at an unchanged value, keeping the provenance change visible in the observation history
- [x] 4.8 Make the watch inert when `chain_params.enabled` is false, leaving the gate poll and crossing detection untouched
- [x] 4.9 Surface the latest value and provenance per watched item in the `status` output

## 5. Crossing attribution and storm suppression

- [x] 5.1 Persist the previous gate observation's theta on each recorded crossing event
- [x] 5.2 Add the re-seed lifecycle guard to `run_gate_pass`: on a pass recording a bar-parameter transition (effective N, q, or h changed), clear and re-seed all sides from current shares and theta and record no crossing events, mirroring the existing gate-inactive to gate-active guard
- [x] 5.3 Compute and persist the above-bar count beside the effective N on each rank-mode pass
- [x] 5.4 Raise a health event when a rank-mode pass's above-bar count diverges from N beyond `above_count_tolerance`, without suppressing events or discarding the pass
- [x] 5.5 Skip the count check entirely in q-mass mode, where no fixed count is implied
- [x] 5.6 Surface the latest above-bar count and effective N in the `status` output

## 6. Telegram: gate-crossing body

- [x] 6.1 Extend the gate-event read in `telegram/atlas_telegram.py` to carry the crossing's bar mode, effective rank/quantile, and previous theta
- [x] 6.2 Add a single-fact line naming the active bar mode (rank-pinned with the effective rank, or q-mass with the effective quantile) in house style, no em or en dashes
- [x] 6.3 Add a single-fact line stating the bar's movement since the previous observation, and attribute the crossing to the bar rather than the subnet where the bar movement alone accounts for the side change
- [x] 6.4 Render a crossing whose bar mode or previous theta is NULL (recorded before this change) without asserting a mode or a movement

## 7. Telegram: chain-parameter-change class

- [x] 7.1 Add the `chain-parameter-change` adapter reading `chain_param_events` read-only past its own watermark, registered in the class table
- [x] 7.2 Render the body: parameter, previous and new values with provenances, reference block, and the configured `governs` description, as single-fact lines with HTML plus plain-text fallback, routing the operator-supplied description through the shared escaping path
- [x] 7.3 State the resulting selection mode in words when a rank transition moves the bar between rank-pinned and q-mass
- [x] 7.4 State that the bar was re-priced for every subnet and that per-subnet crossing pages were withheld, when the transition's pass re-seeded sides
- [x] 7.5 Page every transition with no cooldown and no digest tier
- [x] 7.6 Make the class inert when disabled, leaving other classes' watermarks untouched

## 8. Tests (off-device)

- [x] 8.1 Codec tests: u16 and bool round-trip, wrong-length payloads rejected, a correct-length non-boolean byte rejected, a `U64F64` payload rejected by `decode_u16` and the reverse
- [x] 8.2 Gate poll tests: rank explicit, rank null to `assumed-default`, bar mode `rank` for N > 0 and `q-mass` for N == 0, mode derived from an `assumed-default` rank, out-of-bounds rank persists nothing
- [x] 8.3 Watch tests: bar parameters recorded from the gate poll without a second read, independent items on the gate poll's block, watch runs with the gate kill-switch off, first observation seeds without a transition, value transition recorded, provenance-only change not emitted, per-item failure isolation, no re-emission across restart, disabled watch inert
- [x] 8.4 Storm-suppression test reproducing the 2026-08-03 migration: a bar-parameter transition in a pass where several subnets change side records zero crossing events and re-seeds every side
- [x] 8.5 Attribution test: a stationary share with a bar that moved across it is attributed to the bar; a moved share against a near-static bar is attributed to the subnet
- [x] 8.6 Invariant tests: agreeing count silent, diverging count raises a health event without discarding the pass, no check applied in q-mass mode
- [x] 8.7 Notifier tests: mode and movement lines correct for both modes, NULL mode or NULL prev-theta renders without asserting either, transition pages once with no cooldown, re-seeded pass explained in the body, configured description escaped, disabled class leaves other watermarks untouched
- [x] 8.8 Full livedata and telegram suites green off-device

## 9. Corpus re-sync 440 to 443

- [x] 9.1 Rewrite the emission-gate section of the upstream `ground-truth.md`: rank-pinning is the live mechanism, q-mass is the N == 0 fallback, `EmissionBarRank` default 32 at v443, live Finney has rank unset so the default applies and q = 0.75 is inert; keep the standing rule that the mechanism is never stated without a live read
- [x] 9.2 Record that a rank-pinned bar is itself a demand share and therefore moves, so a subnet can change side without its own demand changing; and that when fewer than N subnets have positive demand the bar falls to the smallest positive share and the gate stops biting
- [x] 9.3 Add a Root Reborn section to the upstream `ground-truth.md`: beta baskets under a global escrow coldkey, allocation by `set_root_weights`, `claim_root` redemption, root registration required to earn root dividends with the remainder recycled, root unstake hold interval, calls 122/123 retired, seed migration complete, and the curation gate currently false so the null strategy is the live baseline
- [x] 9.4 Update the upstream `fact-patterns.md` and `negative-claim-rules.md`: do not describe the bar as a q-mass quantile, do not state a rank or quantile without a live read, do not claim root dividends are being curated or reinvested yet
- [x] 9.5 Record the spec 441/442/443 sequence with mainnet dates in the emission-model history, including the 2026-08-03 bar reset (`migrate_reset_emission_gate_bar`, theta dropped about 14.5% in one poll), so the 440 grounding is superseded rather than contradicted
- [x] 9.6 Re-snapshot the three files into `knowledge/corpus/`, refresh `hashes.json` and `SOURCES.md` (sync and coverage dates, known-staleness note), and confirm `supersession-markers.json` stays empty
- [x] 9.7 Extend the retrieval benchmark with questions covering rank-pinned bar selection, the bar-moves-under-you consequence, and the dormant Root Reborn curation gate, including at least one refusal case that must not be answered from the stale q-mass claim
- [x] 9.8 Record the chain evidence in `docs/decisions.md`: the v443 code references, the 2026-08-06 chain reads, the release-note/code discrepancy on the rank default, and the 2026-08-03 migration evidence from Atlas's own store (theta series, the four-subnet cluster, 28 + 4 = 32)

## 10. Deploy

- [x] 10.1 Ship to the Pi via `git pull` with the watch and its Telegram class disabled
- [x] 10.2 Verify one poll writes rank 32 `assumed-default` and bar mode `rank`, with crossing detection unchanged
- [ ] 10.3 Verify the above-bar count reads 32 against an effective N of 32 with no divergence health event, confirming the share pipeline agrees with the chain — **BLOCKED on the TaoSwap `/v2/subnets/` HTTP 500 outage that began 2026-08-06T03:34** (provider-side, unrelated to this change; the pass fails closed with `above_count` NULL as designed, and `gate_sides` still holds 32 above / 96 below from the last good pass). Re-run once TaoSwap recovers.
- [x] 10.4 Enable the watch; confirm all four items seed observations with no spurious transition events
- [x] 10.5 Seed the `chain-parameter-change` watermark, then enable the class, and confirm the scan picks it up without disturbing the other five
- [x] 10.6 Re-ingest the corpus on device and re-run the retrieval benchmark, recording the run id
- [x] 10.7 Record deployment acceptance and update the READMEs to the new standing
- [x] 10.8 Note for the ~2026-08-11 calibration read: events 1 to 26 predate bar-mode and prev-theta tracking, the four events at 2026-08-03T21:06 are migration artefacts rather than demand signals, and SN9's three crossings were share-side movement against a near-static bar
