# Fact-Check Patterns

Scan the article for these patterns before saving. If any ERROR patterns match, save as draft regardless of auto-publish threshold.

## CRITICAL: SOURCE VERIFICATION (before anything else)

### 0. Unverified mechanism claims
Pattern: Any description of how miners/validators work that was NOT read directly from the subnet's actual main repository README or official docs.

**Check**: For every "miners do X" or "validators do Y" statement, can you point to the exact source line? If not, it's speculation.

**Common failure**: On-chain `github` field may point to a secondary repo (e.g. a competition or fork), not the main subnet code. Always verify the repo you're reading IS the subnet's primary codebase.

Fix: Replace with what the source actually says, or write "details of the mechanism are not publicly documented" if no source exists.

## ERRORS (must fix before publishing)

### 1. Emissions described as single-token
Patterns: "emissions paid in tao", "earning tao from emissions", "tao emissions distributed to miners/validators", "receives tao as emissions", "emissions in tao" (but NOT "tao flow"), "emissions paid only in alpha", "emissions are only alpha"

Fix: Both TAO and alpha are injected into the pool each block. At tempo, alpha is distributed to participants via the fixed 18/41/41 split (owner/miners/validators), and the injected TAO backs the pool reserve. Do not describe emissions as only one token.

### 2. Outdated emission rate
Pattern: "7,200 tao" or "7200 tao" when NOT preceded by "from" or "dropped from"

Fix: Current daily emission is ~3,600 TAO (0.5 TAO/block) after the first halving. Halvings are supply-triggered, not calendar-based, so avoid asserting a fixed halving date.

### 3. Outdated emission model
Patterns: "emissions based on net tao flows", "taoflow determines/drives emissions", "flow-based emissions", "net staking flows determine emissions" (when NOT describing Taoflow as the historical November 2025 to June 2026 model)

Fix: As of June 2026, emissions are PRICE-based again (subtensor v3.4.6-421), and the price model itself has since evolved: root_prop was removed from the share on 2026-07-16 (spec 432), an emission gate was added on 2026-07-27 (spec 440), and the gate's bar became rank-pinned on 2026-08-03 (spec 441). The CURRENT share is EMA price x (1 - miner_burn), normalized across emit-enabled subnets, then passed through a Hill gate that collapses below-bar (low-demand) subnets toward zero and redistributes to above-bar subnets. Taoflow (flow-based) applied only from November 2025 to June 2026. A correct price-based description must NOT be flagged.

### 3a. Outdated price-based formula (root_prop in the share, or no gate)
Patterns: "root_prop x EMA price", "root proportion weights/determines emission share", any CURRENT-tense share formula that includes root_prop, or any claim that every subnet with demand earns a proportional share (ignoring the gate).

Fix: Since 2026-07-16 (spec 432) root_prop does NOT weight emission share (it still caps alpha injection and splits root dividends). Since 2026-07-27 (spec 440) the normalized share additionally passes through the emission gate: gate(s) = s^h / (s^h + theta^h), where theta (the bar) is recomputed every 360 blocks. Since 2026-08-03 (spec 441) the bar is selected by RANK PIN, not by q-mass: EmissionBarRank (N) pins theta to the Nth-largest positive demand share, and EmissionBarQuantile is inert while N > 0 (see 7d). Code default at v443 is N = 32; h defaults to 3. All three are sudo-settable and have already moved live (q was observed at 0.75 on 2026-07-28, before rank pinning made it inert), so never state a current value without a chain read. Below-bar subnets' emission collapses toward zero; above-bar subnets receive more than their raw demand share.

### 3b. Mechanic applied to the wrong emission era (temporal misattribution)
Pattern: any past-tense claim ("was", "were", "historically", "used to", "before the change", "has always") that applies a mechanic from a different era than the one in effect then. Most common: stating or implying that miner_burn affected a subnet's emission share BEFORE June 2026 (e.g. "burning was costing them emission share", "miner_burn has always cut the network share").

