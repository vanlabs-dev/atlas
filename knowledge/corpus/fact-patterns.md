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

Fix: As of June 2026, emissions are PRICE-based again (subtensor v3.4.6-421). emission_share is proportional to root_prop x EMA price x (1 - miner_burn), normalized across emit-enabled subnets. Taoflow (flow-based) applied only from November 2025 to June 2026. A correct price-based description must NOT be flagged.

### 3b. Mechanic applied to the wrong emission era (temporal misattribution)
Pattern: any past-tense claim ("was", "were", "historically", "used to", "before the change", "has always") that applies a mechanic from a different era than the one in effect then. Most common: stating or implying that miner_burn affected a subnet's emission share BEFORE June 2026 (e.g. "burning was costing them emission share", "miner_burn has always cut the network share").

**Check**: For any past-tense claim about a mechanic, confirm the mechanic existed in the emission model active during that period. The (1 - miner_burn) coupling between miner_burn and emission share is the June 2026 price-based model ONLY. Under Taoflow (November 2025 to June 2026) emission share was set by net TAO flows, so miner_burn did NOT affect emission share. Under the original price-based dTAO (to November 2025) the ground truth does not establish a miner_burn coupling either, so do not assume one.

Fix: Use the model in effect THEN. For a subnet that burned historically and is now setting miner_burn to 0%: under Taoflow burning did not touch emission share; the June 2026 price-based model put miner_burn in the formula via (1 - miner_burn), so burning is now self-taxing at the network level. If unsure which era a past event sits in, drop the historical claim. Never apply the current coupling retroactively.

### 4. Root validators voting on emissions
Pattern: "root validators vote/voting/decide/determine emissions"

Fix: Root validator voting was replaced by dTAO in February 2025. Emissions are now price-based: root_prop x EMA price x (1 - miner_burn), normalized across emit-enabled subnets.

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