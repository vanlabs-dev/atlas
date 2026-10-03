# Corpus snapshot provenance

The three grounding files Atlas retrieves from. Machine-readable hashes in
[hashes.json](hashes.json); ingest verifies them before creating any unit.

| field | value |
|---|---|
| Source of truth | `D:\Coding\Bittensor\IntoOps\intoops-routines\references\` |
| Sync date | 2026-10-04 |
| Coverage date | 2026-10-04 |
| Grounded at | Finney `spec_version` **472** |
| Files | `ground-truth.md`, `fact-patterns.md`, `negative-claim-rules.md` |

## Live facts this snapshot states

Verified 2026-10-04 against Finney RPC (`https://entrypoint-finney.opentensor.ai`):

- Spec **472**. Knobs, emission-switch map, and dust-floor storage read
  together at finalized block 9205342
  (`0xac0cb5a8f3dd6498d08bcf042f72666381c63ff2e7ba5939e38b5fc84136f5dc`).
  Chain-read probe clean at finalized block 9205344
  (`0x16035ae03884e5af0899b11c3220a06c0b313823dfc6c9305cbf278a50495fa5`).
  Tracked clone `f87cada63` (`runtime/src/lib.rs` `spec_version: 473`);
  mechanics are stated as of the spec 472 bump (`e7d89a8b3`). Spec 473
  work (BLS12-381 EVM precompiles, the staking-hotkey cleanup rerun) is
  not live and not stated.
- Emission bar is **rank-pinned**: `EmissionBarRank` unset (default 32),
  `EmissionBarQuantile` 0.75 explicit and inert, `EmissionGateExponent`
  unset (default 3).
- `SubnetEmissionEnabled` is live. 128 keys; **29, 35, 36, 82, 108 off**;
  SN1 on.
- `set_root_weights` is **retired** (`migrate_remove_root_weights`, spec
  469): `Weights[ROOT]` cleared, `RootWeightSettingEnabled` and
  `RootWeightsCap` removed. Dividends accumulate in place.
- `BasketConcentrationCap` is **4096** (explicit, 1/16 of fund NAV). It
  caps basket-trade buys (`swap_basket` and each `swap_basket_many` leg).
- `BasketTradingEnabled` is **true** (explicit). It gates `swap_basket` and
  `swap_basket_many`, the only ways fund composition changes. A hotkey can
  still be frozen.
- `swap_basket_many` (call index 151) is live: 1 to 64 atomic legs, one
  dividend flush and one valuation, every `swap_basket` check per leg.
- Basket trade minimum: each leg's sell proceeds must be at least
  max(`DefaultMinStake`, 0.5 TAO). Transaction validation rejects a
  smaller leg before inclusion, including inside Utility batches,
  `as_derivative`, `if_else`, and Proxy calls.
- The legacy `Alpha`, `TotalHotkeyShares` and `AlphaMapLastKey` storage
  items are gone from metadata (`migrate_alpha_v2_and_unstake_dust_v1`);
  stake shares live in `AlphaV2` / `TotalHotkeySharesV2`.
- Claim dust floors are unset on chain. Code defaults apply: row floor
  min(1 TAO, 10 bps of anchored NAV); slice floor 0.0001 TAO. Cash-first
  claims are not live.

[../supersession-markers.json](../supersession-markers.json) is empty. Add
a marker if a corpus claim goes stale before the next re-sync.

## Re-sync procedure

The runtime upgrade job (`upgrade/atlas_upgrade.py`) runs this procedure
automatically when the live runtime spec changes (see
`docs/runtime-upgrade.md`). The model edits the files in steps 2 to 5; the
job runs every other step and every gate. A manual refresh follows the
same order:

1. Confirm the tracked clone's `spec_version` is at least the live spec.
   If the clone lags, stop. Do not rewrite from a lagging tree. The job
   records this as `waiting` and checks again each run.
2. Read the spec-bump commits in the clone. State only mechanics that are
   still in the live spec. A path that was added and then dropped before
   the spec shipped is not live.
3. Re-read every live knob the corpus states, at one finalized block, and
   cite that block (`python3 livedata/atlas_live.py read-knobs`). Code
   defaults are not live values.
4. Edit the three files so they state current chain facts, not history.
   Update this file's dates, the "Grounded at" line, and the live facts.
   Update the live-chain entry in `docs/decisions.md`.
5. Review `supersession-markers.json`.
6. Regenerate `hashes.json` (sha256 per file, newline-normalized LF;
   update `sync_date`, `coverage_date`, and `grounded_spec`). The job does
   this itself after checking that the "Grounded at" line is the live spec.
7. Run every `*/tests` suite and `python3 livedata/atlas_probe.py check`.
8. Ingest: `python3 knowledge/atlas_kb.py ingest`, and check the report.
9. Commit as vaNlabs and push to `main`. Do not force-push. Do not use
   the subnt deploy key.
10. Activate only after the push lands: `activate --run <run>`.

The originals in `intoops-routines` are never modified or deleted from this
repo (ATLAS-KB-007 closed as not-applicable).
