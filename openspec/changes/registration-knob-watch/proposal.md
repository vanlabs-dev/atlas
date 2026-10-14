# Proposal

## Why

On 2026-10-14 the subnet registration rules changed on the live chain with
no runtime upgrade. New-subnet immunity dropped from 120 days to 60, and the
lock-cost reduction interval from 16 days to 8. Atlas saw neither change:
the chain-parameter watch does not read these settings, and the knowledge
corpus still says immunity lasts "4 months". A setting change on a running
chain never triggers the upgrade job, so only a watch catches it.

## What Changes

- The chain-parameter watch reads three more plain storage items at the
  gate poll's block: `NetworkImmunityPeriod`, `NetworkLockReductionInterval`
  and `NetworkRateLimit`. They are declared in the chain-read list, so the
  hourly probe checks them against live metadata.
- `read-knobs` reports the same three values.
- Each item carries a plain-English description. The Telegram alert names
  the setting in words and shows block counts as days.
- `CollateralLockShare` gets the description its alerts lacked.
- The corpus states the 60-day immunity, the 8-day reduction interval with
  the exact decay rule, and the 2-day registration gap, each read at block
  9,278,789.

The first observation of each new item seeds silently, as for every
watched item. Today's change is recorded in the corpus, not paged.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `live-data`: adds a requirement that the registration settings are
  watched.
- `telegram-integration`: adds a requirement that block-count settings
  render in days under a plain label.

## Impact

- `livedata/atlas_live.py` (`CHAIN_READS`, `KNOB_ITEMS`),
  `livedata/config.json` (three watched items with pinned keys).
- `telegram/atlas_telegram.py` (label and unit display),
  `telegram/config.json` (descriptions, display map).
- `knowledge/corpus/ground-truth.md`, `knowledge/corpus/SOURCES.md`,
  `knowledge/corpus/hashes.json`; re-ingest and activate on the Pi.
- The corpus source of truth outside this repo needs the same correction.
