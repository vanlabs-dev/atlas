---
spec_version: 497
subtensor_tag: "v497"
subtensor_commit: "24e1fc7b12ea7ce9d390925dac602ba961997824"
newest_tag: "v497"
newest_tag_live: true
last_updated: "2026-11-26T23:46:20Z"
content_changed: "2026-11-26T23:46:20Z"
pending_on_main: []
---

# Bittensor chain grounding

Machine-checked facts about how the Bittensor chain (subtensor) works on
mainnet now. Atlas regenerates this file from `grounding/claims.yaml`.
Every claim cites source lines at a release tag. A model drafted each
claim; a second model, shown only the claim and the cited lines, agreed
with it, and code checked that every number in it appears in those lines.

- Live means mainnet runs that spec (`state_getRuntimeVersion`). Code on
  `main` that mainnet does not run yet is listed in `pending_on_main`.
- Fresh means `last_updated` is under 7 days old and `spec_version` is
  not behind the newest `v*` tag. A newer tag with `newest_tag_live:
  false` is a release mainnet has not enacted yet; facts here are still
  the live ones.
- `UNVERIFIED (pending review)` marks a claim whose last check failed. Its
  last verified text is kept; do not rely on it.
- `live at snapshot` values are read from the chain when the spec went
  live (`snapshots/<spec>/`), not from code.
- Refs: `[tag path:lines]`. `st/` is `pallets/subtensor/src/`, `au/` is
  `pallets/admin-utils/src/`, `sw/` is `pallets/swap/src/`.

## 1. Emission

- `get_shares` starts from `get_shares_price_ema`, which divides each subnet's EMA price `get_moving_alpha_price` (not spot) by their sum, then applies the miner-burn reweight and the gate; it never calls `get_shares_flow`. [v497 st/coinbase/subnet_emissions.rs:255-361,511-538]
- `apply_emission_gate` multiplies each share by 1 / (1 + (theta/s)^h), where h is `EmissionGateExponent` (default 3), then renormalizes; a zero `EmissionGateBar` turns the gate off. [v497 st/coinbase/subnet_emissions.rs:459-509; st/lib.rs:2504-2519]
- `EmissionGateBar` is recomputed every `EMISSION_BAR_UPDATE_INTERVAL` (360) blocks or while zero; with `EmissionBarRank` 32 (default) it is the 32nd-largest positive share, with 0 the `EmissionBarQuantile` (0.61) crossing. [v497 st/coinbase/subnet_emissions.rs:396-457; st/lib.rs:2476-2502]
- `get_subnets_to_emit_to` admits only non-root subnets that have `FirstEmissionBlockNumber` set, have `SubtokenEnabled` true and pass `get_network_registration_allowed`. [v497 st/coinbase/subnet_emissions.rs:21-32]
- Before the gate, each price share is multiplied by (1 - `MinerBurned`) and renormalized; if every weight comes out zero, the unscaled price shares are used. [v497 st/coinbase/subnet_emissions.rs:350-394]
- At each epoch `MinerBurned` is set to the fraction of miner incentive that went to owner-owned hotkeys; that incentive is recycled or burned per `RecycleOrBurn`, and burned when it is unset. [v497 st/coinbase/run_coinbase.rs:817-892]
- `get_subnet_terms` sets `alpha_in` to the TAO share divided by spot `current_alpha_price`, capped at `root_proportion` times the alpha emission; the TAO the cap leaves over becomes `excess_tao`. [v497 st/coinbase/run_coinbase.rs:241-287; st/coinbase/block_step.rs:81-97]
- `inject_and_maybe_swap` spends `excess_tao` on a chain buy via `swap_tao_for_alpha` (its TAO enters the pool, bought alpha goes to `SubnetProtocolAlpha`); `tao_in` and `alpha_in` reach reserves only as the price-active part from `adjust_protocol_liquidity`. [v497 st/coinbase/run_coinbase.rs:94-142,143-192,193-231]
- **UNVERIFIED (pending review)** (after one citation retry: critic: The cited lines show disabled subnets getting a zero, renormalised share while staying in the map, and alpha_out being comp...). never verified, proposed: A subnet with `SubnetEmissionEnabled` false gets a zero TAO share (redistributed to enabled subnets) but stays in the map, so `emit_to_subnets` still mints its `alpha_out` from `get_block_emission_for_issuance`. [v497 st/coinbase/subnet_emissions.rs:34-76]
- A subnet's `alpha_out` comes from `get_block_emission_for_issuance` on its own alpha issuance, not from its TAO share, and is split by the vector `[burn, recycle, owner, validator, miner]`. [v497 st/coinbase/run_coinbase.rs:248-263,313-342]
- `init_new_network` seeds the canonical `default_emission_weights` `[0, 0, owner, validator, miner]`: owner is `InitialSubnetOwnerCut`, validator half the remainder, miner the rest. [v497 st/subnets/subnet.rs:542-556; st/subnets/emission_weights.rs:236-263,411-419]

