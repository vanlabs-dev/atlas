# Corpus snapshot provenance

The three grounding files Atlas retrieves from. Machine-readable hashes in
[hashes.json](hashes.json); ingest verifies them before creating any unit.

| field | value |
|---|---|
| Source of truth | `D:\Coding\Bittensor\IntoOps\intoops-routines\references\` |
| Sync date | 2026-10-14 |
| Coverage date | 2026-10-14 |
| Grounded at | Finney `spec_version` **478** |
| Files | `ground-truth.md`, `fact-patterns.md`, `negative-claim-rules.md` |

## Live facts this snapshot states

Verified 2026-10-14 against Finney RPC (`https://entrypoint-finney.opentensor.ai`):

- Spec **478**. Knobs, emission-switch map, and dust-floor storage read
  together at finalized block 9277041
  (`0x03d9509323b0b4ecbc38c356a01648adf33bc22da31b550700acdcfa70481eb0`).
  Chain-read probe clean at finalized block 9277043
  (`0xe9f2c2adb02506abfdf20be0e1bf6f1fc4a35162c56f67c1b3c2da42df4115ab`).
  Tracked clone `850f2755b` (`runtime/src/lib.rs` `spec_version: 478`,
  bump `8677391fb`, merge PR #3237).
- Spec 478 shipped:
  - `StakingHotkeys` repair (`3010d1099`, PR #3235):
    `migrate_restore_staking_hotkeys_v1` re-adds hotkeys with an `AlphaV2`
    row or a nonzero `BasketClaimed` watermark to the coldkey's list, at most
    64 rows per idle block, once the alpha conversion and
    `migrate_cleanup_staking_hotkeys` have finished. It moves no stake and
    keeps issuance. Its progress is a storage alias outside the metadata;
    whether it has finished was not read.
  - Stake-exit gas in the EVM staking precompile and the contracts chain
    extension (`41afc661d`, `900bd9e8f`, PR #3233): the `StakingHotkeys`
    walk is reserved for the signer's current list plus one (capped at the
    declared bound) plus one sizing read, per envelope slot for
    `unstake_all*`. Signed extrinsic weights still reserve the walk at the
    cap.
  - No storage item in the metadata was added, removed, renamed or
    reshaped. The remaining 478 changes are node logging (vendored
    `sc-informant`) and regenerated docs.
- Carried from spec 477 and still live: the subnet owner or root sets
  `min_difficulty` (call 4) and `difficulty` (call 24) under the admin
  window and per-parameter owner rate limits; the `Owner` proxy admits them
  and the PoW toggle; root can override the owner cooldown; netuid 0 stays
  root-only. The `claim_root_with_hotkey` admission budget is 129 units on
  every network.
- Carried from specs 474 and 475 and still live:
  - Per-subnet epoch consensus (`SubnetEpochConsensus`, Yuma default,
    owner/root `sudo_set_epoch_consensus` call 111). Null mode: one permit
    for the largest-stake hotkey, miner incentive from its weight row,
    stake-proportional dividends, no bonds, 2,500-UID shared cap, bounded
    pruning via `sudo_trim_null_uids_batch` (call 112, 64 UIDs per call).
    Which subnets run Null was not read.
  - Owner-enabled fee-free PoW registration (`pow_register`, call 152;
    `NetworkPowRegistrationAllowed` default off) with its own difficulty
    price. Owners toggle burn and PoW registration independently; not both
    off.
  - Childkey fan-in capped at 100 parents per child per subnet; longer
    existing lists are kept but cannot grow.
  - Basket trade minimum is root-settable: `BasketMinTradeTao`
    (`sudo_set_basket_min_trade_tao`, call 113, code default 0.5 TAO).
    Not part of the knob read, so its live value is not stated.
  - Not live: the 4K-UID Null cap (`d1c250341`), replaced by the
    2,500-UID cap (`8fc43030a`) before 474 shipped.
- Carried from spec 473 and still live: queued subnet registrations prepay
  into a per-entry escrow (`NetworkRegistrationEscrow`) refunded on failed
  settlement (`NetworkRegistrationCancelled`); a new pool holds exactly
  the TAO paid; EIP-2537 BLS12-381 precompiles at `0x0b` to `0x11`;
  `StakingHotkeys` entries are kept until a pair's last alpha key and
  basket watermark are gone (`migrate_cleanup_staking_hotkeys_v3`).
- Emission bar is **rank-pinned**: `EmissionBarRank` unset (default 32),
  `EmissionBarQuantile` 0.75 explicit and inert, `EmissionGateExponent`
  unset (default 3).
- `SubnetEmissionEnabled` is live. 128 keys; **29, 35, 36, 82, 92, 108,
  116 off**; SN1 on.
- `set_root_weights` is **retired** (`migrate_remove_root_weights`, spec
  469): `Weights[ROOT]` cleared, `RootWeightSettingEnabled` and
  `RootWeightsCap` removed. Dividends accumulate in place.
- `BasketConcentrationCap` is **7865** (explicit, about 12% of fund NAV;
  code default 4096 = 1/16). It caps basket-trade buys (`swap_basket` and each `swap_basket_many` leg).
- `BasketTradingEnabled` is **true** (explicit). It gates `swap_basket` and
  `swap_basket_many`, the only ways fund composition changes. A hotkey can
  still be frozen.
- `swap_basket_many` (call index 151) is live: 1 to 64 atomic legs, one
  dividend flush and one valuation, every `swap_basket` check per leg.
- Basket trade minimum: each leg's sell proceeds must be at least
  max(`DefaultMinStake`, `BasketMinTradeTao`). Transaction validation
  rejects a smaller leg before inclusion, including inside Utility
  batches, `as_derivative`, `if_else`, and Proxy calls.
- The legacy `Alpha`, `TotalHotkeyShares` and `AlphaMapLastKey` storage
  items are gone from metadata (`migrate_alpha_v2_and_unstake_dust_v1`);
  stake shares live in `AlphaV2` / `TotalHotkeySharesV2`.
- Subnet registration rules, read at finalized block 9,278,789 on
  2026-10-14 (change: registration-knob-watch): `NetworkImmunityPeriod`
  **432,000** (60 days), `NetworkLockReductionInterval` **57,600** (8
  days), `NetworkRateLimit` **14,400** (2 days), all explicit;
  `NetworkMinLockCost` 1 TAO, `NetworkLastLockCost` 884.38 TAO. Root set
  the first two the same day with no runtime upgrade; the subtensor
  announcement gives the old values as 120 and 16 days. The
  chain-parameter watch now reads all three.
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
