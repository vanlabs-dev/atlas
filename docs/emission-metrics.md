# Emission & miner-economics metrics

How to read TaoSwap emission data correctly, and which fields lie.

Every constant and formula below was **verified against live data**, not taken
from protocol documentation. Verification method is recorded next to each claim
so it can be re-run. Where a claim was tested on only some subnets, the sample
is stated.

**Evidence base:** TaoSwap snapshot `2026-08-11T04:30:02Z`, `as_of_block`
8818814, 129 subnets, plus 30 full `/metagraph/{netuid}/` pulls. Derived during
the mining-triage exercise; working files under `triage/` (untracked).

---

## 1. Endpoints

| Endpoint | Gives |
|---|---|
| `GET /v2/subnets/` | one row per subnet: price, emission, burn, pool depth, identity, dereg |
| `GET /metagraph/{netuid}/` | `{subnet, count, neurons[]}` — per-UID incentive, dividends, rewards, type |

Base `https://api.taoswap.org`, **auth: none**. Self-imposed politeness cap
20/min, 1.0 s spacing (`livedata/config.json`, ATLAS-LIVE-007). Both endpoints
are already wired as live-data operations — see `livedata/README.md`.

---

## 2. The emission model

Verified constants:

| Quantity | Value | How verified |
|---|---|---|
| Blocks per day | 7200 | `owner_emission_share × 7200` reproduces `owner_emission_per_day` exactly |
| Alpha emitted per subnet | 1 α/block = **7200 α/day** | `alpha_out_emission` = 1.0 on all 129 subnets |
| Network TAO emission | **0.5 TAO/block** | `sum(emission_value)` = 0.49999994; `sum(emission_percent)` = 100.000 |
| Owner share | **18%** = 1296 α/day | `owner_emission_share` = 0.179995 on every subnet |
| **Miner pool** | **41%** = **2952 α/day** | a pure miner's `daily_rewards_alpha ÷ incentive` = **2952.07** |
| Validator pool | **41%** = 2952 α/day | netuid 13 dividend rows sum to 2952.02 |

The owner's 1296 α/day is paid **outside the neuron list** — summing
`daily_rewards_alpha` over all neurons yields 5904 (= 82%), not 7200.

### Volatile inputs — never hardcode these

The table above is structural: those values change only if the protocol
changes. Everything below moves continuously and **must be pulled live at
use time**. A figure quoted without its `as_of_block` is not a number, it
is a rumour.

| Input | Where to get it live |
|---|---|
| TAO/USD | CoinGecko spot via `live_price` (`livedata/atlas_live.py`, Q30 — spends no TaoStats quota). Fallback: `emission_usd ÷ emission_tao` from any metagraph neuron, which self-refreshes with the payload. |
| Subnet alpha price | `price` in `/v2/subnets/`, or `subnet.price` in the metagraph payload |
| `registration_cost` | `/v2/subnets/` — a **dynamic recycle price** that rises with demand |
| `emission_percent`, pool depths, `active_miners` | `/v2/subnets/`, per call |

**Prefer alpha over fiat.** Alpha/day is price-free and stays correct as
markets move; TAO and USD are conversions applied at the moment of
reporting, not properties of the subnet:

```
alpha/day  = 2952 × incentive(uid)          # structural, no price input
TAO/day    = alpha/day × subnet.price       # live price required
USD/day    = TAO/day × TAO_USD              # live rate required
```

Payback is best expressed without fiat at all, since registration cost is
already denominated in TAO:

```
payback_days = registration_cost / (alpha_per_day × subnet.price)
```

### Payment streams

- `incentive` → **miner** stream, pool distributed ∝ incentive
- `dividends` → **validator** stream, pool distributed ∝ dividends

A single UID may hold both. Do not treat them as one number.

Verified: predicted vs actual `daily_rewards_usd` agrees within **0.7%**
(netuids 55, 54); pool-level prediction within **0.1–2.6%** (netuids 11, 83).
Conversion formulas are in §2.1 — derive in alpha, convert last.

---

## 3. `emission_miner_burn`

**Unit: percent, 0–100.** Not a fraction. Verified: 75 of 129 values exceed 1.0;
min 0.0, max 100.0. A subnet at 100.0 pairs with `emission_percent` 0.0.

**Mechanism: a designated burn UID absorbs that share of the miner incentive
stream.** Confirmed on all 16 burning subnets in the sample — the burn UID's
`incentive` matches the reported burn to 3–4 decimals every time.

The burn UID is usually `type: "owner"` but **not always**, and it may *also*
earn dividends. Locate it by incentive share, then confirm by residual:

```
sum(incentive where type == "miner") ≈ 1 − burn/100      # burn UID excluded
```

Do **not** identify it by a loose tolerance on incentive alone — a ±0.02 window
produced false positives on netuids 55 and 54 (real miners whose incentive
happened to sit near a small burn value).

---

## 4. Deriving what a *new* miner can earn

This is the metric that matters, and it is not `2952 × (1 − burn)`.

`type` is a **validator-permit flag**, not a payment role. Permit-holding UIDs
mine too, and on many subnets they capture most of the incentive. A new entrant
without stake joins as `type: "miner"`, so that subset is the correct reference
class.

```
accessible_incentive_share = sum(incentive where type == "miner")
accessible_pool_alpha_day  = 2952 × accessible_incentive_share
stake_gated_share          = sum(all incentive) − accessible − burn/100
```

**On 14 of 30 subnets sampled, the accessible share was far below `1 − burn`.**
Worst observed:

