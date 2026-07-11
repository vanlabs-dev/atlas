# Bittensor Ground Truth

Verified facts. Every article MUST be consistent with these. If unsure about a mechanic, state what you know and flag the uncertainty. Do NOT guess.

## Emissions and Tokens

- Emissions happen in two stages (per the official docs).
  - Stage 1, every block (~12s): the protocol injects BOTH TAO and alpha into the subnet's AMM pool. The TAO amount is sized by the subnet's price-based emission share (root_prop x EMA price x (1 - miner_burn), the model active since June 2026); alpha is injected to keep the pool price stable, with the alpha injection capped by the subnet's root proportion (excess TAO routes to chain buys, see the emission section).
  - Stage 2, end of each tempo (360 blocks, ~72 minutes): the alpha accumulated over the tempo is distributed to participants through Yuma Consensus.
- The distribution split is FIXED by the protocol: 18% to the subnet owner, 41% to miners, 41% to validators and their stakers. It is NOT subnet-configurable. What an individual staker nets out varies with the validator's take (default 18%), not with this split.
- Participants on a subnet receive alpha; the injected TAO backs the pool reserve. Stakers can keep alpha or swap it to TAO. Do not describe emissions as a single token: both TAO and alpha are injected.
- TAO is the root network token. Alpha tokens are subnet-specific tokens.
- When you stake TAO on a subnet, it is converted to alpha via the subnet's AMM (automated market maker) liquidity pool: the TAO enters the pool's TAO reserve and the pool returns the equivalent alpha at the current rate.
- The alpha price (in TAO) is determined by the AMM pool ratio, not set manually.

## Subnets

- The network is capped at 128 occupied subnet slots (the subnet limit). Netuid 0 is the root subnet (Subnet Zero): a special subnet, and the only one without its own alpha token.
- Subnet deregistration is automatic (live since September 2025). When a new subnet registers and all 128 slots are full, the protocol deregisters the subnet with the LOWEST EMA price among non-immune subnets (ties broken by earliest registration). This happens at most once every ~2 days (14,400 blocks).
- New subnets have a network immunity period (currently 4 months from registration) during which they cannot be deregistered.
- When a subnet is deregistered, its AMM pools are dissolved: all alpha is converted to TAO and returned proportionally to alpha holders. The freed netuid can be taken by a new registration, so a netuid can change hands.
- Each subnet has a tempo: a 360-block period (~72 minutes at 12s/block) over which Yuma Consensus calculates emissions.
- Creating a subnet costs a dynamic "burn cost" in TAO (it roughly doubles after each new subnet and decays over time). This TAO is recycled, not destroyed.

## Miners and Validators

- Miners produce work (inference, training, data, compute, etc. depending on the subnet).
- Validators evaluate miner output and set weights that determine emission distribution.
- Validators stake on subnets to participate. Their stake-weighted votes determine miner rewards.
- Anyone can register a hotkey on a subnet to mine. Validating is permissioned by stake: only the top 64 hotkeys by stake/emissions (subject to a minimum stake) receive validator permits by default.

## dTAO and the Emission Model