## 2. Yuma consensus, weights, bonds and dividends

- In the sparse epoch, without `Yuma3On` bonds use `compute_ema_bonds_normal_sparse` with fixed alpha = 1 − `get_bonds_moving_average`/1_000_000, ignoring `LiquidAlphaOn`; liquid alpha runs only via `compute_bonds_sparse` under Yuma3. [v497 st/epoch/run_epoch.rs:1043-1134,1477-1495,1586-1613]
- Each block `run_coinbase` calls `emit_to_subnets`, which splits each subnet's `alpha_out` by `get_subnet_emission_weights` `[burn, recycle, owner, validator, miner]`; owner accrues to `PendingOwnerCut`, miner to `PendingServerEmission`. [v497 st/coinbase/run_coinbase.rs:24-67,289-381]
- `default_emission_weights` is `[0, 0, owner, validator, miner]`: owner is `InitialSubnetOwnerCut` (`SubtensorInitialSubnetOwnerCut` = 11_796 of `u16::MAX`) scaled, validator half the remainder, miner the rest. [v497 st/subnets/emission_weights.rs:229-263; runtime/src/lib.rs:1057-1138]
- Root is paid off the top of the validator slot: `alpha_out` × `get_root_emission_share` (baseline at default validator share and global `TaoWeight`, capped at the slot); without `root_sell_flag` it is recycled. [v497 st/coinbase/run_coinbase.rs:364-406; st/subnets/emission_weights.rs:369-392]
- Consensus is the `active_stake`-weighted column median of weights at `get_float_kappa` (`get_kappa`/`u16::MAX`); weights are clipped to it and incentive is normalized clipped weights × `active_stake`. [v497 st/epoch/run_epoch.rs:999-1027,1319-1322; st/utils/misc.rs:609-611]
- Owner vectors are bounded: `MAX_OWNER_EMISSION` and `MAX_BURN_RECYCLE_EMISSION` are `emission_fraction(33, 100)`, `MAX_VALIDATOR_EMISSION` (50, 100), `MIN_MINER_EMISSION` (33, 100). [v497 st/subnets/emission_weights.rs:70-79]
- With commit-reveal on, weights to a UID registered after the validator's earliest unexpired commit (`WeightCommits` or `TimelockedWeightCommits`) are masked; self-weights are masked except the owner UID. [v497 st/epoch/run_epoch.rs:865-922]

## 3. dTAO pools, swaps, fees, slippage

