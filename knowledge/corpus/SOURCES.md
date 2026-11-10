# Corpus snapshot provenance

The three grounding files Atlas retrieves from. Machine-readable hashes in
[hashes.json](hashes.json); ingest verifies them before creating any unit.

| field | value |
|---|---|
| Source of truth | this directory, `knowledge/corpus/` in `vanlabs-dev/atlas` (the IntoOps copy is closed and never synced from) |
| Sync date | 2026-11-11 |
| Coverage date | 2026-11-11 |
| Grounded at | Finney `spec_version` **490** |
| Files | `ground-truth.md`, `fact-patterns.md`, `negative-claim-rules.md` |

## Live facts this snapshot states

Verified 2026-11-11 against Finney RPC by the runtime upgrade job:

- Spec **490**. Knobs and the emission-switch map read together at
  finalized block 9478248
  (`0x477dbed57b8ac98be02b6e3e4ffca26927082a8a65b00a82b3e3e9fc258a5517`).
  Chain-read probe clean at the same finalized block 9478248 (no failures:
  every item Atlas reads keeps its name, shape and default). Source: the
  subtensor `v490` tag (`d967d1358883`, `runtime/src/lib.rs`
  `spec_version: 490`); `spec-490.diff` runs from the 488 release through
  Release 489 (`0b9d7403b`), the SDK bump (`1aa3c3824`) and the spec bump
  (`d967d1358`). Finney moved from 488 to 490.
- Knob values: `NetworkLockReductionInterval` is **28800** (4 days,
  explicit; 57600 at the previous read, changed by root with no runtime
  upgrade). Every other value is unchanged: `EmissionBarRank` unset
  (default 32), `EmissionBarQuantile` 0.75 explicit and inert,
  `EmissionGateExponent` unset (default 3), `BasketConcentrationCap` 7865,
  `BasketTradingEnabled` true, `MaturityRate` 311622 (explicit),
  `UnlockRate` unset, `PendingChildKeyCooldown` 7200, `StakeThreshold`
  1000 TAO, `CKBurn` 0, `NetworkImmunityPeriod` 432000, `NetworkRateLimit`
  14400 (all explicit); `MaxChildkeyTake`, `MinChildkeyTake`,
  `TxChildkeyTakeRateLimit`, `CommitRevealWeightsVersion` and the three
  claim dust floors unset.
- `SubnetEmissionEnabled`: 128 keys for 128 subnets, **only 82 off**.
- Spec 490 shipped (from Release 489; the 490 commit only bumps the
  version):
  - Gamma shares of emission: `sudo_set_subnet_emission_weights_v2`
    (AdminUtils 120, owner or root, rules and rate limit of call 114;
    proxy filter group `SubnetManagementCalls`) sets the five slots plus up to 16 gamma
    shares of at most 10% each to root-whitelisted targets
    (`sudo_set_subnet_gamma_emission_whitelisted`, AdminUtils 121, root
    only). Shares accrue per block (`PendingGammaEmission`), convert at
    the paying subnet's epoch within 2% price bounds on both pools, and
    credit the owner's gamma deposit on the target. A leased subnet has no
    shares. Removal or dissolution returns a share to the miner slot.
    New items `SubnetGammaEmission`, `PendingGammaEmission`,
    `UnconvertedGammaEmission`, `SubnetGammaEmissionWhitelisted`.
  - Gamma deposits can open at an unassociated hotkey; an associated one
    still admits only its owning coldkey.
  - Root dividend deposits: the all-pools-in-band gate is replaced by a
    price-impact budget (out-of-band holdings at most 10 bps of NAV;
    incoming credits and mint ratio at most 200 bps, against fast-price
    rebased quotes); shares still mint at live realizable prices. Queues
    over 256 credits settle dust in bounded chunks.
  - `terminate_lease`: final dividends crystallize to contributors and pay
    below the transfer minimum; ownership is taken once (marker
    `SubnetLeaseTerminationHotkey`), never again on retry; the residual
    stake and lock move to the beneficiary once contributors are paid.
  - `LegacyAlphaCompatibility` is off in the runtime: stake accounting,
    claim budgets, coldkey swaps and EVM views read only `AlphaV2` /
    `TotalHotkeySharesV2`.
  - EVM staking precompile coldkey totals meter gas per scanned step.
  - Weights for the two new admin calls alias existing ones
    (`sudo_set_subnet_emission_weights`, `sudo_set_gamma_enabled`); not a
    benchmarked weight.
- Not read, so not stated as live: `SubnetGammaEmission`,
  `SubnetGammaEmissionWhitelisted`, lease storage.

Verified 2026-11-07 against Finney RPC by the runtime upgrade job. The
knob values above supersede this read; its mechanics are still live at
490 except where the 490 section above replaces them:

- Spec **488**. Knobs and the emission-switch map read together at
  finalized block 9451247
  (`0xdc850c0891b133858c4f69ce1fa875f81b9ed36e61faca46315f7f4fa1d8af2f`).
  Chain-read probe clean at the same finalized block 9451247 (no failures:
  every item Atlas reads keeps its name, shape and default). Source: the
  subtensor `v488` tag (`b6a81d144078`, `runtime/src/lib.rs`
  `spec_version: 488`); `spec-488.diff` runs from the 486 release through
  Release 487 (`8b2a978a9`) and Release 488 (`b6a81d144`). Finney moved
  from 486 to 488.
