# Corpus snapshot provenance

The three grounding files Atlas retrieves from. Machine-readable hashes in
[hashes.json](hashes.json); ingest verifies them before creating any unit.

| field | value |
|---|---|
| Source of truth | `D:\Coding\Bittensor\IntoOps\intoops-routines\references\` |
| Sync date | 2026-10-16 |
| Coverage date | 2026-10-16 |
| Grounded at | Finney `spec_version` **479** |
| Files | `ground-truth.md`, `fact-patterns.md`, `negative-claim-rules.md` |

## Live facts this snapshot states

Verified 2026-10-16 against Finney RPC (`https://entrypoint-finney.opentensor.ai`):

- Spec **479**. Knobs, emission-switch map, dust-floor storage and the
  subnet registration rules read together at finalized block 9289187
  (`0xf2a5c090d94a4948c7df4d54f4b573876d742314c13685d49f51f41d5400149c`).
  Chain-read probe clean at finalized block 9289189
  (`0x5db0e065a651bfe0aa05651eeb95ef4cdccc6614dfc2a2032e29336b6fad37a6`).
  Tracked clone `f4786f908` (`runtime/src/lib.rs` `spec_version: 479`,
  bump `e66c7eed7`, merge PR #3256).
- Spec 479 shipped:
  - Third-party staking-list growth opt-out:
    `set_reject_staking_hotkey_growth` (call 153) sets bit 1 of
    `AccountFlags` (off by default, follows a coldkey swap, moves no funds).
    With it on, a stake transfer from another coldkey must land on a hotkey
    the receiver lists or owns (`AccountRejectsStakingHotkeyGrowth`). EVM
    staking precompile `setRejectStakingHotkeyGrowth(bool)` /
    `getRejectStakingHotkeyGrowth(bytes32)`. Caps unchanged: 256 entries for
    the coldkey's own actions, 128 through other accounts. Which coldkeys
    set the flag was not read.
  - Single-subnet hotkey swaps rename a delegator's entry when its old
    position exists nowhere else. A delegator that would need a second entry
    and is flagged or at the 128 cap keeps its stake, lock and auto-stake
    target on the old hotkey (`HotkeySwapStakeRetained`). On root, its
    earned basket shares stay claimable under the new hotkey through the new
    storage item `HotkeySwapBasketCredits`, which `claim_root` and coldkey
    swaps include within their bounds. The validator's own split is refused
    past 256 entries before the swap fee. All-subnets swaps still rename.
  - `StakingHotkeys` also keeps a hotkey that an `AutoStakeDestination`
    points at; setting an auto-stake destination and creating a hotkey are
    held to the 256-entry cap.
  - EVM: EIP-7702 authorization lists capped at 255 entries on every entry
    path, checked before signature recovery (`EVM.AuthorizationListTooLarge`);
    the EVM nonce survives balance-account reaping
    (`NoncePreservingAccountProvider`, new storage item `EVM.AccountNonces`).
  - Not live: the benchmarked `swap_hotkey_v2` weight. Dispatch keeps the
    shared `swap_hotkey` envelope until reference measurements exist, and
    `set_reject_staking_hotkey_growth` reuses the `set_reject_locked_alpha`
    weight.
  - No storage item Atlas reads was added, removed, renamed or reshaped; the
    probe is clean. The new items (`HotkeySwapBasketCredits`,
    `EVM.AccountNonces`) are not read.
- Carried from spec 478 and still live:
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
- Subnet registration rules at finalized block 9289187:
  `NetworkImmunityPeriod` **432,000** (60 days),
  `NetworkLockReductionInterval` **57,600** (8 days), `NetworkRateLimit`
  **14,400** (2 days), all explicit. Root set the first two on 2026-10-14
  with no runtime upgrade; the subtensor announcement gives the old values
  as 120 and 16 days. `NetworkMinLockCost` (1 TAO) and
  `NetworkLastLockCost` (884.38 TAO) are not in the knob read; those values
  are from a one-off read at finalized block 9,278,789 on 2026-10-14.
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