- On dynamic subnets (mechanism 1) `current_price` is `calculate_price` = (w1/w2)*(y/x), x = alpha reserve, y = TAO reserve, quote weight w2 stored in `SwapBalancer`; it returns 0 if the alpha reserve is zero, other mechanisms 1. [v497 sw/pallet/impls.rs:22-36; sw/pallet/balancer.rs:220-228,1-12]
- Swap `price_limit` is RAO per alpha, divided by 1_000_000_000 into a price; if the current price is already past the limit the swap fails `PriceLimitExceeded`, otherwise it fills only up to the limit and recomputes the fee. [v497 sw/pallet/impls.rs:460-478,319-340; sw/pallet/swap_step.rs:88-124]
- `FeeRate` defaults to 33 parts of `u16::MAX`, taken from the input before the swap; `drop_fees` makes it zero and non-dynamic mechanisms pay none. [v497 sw/pallet/impls.rs:368-387; sw/pallet/mod.rs:89-97; sw/pallet/swap_step.rs:49-57]
- All swap fees go to the block author (`fee_to_block_author`); alpha fees are swapped fee-free for TAO in `settle_alpha_fee_to_author`, and burned if no author is known. [v497 sw/pallet/swap_step.rs:126-151; st/staking/stake_utils.rs:1135-1162]
- Net input above `MAX_SWAP_INPUT_RESERVE_MULTIPLIER` (1_000) times the input reserve fails `SwapInputTooLarge`; an output reserve below `MinimumReserve` (`SwapMinimumReserve` 1_000_000) fails `ReservesTooLow`. [v497 sw/pallet/swap_step.rs:10-10; sw/pallet/impls.rs:302-332; runtime/src/lib.rs:1170-1185]
- User liquidity is permanently disabled: `add_liquidity`, `remove_liquidity`, `modify_position`, `toggle_user_liquidity` and `disable_lp` all return `Deprecated`. [v497 sw/pallet/mod.rs:213-270]
- On a buy only the TAO that enters the reserve is added to `SubnetTAO` and `TotalStake`; the swap fee leaves the subnet account for the block author and is not counted. [v497 st/staking/stake_utils.rs:1021-1031]
- `set_fee_rate` is root-only and capped by `MaxFeeRate`, which the runtime sets to `SwapMaxFeeRate` 10000. [v497 sw/pallet/mod.rs:189-211; runtime/src/lib.rs:1170-1185]
- `SubnetFastMovingPrice` is an unclamped spot EMA with half-life `BASKET_FAST_EMA_HALF_LIFE_BLOCKS` 600, updated even before start_call; it anchors `swap_basket` price bounds. [v497 st/staking/stake_utils.rs:53-121; st/lib.rs:266-266]

## 4. Staking

- `do_set_perpetual_lock` stores `DecayingLock` = false, which `is_perpetual_lock` reads, so that lock's mass stops decaying while conviction still matures; a lock on the `SubnetOwnerHotkey` has conviction equal to its locked mass. [v497 st/staking/lock.rs:526-637,84-196,320-435]
- `lock_stake` locks alpha per coldkey per subnet to one hotkey; the lock is subnet-wide, so `validate_remove_stake` rejects unstaking more than total minus locked minus miner collateral with `StakeUnavailable`. [v497 st/macros/dispatches.rs:2891-2912; st/staking/lock.rs:693-754; st/staking/stake_utils.rs:1910-1964]
- Non-perpetual locked mass decays by `exp_decay` = exp(-dt/`UnlockRate`) and conviction matures from it with timescale `MaturityRate`; both default to 934_866 blocks (code comment: 50% in ~90 days). [v497 st/lib.rs:2399-2417; st/staking/lock.rs:300-419,913-947]
- Stake weight per hotkey is inherited alpha plus inherited root TAO times `get_tao_weight` (`TaoWeight` / u64::MAX); default `SubtensorInitialTaoWeight` is 971_718_665_099_567_868 (~5.27%). [v497 st/staking/stake_utils.rs:226-287; st/subnets/emission_weights.rs:96-98; runtime/src/lib.rs:1068-1068]
- In `get_parent_child_dividends_distribution`, the childkey take and the `get_ck_burn` share come only out of parents whose owning coldkey differs from the child's; same-coldkey parents pay neither. [v497 st/coinbase/run_coinbase.rs:1142-1243]
- Leaving root requires `RootStakeUnlockInterval` blocks since the pair's last root add/remove/claim (`LastColdkeyHotkeyStakeBlock`), else `RootStakeLocked`; the default 0 disables the hold. [v497 st/lib.rs:3471-3493; st/staking/stake_utils.rs:1097-1111]
- A top-up to an existing lock must target the same hotkey (`LockHotkeyMismatch`) and stay within total stake (`InsufficientStakeForLock`); `do_move_lock` zeroes conviction unless both hotkeys share an owning coldkey. [v497 st/staking/lock.rs:745-785,1675-1734]
- After `ONE_YEAR` from registration, `change_subnet_owner_if_needed` makes the top-conviction hotkey the subnet owner if its own conviction exceeds 18% of `SubnetAlphaOut` minus `SubnetProtocolAlpha` minus burned alpha. [v497 st/staking/lock.rs:14-14,1094-1183]