- Knob values, all unchanged from the previous read: `EmissionBarRank`
  unset (default 32), `EmissionBarQuantile` 0.75 explicit and inert,
  `EmissionGateExponent` unset (default 3), `BasketConcentrationCap` 7865,
  `BasketTradingEnabled` true, `MaturityRate` 311622 (explicit),
  `UnlockRate` unset, `PendingChildKeyCooldown` 7200, `StakeThreshold`
  1000 TAO, `CKBurn` 0, `NetworkImmunityPeriod` 432000,
  `NetworkLockReductionInterval` 57600, `NetworkRateLimit` 14400 (all
  explicit); `MaxChildkeyTake`, `MinChildkeyTake`,
  `TxChildkeyTakeRateLimit`, `CommitRevealWeightsVersion` and the three
  claim dust floors unset.
- `SubnetEmissionEnabled`: 128 keys for 128 subnets, **only 82 off**.
  SN103, off at the 2026-10-27 read, is on.
- Spec 488 shipped (from the 487 and 488 releases):
  - Emission vector burn and recycle slots are enabled: together at most
    33% (`BurnRecycleEmissionAboveMaximum`; the old must-be-zero errors
    stay only as deprecated indices). Burn destroys alpha, recycle lowers
    `SubnetAlphaOut`. Neither enters `MinerBurned` or the emission share.
  - Gamma: dollar-valued subnet service credit minted by burning alpha
    (`mint_gamma` 158, `mint_gamma_with_stake` 159, `move_gamma` 160,
    `close_gamma_deposit` 161, spender 162, daily cap 163, `spend_gamma`
    164), priced at min(spot, `SubnetGammaPrice`) and a root-set TAO/USD
    oracle (`feed_tao_usd_price` 157; AdminUtils 116). Gated by
    `GammaEnabled` (AdminUtils 118) and `SubnetGammaEnabled` (117), both
    default off and not read. Coldkey swaps move deposits (128 cap across
    both keys); dissolution deletes them. `set_service` (165) publishes a
    hotkey's service URL and spender (`Services`).
  - Hashed and post-quantum wallet accounts (`HashedAccounts`, pallet
    index 33: ML-DSA-65, Falcon-512/1024, rotating hashed SR/ED), behind
    `HashedAccountsEnabled` (AdminUtils 115, default off, not read);
    registration reserve root-set (AdminUtils 119, default 0.2 TAO).
    Hotkey ownership changes and coldkey swaps refuse to weaken a
    protected account (`HotkeyOwnerPolicyViolation`). Utility
    `as_protected_derivative` (8) and `as_safe_derivative` (9); multisig
    indices 5 to 9 for off-curve composite accounts; account-approved
    limit orders.
  - Proxy types `Lock` (21) and `GammaSpend` (22). `Staking` also admits
    the two root-claim calls; `NonTransfer` and `NonCritical` lose basket
    trading and gamma calls.
  - Root dividend deposits (admission gate replaced at 490, see above):
    dust judged on the fast price; unsettled credits snapshot per root
    stake (`DeferredBasketRates` and related items), convert later or are
    redeemed directly; dissolution sells them into a reserve outside NAV.
    Share mint priced at `N + fund_yield`. Calls that would change the
    claimant base fail with `BasketDepositPending` until settled or
    snapshotted.
  - `SubnetMovingPrice` updates every block for every started dynamic
    subnet, not only the emission set; before `start_call` only the fast
    price moves.
  - Fee schedules for stake calls keep their pre-487 weights by owner
    decision (settlement work runs but is not charged). Not a chain
    mechanic the corpus states.
- Not read, so not stated as live: `GammaEnabled`, `SubnetGammaEnabled`,
  `TaoUsdPriceOracle`, `HashedAccountsEnabled`,
  `HashedAccountRegistrationDeposit`, `SubnetEmissionWeights`.

Verified 2026-11-05 against Finney RPC, workstation reads (audit WP13):

- Per-subnet hyperparameters for all 128 subnets at finalized block
  9434494 (`0x0f641a845c312690e6deb171aefa657a72fb23249692a84a87c1fadc7481036b`):
  `Tempo` 360 on 124 subnets, SN1 99, SN18 1800, SN19 7200, SN38 1440.
  `ImmunityPeriod` set on all 128, 5000 on 68, range 0 to 65535.
  `CommitRevealWeightsEnabled` true on 44, false on 35, unset (default
  true) on 49. `Yuma3On` true on 32, false on 1, unset (default false) on
  95. `LiquidAlphaOn` true on 8. `BondsMovingAverage` unset on 109.
- Plain values at finalized block 9434521
  (`0xacf84f86e78af06dbb9f1589fc9b3db44b3932639c994c21ba967d89f3ab0063`):
  `MaturityRate` 311622 (explicit; code default 934866), `UnlockRate`
  unset, `PendingChildKeyCooldown` 7200, `StakeThreshold` 1000 TAO, `CKBurn`
  0, `MaxChildkeyTake`, `MinChildkeyTake`, `TxChildkeyTakeRateLimit` and
  `CommitRevealWeightsVersion` unset.
