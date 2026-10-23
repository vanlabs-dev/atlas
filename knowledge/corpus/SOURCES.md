# Corpus snapshot provenance

The three grounding files Atlas retrieves from. Machine-readable hashes in
[hashes.json](hashes.json); ingest verifies them before creating any unit.

| field | value |
|---|---|
| Source of truth | `D:\Coding\Bittensor\IntoOps\intoops-routines\references\` |
| Sync date | 2026-10-24 |
| Coverage date | 2026-10-24 |
| Grounded at | Finney `spec_version` **484** |
| Files | `ground-truth.md`, `fact-patterns.md`, `negative-claim-rules.md` |

## Live facts this snapshot states

Verified 2026-10-24 against Finney RPC (`https://entrypoint-finney.opentensor.ai`):

- Spec **484**. Knobs, emission-switch map, dust-floor storage and the
  subnet registration rules read together at finalized block 9348505
  (`0x9e1b8b95cc3bc80cacfa42a5cbaf06fcfaac617711a9180c0985cac8c9a2b6a6`).
  Chain-read probe clean at finalized block 9348506
  (`0x9e82da9035779a116f94b2f1a02ddbddbc33ebaf61615b2c2b7dfa54b19c7822`).
  Tracked clone `5749dbfbe` (`runtime/src/lib.rs` `spec_version: 484`).
  `spec-484.diff` has base `spec_version: 482`, so it repeats the 483
  changes; the items below are the ones absent from `spec-483.diff`.
- Spec 484 shipped (Finney moved from 483):
  - Subnet lifecycle for reporting: new storage item `SubnetState`
    (netuid → `Registered`, `Started`, `PendingDissolution`, `Dissolving`),
    backfilled at upgrade by `migrate_subnet_state`
    (`backfill_subnet_lifecycle_state_v1`). `NetworksAdded` still decides
    what runtime operations may target. Reporting runtime APIs (metagraph,
    selective metagraph and mechagraph, dynamic info, neuron info, subnet
    state, emissions history, stake info, delegate info,
    `current_alpha_price_all`) list every subnet with a `SubnetState`
    entry, so a dissolved subnet stays visible until its idle-block cleanup
    finishes. Once cleanup settles stake, each hotkey's stake reads as zero
    as soon as that hotkey has been paid out. While a subnet is pending or
    dissolving, the stake-availability API reports nothing available.
  - `claim_root_with_hotkey` admission budget is 130 units (one validator,
    128 subnet slots and the root slot; was 129).
  - EVM subnet precompile `getLiquidAlphaConsensusMode(uint16)` and
    `setLiquidAlphaConsensusMode(uint16,uint8)` (0 Current, 1 Previous,
    2 Auto). The setter dispatches `sudo_set_liquid_alpha_consensus_mode`
    signed by the caller, so in practice only the subnet owner succeeds.
  - The swap pallet writes `SwapBalancer` and the balancer reservoirs only
    when the value changes. Values are unchanged.
  - `SubnetState` is not read. No storage item Atlas reads was added,
    removed, renamed or reshaped; the probe is clean.
  - The rest of the 484-only diff is SDK, btcli, docs and fee-snapshot
    tests (for example `bdaa99a27`, the btcli identity prompts). It
    changes no chain mechanic.