## 5. Registration, immunity and pruning

- Subnet lock cost from `get_network_lock_cost` is `last_lock * mult - (last_lock / lock_reduction_interval) * (current_block - last_lock_block)`, where `mult` is 2 (1 if `last_lock_block == 0`), floored at `min_lock`. [v497 st/coinbase/root.rs:288-328]
- A dissolved subnet refunds its owner only if `NetworkRegisteredAt` < `NetworkRegistrationStartBlock`: the `refund` starts as lock minus owner alpha at `current_alpha_price`, the alpha being `SubnetOwnerCutAccrued`, or `legacy_owner_cut_accrued` if no entry exists, before it is adjusted and transferred to the owner. [v497 st/staking/remove_stake.rs:610-704; st/subnets/emission_weights.rs:421-446]
- **UNVERIFIED (pending review)** (after one citation retry: critic: When `half_life` is 0 or block ≤ 1 only the multiplication is skipped: `decayed_registration_price` with `factor = None` st...). never verified, proposed: Each block (skipped if `half_life` is 0 or block ≤ 1) the burn is multiplied by a Q32 factor `f`, found by binary search as the value whose power `BurnHalfLife` is at most 0.5, and clamped to the subnet's min and max burn; `execute_registration` then multiplies it by `BurnIncreaseMult` (at least 1) and clamps it to the same bounds again. [v497 st/subnets/registration.rs:815-850,909-918]
- Of the burn price, the `(1 - p)` share is burned and `p` (`get_collateral_requirement_tao`) is locked to the hotkey as miner collateral; a returning hotkey pays only the shortfall, valued at `get_moving_alpha_price`. [v497 st/subnets/registration.rs:352-389; st/subnets/collateral.rs:208-247]
- `get_neuron_to_prune` replaces the uid with the lowest `Emission`, then the oldest registration, then the lowest uid; it picks an immune uid only when non-immune uids number at most `get_min_non_immune_uids`. [v497 st/subnets/registration.rs:592-671]
- A neuron is immune while `current_block - registered_at < ImmunityPeriod`, which is set per subnet. [v497 st/utils/misc.rs:568-582]
- `get_neuron_to_prune` skips `get_immune_owner_hotkeys`: up to `ImmuneOwnerUidsLimit` owner-coldkey uids on the subnet, earliest `BlockAtRegistration` first, `SubnetOwnerHotkey` inserted first; `get_neuron_to_prune` never returns these, even when it falls back to an immune uid. [v497 st/subnets/registration.rs:534-589,591-671]
- `get_lock_reduction_interval` multiplies `NetworkLockReductionInterval` by block emission / 1_000_000_000, so each emission halving halves the lock-cost decay window. [v497 st/coinbase/root.rs:366-383]
- `do_pow_register` needs a seal bound to netuid, block hash, hotkey and coldkey, from a block at most `POW_MAX_WORK_AGE_BLOCKS` (5) old; it bumps only `Difficulty` by `BurnIncreaseMult`, not the burn. [v497 st/subnets/registration.rs:86-168,194-225,920-933]

## 6. Key hyperparameter defaults