- Mechanics added or corrected from the subtensor `v486` tag (commit
  `72323e132`): per-subnet tempo and the `LastEpochBlock` scheduler; UID
  immunity and pruning; commit-reveal, bonds, Yuma 3 and liquid alpha;
  childkeys and take; per-subnet alpha halving; subnet lock and UID
  registration TAO destination; emit-to set normalization; conviction
  rates as time constants. dTAO first block 4920351 (docs) at 2025-02-13
  21:41:24 UTC, from that block's `timestamp.set` inherent (block hash
  `0x31a7917b1773378fa5706dc24e244efe4212be186441497c8a3f031f374a9efd`).


Verified 2026-10-27 against Finney RPC (`https://entrypoint-finney.opentensor.ai`).
The knob values above supersede this read; the mechanics below are still
live at 490 (the 488 and 490 diffs leave them as stated unless noted above):

- Spec **486**. Knobs, emission-switch map, dust-floor storage and the
  subnet registration rules read together at finalized block 9369802
  (`0xa4f5e96389b63715f7592f1b85288939243033fdcf065f804936a834b6fefab7`).
  Chain-read probe clean at finalized block 9369804
  (`0xc9f7450d8a565cbc98639aee738e9452812470cdeeaa59cfffb4831e9951a4a9`).
  Tracked clone `72323e132` (`runtime/src/lib.rs` `spec_version: 486`).
  `spec-486.diff` has base `spec_version: 482`, so it repeats the 483 and
  484 changes. Against `spec-484.diff`, every pallet, runtime, precompile
  and `common/` blob is identical except `runtime/src/lib.rs` (the version
  bump) and `chain-extensions/src/lib.rs`.
- Spec 486 shipped (Finney moved from 484):
  - The contracts chain extension's stake-availability query
    (`GetStakeAvailabilityV1`) now charges weight before it runs: one read,
    then the `StakingHotkeys` walk for the coldkey's actual list length
    plus one entry. The walk is not clamped at the 256-entry cap. It
    charged nothing before. Returned values are unchanged.
  - No storage item Atlas reads was added, removed, renamed or reshaped;
    the probe is clean. All knob values match the 484 read.
  - The rest of the 486-only diff is CI scripts (deployed-runtime
    publishing) and test files. It changes no chain mechanic.
- Carried from spec 484 and still live:
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
  - `SubnetState` is not read.
- Carried from spec 483 and still live (the 486 diff carries the same
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
    reverted at 486. The live
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
  - Resolved outside the corpus: `livedata/atlas_live.py`
    `SUBNET_PARAM_DEFAULTS` now records an absent `SubnetEmissionEnabled`
    key as `true`, matching the runtime's `DefaultTrue` (unchanged at
    490). Every live subnet has an explicit key (128 of 128).
- Carried from spec 482 and still live (not touched by the 483, 484 or
  486 diffs):
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
    `sudo_set_subnet_emission_weights` (call 114): burn plus recycle at
    most 33% (since 488; was 0), owner at most 33% (lease-created subnets at least 18%), validator at
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
    cap. Since spec 486 the chain extension's stake-availability query
    also charges for the walk.
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
- `SubnetEmissionEnabled` is live. 128 keys for 128 subnets at finalized
  block 9478248; **only 82 off** (103 on); SN1 on.
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
  stake shares live in `AlphaV2` / `TotalHotkeySharesV2`, the only items
  the runtime reads since 490.
- Subnet registration rules at finalized block 9478248:
  `NetworkImmunityPeriod` **432,000** (60 days),
  `NetworkLockReductionInterval` **28,800** (4 days), `NetworkRateLimit`
  **14,400** (2 days), all explicit. Root set the first two on 2026-10-14
  with no runtime upgrade (the subtensor announcement gives the old values
  as 120 and 16 days), then lowered the lock reduction interval again from
  8 days, also with no runtime upgrade, between the 2026-11-07 and
  2026-11-11 reads. `NetworkMinLockCost` (1 TAO) and
  `NetworkLastLockCost` (884.38 TAO) are not in the knob read; those values
  are from a one-off read at finalized block 9,278,789 on 2026-10-14.
- Claim dust floors are unset on chain at finalized block 9478248. Code
  defaults apply: row floor min(1 TAO, 10 bps of anchored NAV); slice
  floor 0.0001 TAO. Cash-first claims are not live.

[../supersession-markers.json](../supersession-markers.json) is empty,
reviewed at the spec 490 re-sync: every claim the 490 diff or the new
knob read made stale (five emission slots summing to one alone, root
dividend deposits waiting on every pool inside the 2% band, gamma
deposits only at an associated hotkey, the 8-day lock reduction
interval) was rewritten in place. Add a marker if a
corpus claim goes stale before the next re-sync.

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

This directory is the only corpus source. Nothing is synced from the
closed IntoOps copy (ATLAS-KB-007 closed as not-applicable).