**Check**: For any past-tense claim about a mechanic, confirm the mechanic existed in the emission model active during that period. The eras: original dTAO price-based (February 2025 to November 2025); Taoflow net-flows (November 2025 to June 2026); price-based with root_prop weighting (June 2026, spec 421, to 2026-07-16, spec 432); ungated price x (1 - miner_burn) (2026-07-16 to 2026-07-27); gated with a q-mass bar (2026-07-27, spec 440, to 2026-08-03); gated with a rank-pinned bar (2026-08-03, spec 441, onward). The (1 - miner_burn) coupling exists in ALL the post-June-2026 price eras but NOT before: under Taoflow emission share was set by net TAO flows, so miner_burn did NOT affect emission share, and under the original dTAO the ground truth does not establish a coupling either. root_prop weighted the share ONLY June 2026 to 2026-07-16. The emission gate exists ONLY from 2026-07-27.

Fix: Use the model in effect THEN. For a subnet that burned historically and is now setting miner_burn to 0%: under Taoflow burning did not touch emission share; every post-June-2026 price model puts miner_burn in the formula via (1 - miner_burn), so burning is now self-taxing at the network level. If unsure which era a past event sits in, drop the historical claim. Never apply a current mechanic (gate, root_prop removal, miner_burn coupling) retroactively.

### 4. Root validators voting on emissions
Pattern: "root validators vote/voting/decide/determine emissions"

Fix: Root validator voting was replaced by dTAO in February 2025. Emissions are now gated price-based: EMA price x (1 - miner_burn), normalized across emit-enabled subnets, then passed through the emission gate.

### 5. Validators mine
Pattern: "validators mine/mining/produce work"

Fix: Validators evaluate and set weights. They do not mine.

### 6. TAO burned when staking
Pattern: "tao burned/burns when/during/by staking"

Fix: TAO goes into the AMM pool when staking (it is not destroyed). TAO is only consumed at registration (the "burn cost"), where it is recycled.

### 7. Chain buys confused with emissions
Patterns: "emission buy.*0%", "zero emission", "0% emission", "no emission" when referring to chain_buys or emission_buy_pct

Fix: "Chain buys" (emission_chain_buys_percent / emission_buy_pct) measures what percentage of a subnet's emissions are being market-bought through the AMM. This is NOT the subnet's emission share. A subnet can have high emissions (emission_pct) and 0% chain buys simultaneously. NEVER flag low/zero chain buys as a risk. Low chain buys can indicate the subnet is performing well enough that organic staking demand covers growth without needing emission-funded buying. Always use the term "chain buys" or "chain buy rate" when referencing this metric, never just "emission" which implies the subnet's emission share.

### 7b. Locking or conviction described as boosting emissions
Pattern: "locking ... boosts/increases ... emissions", "conviction ... earns more", "locked stake ... higher rewards/weight"

Fix: Locking stake (conviction) does NOT change emissions or rewards. Canon: "Locking stake does not change the amount of emissions you receive." It is a commitment signal only; locked alpha earns normal staking rewards.

### 7c. Miner burn confused with chain buys or emission share
Pattern: treating "miner burn" / emission_miner_burn as the same thing as chain buys, or as the subnet's emission share.

Fix: miner_burn is a THIRD distinct metric: the proportion (0..1) of a subnet's miner emission withheld from miners (sent to the owner/burn key) in a tempo, counted whether recycled or burned. Under the price-based model it scales the subnet's emission share via the (1 - miner_burn) term. It is NOT chain buys and NOT emission share. Keep all three terms distinct.

### 7d. Emission gate bar described as a q-mass quantile
Pattern: "the bar is the share at which cumulative demand crosses q", "subnets above the bar carry 75% of demand", or quoting EmissionBarQuantile as the thing that sets the bar.