- `Tempo` defaults to `DefaultTempo` = `InitialTempo` = `SubtensorInitialTempo` = `INITIAL_SUBNET_TEMPO`, which is `prod_or_fast!(360, 10)`, so 360 blocks on mainnet. (live at snapshot: 360 on 125 of 129 subnets) [v497 runtime/src/lib.rs:996-1101; st/lib.rs:1292-1296,2658-2661]
- `CommitRevealWeightsEnabled` defaults to true on every subnet. (live at snapshot: true on 92 of 129 subnets) [v497 st/lib.rs:1524-1528,2990-2994]
- `WeightsSetRateLimit` defaults to 100 blocks per subnet; the value is hardcoded in the pallet, not set in runtime config. (live at snapshot: 100 on 123 of 129 subnets) [v497 st/lib.rs:1300-1302,2961-2964]
- `ImmunityPeriod` defaults to 4096 blocks per subnet. (live at snapshot: 5000 on 69 of 129 subnets) [v497 runtime/src/lib.rs:1020-1106; st/lib.rs:1352-1356,2905-2908]
- `MaxAllowedUids` defaults to 256 per subnet. (live at snapshot: 256 on 116 of 129 subnets) [v497 runtime/src/lib.rs:1008-1092; st/lib.rs:1340-1344,2900-2903]
- `MaxAllowedValidators` defaults to 128 per subnet. (live at snapshot: 64 on 121 of 129 subnets) [v497 runtime/src/lib.rs:1014-1110; st/lib.rs:1375-1379,2936-2939]
- `MaxDelegateTake` defaults to 11_796 (18%) and `MinDelegateTake` defaults to 0. (live at snapshot: 11796 (unset, default)) [v497 runtime/src/lib.rs:1027-1113; st/lib.rs:1005-1021,1806-1812]
- `MinBurn` defaults to 500_000 RAO, `Burn` starts at 100_000_000 and `MaxBurn` defaults to 100_000_000_000. (live at snapshot: 500000 on 68 of 129 subnets) [v497 runtime/src/lib.rs:1036-1121; st/lib.rs:1118-1134,2996-3012]
- `Kappa` defaults to 32_767 (0.5 of 65535) per subnet. (live at snapshot: 32767 on all 129 subnets) [v497 runtime/src/lib.rs:1007-1090; st/lib.rs:1328-1332,2876-2878]
- `LiquidAlphaOn` defaults to false; when it is enabled, `AlphaValues` default to (45875, 58982). (live at snapshot: false on 122 of 129 subnets) [v497 st/lib.rs:1536-1552,3068-3081]
- `NetworkRateLimit` (blocks between subnet registrations) defaults to 7200, or 0 in `pow-faucet` builds. (live at snapshot: 10800) [v497 runtime/src/lib.rs:1059-1139; st/lib.rs:1232-1239,2623-2625]
- `MinAllowedWeights` defaults to 1024 per subnet. (live at snapshot: 1 on all 129 subnets) [v497 runtime/src/lib.rs:1010-1097; st/lib.rs:1370-1374,2931-2934]

## 7. Coldkey swap and other safety delays

