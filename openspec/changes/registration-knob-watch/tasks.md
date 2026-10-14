# Tasks

## 1. Watch

- [x] 1.1 Declare `NetworkImmunityPeriod`, `NetworkLockReductionInterval` and `NetworkRateLimit` (`u64`, no hasher) in `CHAIN_READS` and `KNOB_ITEMS`. Verify the livedata suite passes.
- [x] 1.2 Add the three items to `chain_params.items` in `livedata/config.json`, with keys pinned from `twox128`, codec `u64`, the spec 478 code defaults, and descriptions. Verify a test that each pinned key equals its derived key, and a watch test that 864000 → 432000 records one transition.

## 2. Alert wording

- [ ] 2.1 Add `governs` text for the three items and `CollateralLockShare`, and a `display` map (label, unit) to `telegram/config.json`. Render labelled block-count settings in days. Verify a test for the immunity scenario and that unlabelled settings render unchanged.

## 3. Corpus

- [ ] 3.1 Correct `ground-truth.md` (60-day immunity, the lock-cost decay rule with the 8-day interval, the 2-day gap) and record the reads in `SOURCES.md`. Regenerate `hashes.json`. Verify the knowledge suite passes.

## 4. Deploy

- [ ] 4.1 After the push is approved, pull on the Pi, run every suite, run the chain-read probe, ingest and activate the corpus, and confirm the next gate poll seeds the three items. Verify `chain_params` rows exist for all three.
