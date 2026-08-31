## 1. Chain and code verification (read-only)

- [ ] 1.1 On the Pi, read at one finalized block: `RootWeightSettingEnabled`,
  `RootWeightsCap` (root entry), `EmissionBarRank`, and the presence of
  `BetaIndexSnapshot`; record block, values, provenance
- [ ] 1.2 From the tracked clone with `git show v452:...` (no checkout), confirm
  the single-hotkey 18% predicate in `staking/lock.rs` and its eligible-alpha
  definition
- [ ] 1.3 Confirm the v449 migration flips `RootWeightSettingEnabled` and pins
  `RootWeightsCap`; read `DefaultRootWeightsCap` and the cap's storage
  declaration (hasher, codec)
- [ ] 1.4 Confirm which `RootWeightsCap` entry `set_root_weights` consults;
  decide root-entry read vs enumeration and record the finding in design.md
- [ ] 1.5 Confirm `stake_into_basket` gating status at v452
- [ ] 1.6 Read `beta_pricing.rs` and `docs/concepts/beta-tokens.mdx` at v452
  for the baseline, index, display price, and `BasketTwr` definitions

## 2. Corpus re-sync

- [ ] 2.1 Rewrite the conviction section: single-hotkey 18% gate, eligible
  alpha definition, one-year age gate retained, dated to spec 447
- [ ] 2.2 Rewrite the Root Reborn section: curation live since spec 449,
  `RootWeightsCap` 1/16, on-chain beta pricing (baseline, index, display
  price, display beta, `BasketTwr`), spec 451 claim hardening,
  `stake_into_basket` status as found
- [ ] 2.3 Add spec 448 lines: `TotalAlphaStaked` per netuid, `move_stake_limit`
  with slippage protection, linked limit orders, all-hotkeys unstake
- [ ] 2.4 Replace the negative-claim rules that deny curation and the 10% gate
  with dated corrections; add a rule that a beta price is never quoted live
- [ ] 2.5 Update `SOURCES.md` (sync date, coverage date, known staleness
  section) and regenerate `hashes.json`; keep `supersession-markers.json`
  empty
- [ ] 2.6 Knowledge tests green off-device

## 3. Benchmark battery

- [ ] 3.1 Add the takeover-threshold case (tempts 10%; expects 18%
  single-hotkey dated to spec 447)
- [ ] 3.2 Add the curation-live case (tempts "dormant"; expects live since
  spec 449 with the 1/16 cap)
- [ ] 3.3 Add the beta-price case (asks for a current value; expects refusal
  plus the display convention)
- [ ] 3.4 Expected-evidence markers and scorer entries for all three; modelval
  and knowledge tests green

## 4. Live-data watch and cross-check

- [ ] 4.1 Add `RootWeightsCap` to `chain_params.items`: derived key for the
  consulted entry, `u16` codec, runtime default with source, `governs` text
- [ ] 4.2 Extend the key self-test to cover the new derived key
- [ ] 4.3 Set `gate_signal.above_count_tolerance` to 1 with a config comment
  stating the recalculation-boundary reason
- [ ] 4.4 Tests: new item observed and seeded, null read persists default as
  `assumed-default`, transition on value change, tolerance one passes N plus
  or minus one and fires at two
- [ ] 4.5 Livedata suite green off-device

## 5. Alert and voice vocabulary

- [ ] 5.1 Add `RootWeightsCap` to `classes.chain-parameter-change.governs` in
  `telegram/config.json`
- [ ] 5.2 Add beta, basket, basket index, and display price to `voice.gloss`;
  check the lexicon for a conflicting synonym
- [ ] 5.3 Telegram suite green off-device

## 6. Documentation

- [ ] 6.1 README: status paragraph, `knowledge-base` and `live-data` rows
- [ ] 6.2 Decision log: chain-evidence entry for the re-sync with block and
  values from 1.1
- [ ] 6.3 Decision log: record the divergence finding (105 events in 7 days,
  31 on 32 of 48 polls, theta changed on 39 of 47 polls) and the tolerance
  decision; close the deferred `above_count == 32` re-check as explained

## 7. Deployment and acceptance

- [ ] 7.1 Push; `git pull` on the Pi; both suites green under system Python
- [ ] 7.2 Ingest and activate the corpus; run the battery; record run id,
  metrics, and verdict; roll back to the previous run if the gate fails
- [ ] 7.3 Confirm the next hourly pass persists `RootWeightsCap` with the
  expected value and provenance, and records no divergence event at a count
  of 31 or 32
- [ ] 7.4 `test --class chain-parameter-change` renders the new gloss