- `announce_coldkey_swap` and `announce_coldkey_swap_v2` set the swap's `when` to now plus `ColdkeySwapAnnouncementDelay`; `swap_coldkey_announced` before `when` fails `ColdkeySwapTooEarly`. [v497 st/macros/dispatches.rs:2453-2539,2559-2600]
- **UNVERIFIED (pending review)** (critic: The exception list leaves out the proxy pallet's `remove_announcement`, which `check` always allows, including while disputed, so the stated set of a...). never verified, proposed: While an announcement is pending, `CheckColdkeySwap` fails the coldkey's calls with `ColdkeySwapAnnounced`, except the announce, swap, dispute, clear and reservation-release calls and `submit_encrypted`; once disputed, nearly all fail `ColdkeySwapDisputed`. [v497 st/guards/check_coldkey_swap.rs:41-82]
- `clear_coldkey_swap_announcement` works only after when + `ColdkeySwapReannouncementDelay` (else `ColdkeySwapClearTooEarly`), so a victim cannot cancel a fresh malicious announcement; they must dispute. [v497 st/macros/dispatches.rs:2803-2830]
- **UNVERIFIED (pending review)** (critic: The all-subnet path checks every subnet where the hotkey is a member or has child keys (`IsNetworkMember || !ChildKeys.is_empty()`), which is not the...). last verified 2026-11-26: A coldkey can swap a hotkey on one subnet only once per `HotkeySwapOnSubnetInterval` (mainnet `24 * 60 * 60 / 12` blocks), tracked in `LastHotkeySwapOnNetuid`; otherwise the call fails `HotKeySwapOnSubnetIntervalNotPassed`. [v497 st/swap/swap_hotkey.rs:769-784; runtime/src/lib.rs:1073-1073]

## 8. Deprecated / common traps

- `set_root_weights` no longer applies (`RootWeightSettingDisabled` is kept only for index stability); now `Weights[ROOT]` is cleared, `RootWeightSettingEnabled` is killed, and basket composition changes only through `swap_basket`. (stopped applying at spec 461, live from spec 464 (2026-09-17)) [v497 st/macros/errors.rs:360-374; st/migrations/migrate_remove_root_weights.rs:26-64]
- `SubnetOwnerCut` and `OwnerCutEnabled` no longer set the owner's emission, and their setters return `Error::Deprecated`; now the owner share is slot 2 of the per-subnet `SubnetEmissionWeights` vector, and zero disables it. (stopped applying at spec 480, live from spec 481 (2026-10-19)) [v497 st/lib.rs:2577-2610; au/lib.rs:1233-1243,2587-2599]
- User liquidity positions no longer apply: `add_liquidity`, `remove_liquidity`, `modify_position`, `toggle_user_liquidity` and `disable_lp` always return `Deprecated`, and user liquidity is permanently disabled. (stopped applying at spec 423) [v497 sw/pallet/mod.rs:213-270]
- SubtensorModule `set_tempo` (call 139) no longer changes tempo: it charges a fee and returns success without changing state; now use `AdminUtils::sudo_set_tempo`. (stopped applying at spec 431, live from spec 432 (2026-07-16)) [v497 st/macros/dispatches.rs:2953-2965]
- `swap_hotkey` (call 70) is deprecated; now use `swap_hotkey_v2` (call 72), whose `keep_stake` flag can leave the stake on the old hotkey. (stopped applying at spec 391) [v497 st/macros/dispatches.rs:885-929]
- The `BlockEmission` storage item is deprecated; now `calculate_block_emission()` derives each block's emission from total issuance. (stopped applying at spec 428, live from spec 432 (2026-07-16)) [v497 st/lib.rs:2046-2050; st/coinbase/block_emission.rs:31-45]
- TAO-flow emission shares (`get_shares_flow`) no longer apply; now `get_subnet_block_emissions` takes shares from `get_shares`, which uses `get_shares_price_ema`, scales by `(1 - MinerBurned)` and applies the emission gate. (stopped applying at spec 421) [spec-419 st/coinbase/subnet_emissions.rs:332-336; v497 st/coinbase/subnet_emissions.rs:34-40,350-394]

## 9. Changelog of live spec bumps

- spec 497 live 2026-11-26 (from 495): 3 PRs: #3367 #3362 #3361
- spec 495 live 2026-11-24 (from 494): 2 PRs: #3358 #3359
- spec 494 live 2026-11-23 (from 493): 2 PRs: #3352 #3351
- spec 493 live 2026-11-20 (from 492): 7 PRs: #3345 #3350 #3349 #3343 #3337 #3340 (+1 more)
- spec 492 live 2026-11-19 (from 491): no PR merges
- spec 491 live 2026-11-16 (from 490): no PR merges
- spec 490 live 2026-11-10 (from 488): 1 PR: #3324
- spec 488 live 2026-11-05 (from 486): 1 PR: #3291
- spec 486 live 2026-10-26 (from 484): 2 PRs: #3289 #3282
- spec 484 live 2026-10-23 (from 483): 8 PRs: #3279 #3281 #3101 #3277 #3253 #3276 (+2 more)