| netuid | accessible | stake-gated | accessible pool (α/day) |
|---|---|---|---|
| 63 Enigma | 0.0001 | 0.9998 | **0.4** across 244 slots |
| 48 Quantum Compute | 0.0000 | 0.9999 | 0.0 — zero earning miners |
| 126 Poker44 | 0.0000 | 0.6971 | 0.0 — zero earning miners |
| 15 ORO | 0.0600 | 0.9394 | 177.1 |
| 70 NexisGen | 0.0969 | 0.9031 | 285.9 |
| 114 SOMA | 0.1000 | 0.9000 | 295.2 |
| 8 Vanta | 0.2973 | 0.7025 | 877.6 |

(Against a 2952 α/day ceiling. Alpha figures are structural and hold
regardless of price; the incentive shares are the underlying measurement.)

Using `2952 × (1 − burn)` on netuid 63 overstates the reachable pool by
**four orders of magnitude**.

---

## 5. Fields that are wrong, empty, or misread

| Field | Problem |
|---|---|
| `active_miners` | Counts **earners**, not participants. Disagreed with the metagraph on every subnet checked. Registered miner slots are typically ~240 while `active_miners` reads 1–245. Never use it as a per-miner denominator. |
| `block_at_registration` | **0 for all 256 neurons on every subnet.** Registration age, churn rate, and time-to-deregistration are **not obtainable** from this API. |
| `daily_rewards_alpha` | **Sums both streams.** On a dual-role UID it includes validator income. Summing it over incentive-earners inflated 6 of 30 subnets by up to 96% (netuid 26 read 5795 α/day against a 2952 ceiling). Use `2952 × incentive` for miner-stream alpha. |
| `daily_rewards_alpha` (burn) | Does **not** net out the burn. Netuid 13 at 70.68% burn still shows ~2949 α/day across incentive rows. |
| `registration_cost` (per-neuron, metagraph) | Broadcast as a single constant on most subnets — does not reflect what incumbents paid. Subnet-level `registration_cost` is the live recycle price and is **dynamic**. |
| `total_alpha_burned` | Reads 0 while `alpha_burned_all_time` holds the real figure (netuid 107: 0 vs 384,341,056,353,167 rao, the latter matching the TaoSwap UI). |
| `mechanism_emission_split` | Empty array `[]` with `mechanism_count` 1 across the sample. Untested for multi-mechanism subnets. |
| UID capacity | **Not always 256.** Netuid 107 has 94 UIDs (85 miner slots) — real headroom. Netuid 18 reports **257** against a 256 cap, unexplained. Check per subnet; do not assume full. |

---

## 6. Recommended metric set

For miner viability, these held up under adversarial re-checking:

| Metric | Definition |
|---|---|
| `miner_slots` | count of `type == "miner"` |
| `earning` | miner slots with `daily_rewards_usd > 0` |
| `earn_rate_pct` | `earning ÷ miner_slots` — the single best viability signal |
| `accessible_inc_share` | §4 — how much of the pool a stake-less entrant can reach |
| `median_alpha_day` / `p25` | `2952 × incentive`, or measured from `daily_rewards_alpha` on single-stream UIDs |
| `top10_share_pct` | concentration; >90% means the median is meaningless |
| `payback_days` | `registration_cost ÷ (median_alpha_day × subnet.price)` |

Report in **alpha** and convert to fiat only at the moment of display, with
the rate's timestamp attached. Fiat columns stored in a CSV are stale the
moment they are written.

**Never report a per-miner mean.** Distributions are extreme: netuid 54 has a
top-decile share of 96.7% and netuid 8 of 80.5%, with medians three orders of
magnitude below their top earners. Report median with p25 and top10 share.

**Cross-check any subnet-level claim against the metagraph.** Every error found
during this exercise came from trusting a `/v2/subnets/` aggregate without
opening the neuron list.

---

## 7. Worked example — netuid 107 (Minos)

Confirmed against the TaoSwap mobile UI 2026-08-11:

| UI | Field | Value |
|---|---|---|
| Miners 20 | `active_miners` | 20 — **earners**, matching metagraph |
| Miner Burn 0.0% | `emission_miner_burn` | 0.0 |
| Reg. Cost 0.9900 τ | `registration_cost` | 0.99 |
| Root Proportion 36.13% | `root_proportion` | 0.36142 |
| Top 10 share 33% | `top10_share` | 0.3289 |
| Alpha Burned 384.34K | `alpha_burned_all_time` | matches (not `total_alpha_burned`) |

Metagraph: 94 UIDs — 85 miner / 8 validator / 1 owner. So 20 of 85 miner slots
earn (23.5%); 65 registered miners earn nothing. The UI shows neither the slot
count nor the zero-earners.

`accessible_inc_share` 0.9998 → accessible pool **2951.5 α/day** (nothing
stake-gated). But `top10_share` is 92%: the top UID holds incentive 0.899 =
**2654 α/day**, against a median of **9.05 α/day**. One UID takes 90% of the
subnet's entire miner emission.

Payback at the median, price-free in structure:
`0.99 TAO ÷ (9.05 α/day × price)` ≈ **1.8 days** at the snapshot price —
recompute with a live price before quoting it.

Also note 107 is the one subnet in the 30-subnet sample **not at UID capacity**
(94 of 256), so registering does not require displacing an incumbent.

Emission read 9.02% in the UI vs 9.050% in the 04:30Z snapshot — normal drift,
and the only field that moved.