- Dynamic TAO (dTAO) gave each subnet its own alpha token and AMM liquidity pool. (The precise launch date is not stated on the canonical docs pages reached; treat "early 2025" as approximate until confirmed.)
- The emission model has changed twice. dTAO originally allocated emissions by price. In November 2025 it switched to flow-based ("Taoflow"). As of June 2026 it REVERTED to a price-based model (subtensor v3.4.6-421, PR #2781). The price-based model is the CURRENT model. (Confirmed against the merged chain code and docs.learnbittensor.org/learn/emissions.)
- CURRENT model (price-based, since June 2026): a subnet's share of network emissions is proportional to root_prop x EMA price x (1 - miner_burn), normalized across all emit-enabled subnets:
  `emission_share_i = (root_prop_i * price_i * (1 - miner_burn_i)) / sum_j(root_prop_j * price_j * (1 - miner_burn_j))`
  - **price** is the subnet's EMA (moving) price in TAO (the on-chain SubnetMovingPrice), NOT the spot/active price.
  - **root_prop** = (T_root * w) / (T_root * w + alpha_issuance), where T_root is network-wide root TAO stake, w is the network tao weight, and alpha_issuance is the subnet's own alpha issuance. It shrinks as a subnet's alpha issuance grows, so emission eases toward newer subnets and decays as a subnet matures: new entrants get an easier on-ramp, incumbents must keep earning their share on price. Use this exact form. Do NOT shorten it to "tao_weight / (tao_weight + alpha_issuance)", which hides the root-stake term.
  - **miner_burn** is the proportion (0..1) of a subnet's miner (incentive) emission in a tempo that is withheld from miners because it goes to an owner/immune hotkey, counted whether it is recycled OR burned. The (1 - miner_burn) term cuts the subnet's chain emission share in lock step: a subnet that routes all miner rewards to the owner/burn key drives its share toward zero; one that stops recovers full share the next tempo (recomputed fresh each tempo, no memory). Validators operate this lever via the weights they set; the triumvirate oversight tooling is the backstop for fake-mining subnets where validators are inactive. The announcement frames it as a boolean (burn all or nothing), but on-chain it is a continuous proportion.
- HISTORICAL (Taoflow, November 2025 to June 2026, now retired): emission share was determined by NET TAO FLOWS (staking minus unstaking), smoothed with an EMA. Do NOT describe this as current. The flow code path is dead in the runtime; the chain still records net flows, but they no longer drive emission, so a "net flow" reading is a demand signal only.
- TAO holders express preference by staking into specific subnets (buying alpha), which lifts the subnet's price and therefore its emission share. This is "voting with your TAO."

## Emissions and Halving

- Daily TAO emission is currently ~3,600 TAO (0.5 TAO per block). The first halving cut block rewards by 50% (from 1.0 to 0.5 TAO/block, i.e. ~7,200 to ~3,600 TAO/day).
- Halvings are SUPPLY-BASED, not calendar-based: a halving triggers automatically when total TAO issuance reaches preset thresholds, so timing depends on issuance, not a fixed date. (The first halving landed around December 2025; treat the date as approximate, the trigger is issuance.)
- TAO has a hard cap of 21 million tokens (the same 21M cap applies to each subnet's alpha token). Circulating supply changes over time; do not state a fixed circulating figure.
- Every block (~12 seconds) TAO is injected into subnet pools based on each subnet's price-based emission share (root_prop x EMA price x (1 - miner_burn)). At the end of each tempo (360 blocks, ~72 minutes), the tempo's accumulated alpha is distributed through Yuma Consensus.
- The distribution split is FIXED at the protocol level: 18% subnet owner, 41% miners, 41% validators and their stakers. It is not subnet-configurable. Individual staker payouts vary with the validator's take (default 18%), not with this split.

## Staking

- Staking TAO on a subnet converts TAO to alpha through the AMM pool.
- Unstaking converts alpha back to TAO through the same pool.
- There is slippage on both operations, especially with thin liquidity pools.
- Stakers earn rewards through their chosen validators. Validators receive emissions and distribute to their stakers proportionally.
- Stakers can choose how to receive rewards: "Keep" (receive alpha tokens) or "Swap" (alpha is automatically converted to TAO).

## Conviction and Locking (recent upgrade)

- Conviction staking lets a coldkey LOCK alpha to a specific hotkey on a subnet, building an on-chain "conviction" score over time. It is a public commitment signal that cannot be silently reversed. (Source: docs.learnbittensor.org/staking-and-delegation/conviction-staking.)
- Locking does NOT change emissions or rewards. Canon, verbatim: "Locking stake does not change the amount of emissions you receive." Locked alpha still earns normal staking rewards. NEVER write that locking or conviction boosts emissions, weight, or rewards.
- Two modes: perpetual (conviction grows toward the locked amount: ~63% at one time constant, ~90% at ~2.3 time constants) and decaying (unwinding forces a public exponential-decay window before the lock is gone, giving advance warning of a large exit).
- The time constant (MaturityRate / UnlockRate) is currently a 90-day half-life and is governance-settable. Do not state a fixed number as permanent.
- Owner specifics: a subnet owner's per-epoch cut is NOT auto-locked by default (opt-in). Any lock targeting the owner's hotkey instantly matures conviction to the full locked amount.
- Future ownership transfer (NOT yet active): a proposed feature would transfer ownership if a subnet is at least one year old AND aggregate conviction reaches at least 10% of the subnet's alpha out, handing the owner hotkey to the highest-aggregate-conviction holder. So ownership can change by means other than deregistration. Treat as not-yet-live.
- Constraints: staked alpha cannot be unstaked below the locked amount; locked alpha cannot move cross-subnet directly; conviction is wiped if the subnet is deregistered.
- Locked-alpha transfer flag (added with the June 2026 upgrade, subtensor v3.4.6-421): coldkeys REJECT incoming locked alpha by default. A coldkey must opt in (via set_reject_locked_alpha set to disabled) to receive locked alpha through stake transfers or coldkey swaps. This is a transfer-acceptance control only; it does not change emissions or rewards.

## Chain Buys vs Emission Share (CRITICAL DISTINCTION)

- **emission_pct / emission_percent**: The subnet's share of total network emissions. This is how much of the 3,600 daily TAO the subnet receives. Driven by the price-based formula (root_prop x EMA price x (1 - miner_burn)).
- **emission_buy_pct / emission_chain_buys_percent**: The percentage of a subnet's emissions that are being market-bought through the AMM (chain buys). This is a SEPARATE metric.
- **emission_miner_burn / miner_burn**: A THIRD, distinct metric. The proportion (0..1) of a subnet's miner emission withheld from miners (sent to the owner/burn key) in a tempo. It is NOT emission share and NOT chain buys. Under the price-based model it directly cuts emission share via the (1 - miner_burn) term: a higher miner_burn lowers the subnet's network emission share. Keep all three terms distinct.
- These metrics are independent. A subnet can have 5% emission share and 0% chain buys. This is normal and can be positive.
- The per-block alpha injection cap is now root_prop-based (root_prop x alpha_emission). As a subnet matures (alpha issuance grows, root_prop falls), more of its TAO emission can no longer be injected as pool liquidity and is routed to chain buys instead. Rising chain buys on an older subnet is therefore a structural feature of maturity, not a warning sign.
- Low or zero chain buys is NOT a risk. It can indicate the subnet is healthy enough that organic demand covers growth without needing emission-funded buying pressure.
- When writing about chain buys, ALWAYS use the term "chain buys" or "chain buy rate." NEVER call it "emission buy" or "emission rate" as this will be confused with the subnet's emission share.
- The "emission acceleration ratio" (chain_buys / ema) is a momentum signal, not a health metric. A ratio below 1.0 or at 0 does not mean the subnet is unhealthy.

## Common Mistakes to Avoid

- "Emissions are only paid in alpha" --> INCOMPLETE. Both TAO and alpha are injected into the pool each block; at tempo, alpha is distributed to participants (18/41/41) and the injected TAO backs the pool reserve. Stakers can keep alpha or swap to TAO.
- "Each subnet sets its own emission split" --> WRONG. The 18% owner / 41% miners / 41% validators split is FIXED at the protocol level. What varies is the validator's take (default 18%), which affects individual staker payouts, not the split itself.
- "Subnet emissions are based on net TAO flows / Taoflow" --> OUTDATED as of June 2026. Emissions reverted to a PRICE-based model: root_prop x EMA price x (1 - miner_burn). Taoflow (flow-based) was the model only from November 2025 to June 2026. Saying emissions are price-based is now CORRECT, not an error.
- "Validators mine" --> WRONG. Validators evaluate and set weights. Miners produce work.
- "TAO is burned when staking" --> WRONG. TAO goes into the AMM pool, it is not destroyed. TAO IS burned when registering on a subnet (different operation).
- "All subnets do AI" --> WRONG. Some do DeFi, gaming, data, infrastructure, etc.
- "Stakers earn directly from the network" --> MISLEADING. Stakers earn through validators.
- "Daily emissions are 7,200 TAO" --> OUTDATED. Current daily emission is ~3,600 TAO (0.5 TAO/block) after the first halving. Halvings are supply-triggered, not calendar-based.
- "0% emission buy rate" as a risk --> WRONG. Chain buys at 0% is not a risk indicator. Never flag it as one.
- "Emission buy" without specifying "chain buys" --> CONFUSING. Always say "chain buy rate" not "emission buy" to avoid confusion with the subnet's emission share.