Fix: OUTDATED as of spec 441 (live 2026-08-03). The bar is selected by EmissionBarRank (N): when N > 0 theta is pinned to the Nth-largest positive demand share and the quantile is INERT. Q-mass is only the N = 0 fallback. Rank mode is currently active (N unset on chain, code default 32 at v443). Never state a live N, q, or h without a chain read, and never quote a live q as if it set the bar.

### 7e. Bar crossing reported as a demand movement
Pattern: "subnet X's demand rose above the bar" when what actually happened is that the bar moved.

Fix: a rank-pinned bar IS a demand share, so it moves on its own as the distribution shifts, and a subnet can change side with a completely stationary share. Compare the bar to its previous value before attributing a crossing to the subnet. Worked example: the spec-441 bar reset on 2026-08-03 dropped theta about 14.5% in one poll and pushed subnets 49, 67, 79 and 81 above the bar without their shares moving.

### 7f. Root Reborn curation described as dormant, or a specific validator described as curating without evidence
Pattern: "curation is disabled", "root dividends just accumulate in place", "validators cannot set root weights yet", or "validator X is deploying basket capital" with no weight vector cited.

Fix: Curation is LIVE since spec 449 (2026-08-27): `RootWeightSettingEnabled` is true and `set_root_weights` works under a 1/16 `RootWeightsCap` (at least 16 destinations). It is per validator: a fund whose validator has set no vector still runs the null strategy. State the mechanism as live; attribute curation to a specific validator only from its public weight vector. In force since spec 441 and unchanged: only root-registered hotkeys earn root dividends (the remainder is recycled), root unstakes sit behind a hold interval, calls 122/123 are retired.

## WARNINGS (verify but don't block)

### 8. Em dashes
Check for U+2014 or U+2013 characters.

Fix: Replace with commas, periods, or colons.

### 9. "All subnets" claims
Pattern: "all subnets do/are/use/run/focus"

Fix: Not all subnets do the same thing. Verify the claim is accurate.

### 10. "You earn by staking TAO"
Pattern: "you earn by staking tao"

Fix: Stakers earn through validators, not directly. Verify the wording.

## Self-Check Procedure

After writing, before saving:
1. **SOURCE CHECK (most important):** For every claim about how the subnet works, confirm you read it from the subnet's ACTUAL main repo or docs. If the on-chain github points to a different repo than the main subnet code, flag it.
2. **SOURCE PRIORITY CHECK:** Official subnet docs, repo, website, litepaper, and live product surface outrank TAO.app, TaoSwap, TaoStats, Supabase mirrors, Desearch, and social/web summaries for mechanism and product-status claims. The repo is only authoritative after a TaoSwap on-chain identity call confirms the current slot owner declares it. Use APIs to fill gaps, not to overrule official sources.
3. **CONFLICT CHECK:** If official/repo sources diverge from TAO.app, TaoSwap, TaoStats, Supabase, or Desearch on a material claim, the third party is stale: use the official/repo value and proceed. This is NOT a conflict and does not hold the article. Only hold as draft for a GENUINE conflict: two primary sources disagree, the repo is internally ambiguous, the repo 404s or went private, or the on-chain owner changed since last publish. See `references/data-sources.md` "Authority Tiers and Conflict Resolution."
4. Read the article once looking for each error pattern above
5. Verify every number/metric against the data brief
6. Check that no information was fabricated (if data was missing, the article should say so)
7. Confirm no em dashes exist anywhere
8. Confirm the article follows the exact heading structure from article-format.md
9. Ask: "If the subnet team reads this, will they say it's accurate?" If unsure about ANY claim, soften the language or remove it.
10. **TEMPORAL CHECK:** For every past-tense claim about a mechanic, confirm it used the emission model in effect THEN (see error 3b). The (1 - miner_burn) emission-share coupling is June 2026+ only; under Taoflow (Nov 2025 to June 2026) miner_burn did not affect emission share. Never apply a current mechanic retroactively.