- Carried from spec 483 and still live (the 484 diff carries the same
  coldkey-swap, proxy, fee-wrapper and precompile hunks as the 483 diff):
  - Coldkey swaps merge into an already-used destination
    (`ColdKeyAlreadyAssociated` retired). Shares and basket watermarks add
    together (an overflow fails the swap), and staking lists merge. Queued
    subnet registrations, their escrow, miner collateral and leases move
    with the coldkey. The destination keeps its identity, its decaying-lock
    choices and any auto-stake destination it set. It also keeps its
    `AccountFlags` when it is in use or has flags set. The source's
    auto-stake setting moves only onto a blank destination, and lineage is
    recorded only onto a destination with no staking associations and no
    lineage. Rate-limit clocks and hotkey-swap cooldowns keep the later
    stamp. Proxy grants and `RealPaysFee` stay with the old coldkey. Still
    refused: a hotkey destination, a destination with any lock holding mass
    or residual conviction, a breached destination opt-out (locked alpha,
    staking-list growth), and work above one call (256 hotkeys across both
    lists, 1,024 positions, 128 destination lock rows, 32 owned queued
    registrations, a 256-entry registration queue).
  - `announce_coldkey_swap_v2` (call 155, EVM `announceColdkeySwapV2`)
    checks the cleartext destination before the fee and reserves it
    (`ColdkeySwapDestinationReservations` / `ColdkeySwapReservedDestination`)
    against hotkey registration, hotkey swaps onto it, cross-coldkey stake
    and lock transfers, and other announcements
    (`ColdkeySwapDestinationReserved`). The reservation ends at execute,
    clear, reset, destination release
    (`release_own_coldkey_swap_destination_reservation`, call 154), or at
    the execution block plus `ColdkeySwapReannouncementDelay`. Every V2
    call pays the key-swap cost. The legacy hash announce (call 125) stays
    and neither checks nor reserves. A failed `swap_coldkey_announced` keeps
    its announcement.
  - Root `reset_coldkey_swap_keep_locked` (call 156) clears the
    announcement and dispute but keeps the coldkey restricted to announce,
    dispute, execute and `submit_encrypted` (`ColdkeySwapDisputes` = 0).
    A swap to another coldkey or a full `reset_coldkey_swap` releases it.
  - Proxy types `Validate` (19: weights, serving, `associate_evm_key`,
    `Commitments.set_commitment`) and `Weights` (20: weights calls only),
    granted by the hotkey (#3194). Neither admits value movement or
    wrappers.
  - `RealPaysFee` redirection follows up to three `proxy` levels with
    consent at every hop; a homogeneous proxy batch can be the last level.
  - New subnets register with `SubnetEmissionEnabled` true (also on a
    reused netuid). Existing subnets are untouched; root can still switch
    any subnet off.
  - A due Null epoch takes the block's single epoch slot first.
  - Fee-free wrappers (`proxy` and the Utility batches, `as_derivative`,
    `if_else`) are validated call by call in the pool: every proxy hop must
    be a zero-delay grant whose type admits the call (`InvalidRealAccount`
    otherwise), and every inner call faces its outer-call checks.
  - EVM: the dispatch precompile (`0x06`) refuses static frames, and it and
    the proxy precompile's `proxyCall` prepay gas per input byte and refuse
    input longer than the normal block length. An over-weight call spends
    only its own frame's remaining gas.
  - Not live: the first Validate proxy merge (#3041, `d8921c2e0`) and its
    follow-ups, reverted (`768c79ce3`) before 483 shipped, and still
    reverted at 484. The live
    `Validate` / `Weights` types are #3194. Also not live: the
    coldkey-keyed proxy merge on coldkey swap (`6b2d0e356`), replaced by
    `043f17768` and `c6bbc008c`, which leave proxies with the old coldkey.
    Also not live: benchmarked weights for `announce_coldkey_swap_v2`, the
    reservation release and `reset_coldkey_swap_keep_locked`. They dispatch
    with aliased weights from the existing coldkey-swap calls
    (`pallets/subtensor/src/weights.rs`).
  - The coldkey-swap items (`ColdkeySwapDestinationReservations`,
    `ColdkeySwapReservedDestination`, `ColdkeySwapV2PolicySnapshots`) are
    not read. `ColdkeySwapDisputes` uses block 0 as the recovery-lock
    marker; Atlas does not read it.
  - Open, outside the corpus: `livedata/atlas_live.py`
    `SUBNET_PARAM_DEFAULTS` records an absent `SubnetEmissionEnabled` key
    as `false`. The runtime's storage default is `DefaultTrue` (unchanged
    at 484). Every live subnet has an explicit key (128 of 128), so no
    reading is affected today. Fixing it means changing a livedata test
    that pins the `false` default, which is outside the upgrade job's
    scope.
- Carried from spec 482 and still live (not touched by the 483 or 484
  diffs):
  - Yuma miner payouts apportion the accumulated miner budget in full by
    incentive (remainders in UID order).
  - The validator-share floor check compares in `u64` parts; the smallest
    accepted share is `root_baseline_share + 1`.
- Carried from spec 481 and still live:
  - Per-subnet emission weights: `SubnetEmissionWeights` holds
    `[burn, recycle, owner, validator, miner]` in `u64::MAX` parts, seeded
    at upgrade from each subnet's legacy owner-cut state
    (`migrate_seed_subnet_emission_weights`; default `[0, 0, 0.18, 0.41,
    0.41]`). The owner or root sets it with
    `sudo_set_subnet_emission_weights` (call 114): burn and recycle 0,
    owner at most 33% (lease-created subnets at least 18%), validator at
    most 50%, miner at least 33%. Owners are limited to one change per
    50,400 blocks per subnet; the first change is free, root is exempt,
    dissolution clears the key. EVM subnet precompile
    `setSubnetEmissionWeights` / `getSubnetEmissionWeights`.
  - Root off the top: root is paid `min(V, r) x alpha_out` with
    `r = V0 x root_tao x TaoWeight / (root_tao x TaoWeight + alpha_issuance)`,
    `V0` the default validator share, recomputed every block. A set with
    `V <= r` fails (`ValidatorEmissionTooLowToPreserveRoot`). Consensus,
    dividend split, child/parent stake and the pool side use the global
    `TaoWeight`.
  - Legacy owner-cut setters (`sudo_set_subnet_owner_cut` call 28,
    `sudo_set_owner_cut_enabled` call 92, precompile `setOwnerCutEnabled`)
    return `Deprecated`. `SubnetOwnerCut` and `OwnerCutEnabled` stay in
    metadata unchanged in shape, but no emission path reads them.
  - The dissolution lock refund deducts accrued owner alpha
    (`SubnetOwnerCutAccrued`), not the owner's current share.
  - Not live: the per-subnet TAO-weight multiplier
    (`SubnetTaoWeightMultiplier`, `BaseValidatorEmissionShare`,
    `ValidatorEmissionBelowTaoWeightFloor`, `effective_tao_weight`) and
    spec 480's frozen per-subnet `SubnetTaoWeight`. Both were dropped
    before 481 shipped. `migrate_remove_subnet_tao_weight` clears any
    leftover `SubnetTaoWeight` keys. `sudo_set_subnet_emission_weights`
    has an interim weight envelope, not a benchmarked weight.
  - `SubnetEmissionWeights`, `SubnetCreatedViaLease` and
    `SubnetOwnerCutAccrued` are not read, so no subnet's live split is
    stated.
  - Open, outside the corpus: the mining screen
    (`fleet/atlas_fleet_mining.py`) still derives miner share from
    `SubnetOwnerCut` and `OwnerCutEnabled`. That is right only for subnets
    still on their seeded vector. Correcting it needs a
    `SubnetEmissionWeights` read and a `fleet/` change.
- Carried from spec 479 and still live:
  - Third-party staking-list growth opt-out:
    `set_reject_staking_hotkey_growth` (call 153) sets bit 1 of
    `AccountFlags` (off by default, moves no funds; follows a coldkey swap
    onto a fresh key, while a merge keeps the destination's flags).
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
  - `HotkeySwapBasketCredits` and `EVM.AccountNonces` are not read.
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
  root-only. The `claim_root_with_hotkey` admission budget is 130 units on
  every network since spec 484.
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
- `SubnetEmissionEnabled` is live. 128 keys for 128 subnets; **82 and 103
  off**; SN1 on.
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
- Subnet registration rules at finalized block 9348505:
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
