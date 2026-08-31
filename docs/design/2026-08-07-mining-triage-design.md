# Mining triage design

Date: 2026-08-07
Status: pre-proposal record, kept on purpose. The change design is
`openspec/changes/archive/2026-08-11-mining-triage/design.md`, which
supersedes this file and links back to it for the assignment check.
Supersedes: none

## Assignment check result (2026-08-07, on the Pi)

Both blocking questions are answered. Findings are folded into the sections
below; the raw outcome:

**The endpoint is healthy and the fields are real.** The TaoSwap
`/v2/subnets/` outage recorded in `docs/decisions.md` from 2026-08-06T03:34
has cleared. Three live fetches at 2026-08-07T03:57Z returned HTTP 200,
`validation_result: valid` against `taoswap/subnets.v1`, block reference
8789861, `freshness_status: unknown-upstream` (the endpoint carries no
upstream timestamp, which is a known property, not a fault). Every field
the screen needs is populated on 128 of 129 subnets; the single null row is
netuid 0, root, which legitimately has no miner economics.

**The gate is a strong first filter.** 85 subnets have
`emission_is_enabled` true, 43 have it false, 1 null. A third of the field
is removed before any other test runs.

**Registration cost is not the barrier.** Median `registration_cost` is
0.006 TAO, max 1.0 TAO across gate-enabled subnets. The design assumed
amortising a meaningful burn; that assumption is wrong and the term is
close to noise. Recurring GPU rent dominates entry cost.

**`active_miners` is not the field size.** Median 6, max 251, sum 3675
across 85 subnets, with 10 subnets reporting 0 and 13 reporting 1. Netuid 1
reports 3. Registered UID counts are far higher, so the field counts
something narrower. Resolved in the second check below.

**The emission split is confirmed, with a citation.** `atlas-kb` returns
`ground-truth.md::Emissions and Halving` lines 58-65, `evidence_state:
confirmed`, coverage date 2026-08-06: "The distribution split is FIXED at
the protocol level: 18% subnet owner, 41% miners, 41% validators and their
stakers. It is not subnet-configurable." Independently corroborated by the
live panel: `conviction.owner_emission_share` is exactly 0.18 on all 84
subnets that report it.

**`MinerBurned` weights the subnet's price share.**
`pallets/subtensor/src/coinbase/subnet_emissions.rs` at indexed sha
`c02a376ecee28718970962562fece409b695df72`: "Weight each subnet's price
share by (1 - miner_burned), then renormalize. The effective emission is
proportional to price_i * (1 - miner_burned_i)." The storage item is
`MinerBurned` and TaoSwap's `emission_miner_burn` (0-100 percent) maps to
it. This is one of two effects; the second is established in the next
check, and both belong in the formula. Burn distribution across
gate-enabled subnets: median 0.00, 44 subnets at or below 1 percent, 26 at
or above 50, 10 at or above 99.

**Second check, same day: the three open questions are closed.**

*`MinerBurned` is owner self-mining, and both of its effects are real.*
`run_coinbase.rs` computes it, not the owner: during distribution, miner
incentive landing on owner or owner-associated immune hotkeys is burned or
recycled rather than paid, `withheld_incentive` accumulates it, and
`MinerBurned = withheld / total_incentive` is written to storage. The next
block's share computation multiplies the subnet's price share by
`(1 - MinerBurned)`. So the withholding hits the miner leg at distribution
and the share penalty hits the subnet's emission afterwards. They are
sequential, not the same effect counted twice, and the original formula
`alpha_in_emission x 0.41 x (1 - miner_burn)` is correct: the share penalty
is already inside the observed `alpha_in_emission`, and the withholding is
a separate deduction from the miners' leg.

The field is therefore a direct measure of how much of the miner reward
pool the subnet owner takes for itself. Verified against chain: TaoSwap's
`emission_miner_burn` matches chain `MinerBurned` (U96F32, divide by 2^32)
on 127 of 128 subnets to within 0.5 percentage points. On several subnets
the largest single incentive holder's share equals the burn almost exactly
(netuid 1: burn 34.70, top holder 34.7; netuid 19: burn 65.56, top holder
65.6), meaning the owner hotkey *is* the top miner.

*Collateral is dormant on mainnet.* Storage enumeration at finalized head
`0x38f911f2...` returns zero keys under both `CollateralLockShare` and
`MinerCollateral`, against a working control (`MinerBurned` 128 keys,
`Owner` 300). No subnet has set a lock share and no miner holds locked
collateral, so registration today is fully burned with no lockup. The
mechanism is live in code and settable up to 95 percent, so it belongs in
the chain-parameter watch as a switch to detect, not in the cost model as
a number to compute.

*`active_miners` is the count of UIDs earning incentive, less the owner.*
Measured across eight subnets against chain `SubnetworkN` and the
`Incentive` vector: where burn is zero the panel figure equals the count of
UIDs with incentive above zero exactly (netuid 8: 34 and 34; netuid 64: 15
and 15; netuid 3: 5 and 5), and where burn is positive it is exactly one
lower, the excluded UID being the owner's earning hotkey (netuid 1: 4 and
3; netuid 9: 3 and 2; netuid 19: 30 and 29; netuid 5: 239 and 238).

*The finding that matters most came out of the same read.* `SubnetworkN` is
256 on every subnet checked, but only 3 to 15 UIDs earn any incentive on
most of them, and the top ten UIDs take essentially all of it (netuid 1:
top-1 34.7 percent, top-10 100; netuid 9: top-1 55.8, top-10 100; netuid 3:
top-10 100). Mining reward is winner-take-most, so a new entrant's expected
income is not the pool divided by the field, it is zero unless it displaces
an incumbent. The exception profile exists and is visible: netuid 5 has 239
UIDs earning with top-10 taking only 45.4 percent.

*TaoStats is out of the wedge entirely.* Field size and the full incentive
distribution both come from keyless chain storage, so the 10k monthly
ledger is untouched. That is fortunate, because the contracted metagraph
adapter would not have served this anyway: `_pp_metagraph_taostats`
hard-truncates to `rows[:25]` and drops `incentive` from its output.

**Miner registration collateral: real in code, dormant in practice.**
`pallets/subtensor/src/subnets/collateral.rs` (920 lines, same sha): when a
subnet sets a nonzero `CollateralLockShare` (p), the registration price
splits, `(1 - p)` burned and `p` staked to the registering hotkey and
locked. The lock releases at `CollateralDrainRatio` (k) alpha per alpha of
emission earned, and the module doc is explicit: "There is no other exit
path: collateral is never directly withdrawable, and a position that stops
earning emission keeps its remaining collateral frozen indefinitely."
`pallets/subtensor/src/lib.rs` caps the settable share at 95 percent of the
registration price. The SDK notes the storage registry needs regenerating
"against spec >= 435", so this shipped before mainnet's current 443.

No subnet has enabled it (see the dormancy check above), so it is a switch
the screen watches, not a cost the screen computes. If a subnet flips it
on, that subnet's entry risk changes completely and the change should
surface as an event, not as a quietly different number on a board.

## Problem statement

The goal is income from Bittensor, with subnet mining as the primary route.
Deciding where to mine currently means reading 104 subnet repositories and
guessing at their economics. Done by hand that is roughly 30 to 60 minutes
per subnet to answer "can this hardware even run the miner, and does the
subnet pay anyone who is not the owner", so a full pass over the fleet is
50 to 100 hours. It also decays: subnet code churns, emissions move every
epoch, and a shortlist built by hand is stale within weeks.

The blind spot is sharper than the toil. Nothing today answers whether a
given subnet pays a marginal new miner anything at all after the emission
gate, the miner burn, and the existing field are accounted for. Registering
on the wrong subnet costs the registration burn plus a month of GPU rent
before the mistake is visible.

## Status quo

Taostats and TaoSwap web UIs, subnet Discords, and reading repos one at a
time. Three specific failures:

- Neither UI joins economics to feasibility. They will show a subnet's
  emission and price; they will not tell you the miner needs an H100 or
  that the miner body is a thin relay to a closed API.
- Neither nets out cost. Emission percentage is not income. Miner burn,
  the spec 440/443 emission gate, the size of the existing field, alpha
  pool depth on exit, registration burn, and GPU rent all sit between the
  headline and the money.
- Discord is advocacy. Subnet owners are talking their own book, and there
  is no evidence trail back to a line of code.

Atlas already fixed the substrate problem: 104 blobless clones under
`var/fleet/`, a `(netuid,epoch)` FTS index, `atlas-fleet` MCP tools, the
emission-redirect map, and hourly gate polling. The screen does not exist;
the data under it mostly does.

## Wedge

Economics first, deep read only on survivors (D4). Stages A through C2 are
built, all read-only, all inside the existing fleet pass; Stage D is
deliberately not automated.

**Stage A, economics screen, one keyless call.** `subnets_taoswap`
(`/v2/subnets/`) is already contracted and pinned in `livedata/config.json`
and already polled hourly by the gate poll. Its per-subnet fields carry the
whole economics side: `emission_is_enabled`, `emission_miner_burn`,
`alpha_in_emission`, `alpha_in_pool`, `root_in_pool`, `registration_cost`,
`price`, `moving_price`, `tempo`, `dereg`. Competition comes from chain
storage, not from the panel's `active_miners`. No TaoStats quota is
consumed. Per netuid, compute:

- Gate check. `emission_is_enabled` false, or the subnet sitting below the
  rank-pinned `EmissionGateBar` that livedata already tracks. **Corrected
  2026-08-07:** such a subnet still distributes alpha to its miners, because
  `get_subnet_block_emissions` keeps disabled subnets in the map "so the
  normal alpha_out path still runs". What it loses is the TAO inflow backing
  that alpha, so the price decays and TAO income tends to zero. Still cut,
  for that reason rather than for absent payment. Measured 2026-08-07: this
  removes 43 of 129.
- Burn cut. `emission_miner_burn` at or above 99 means the owner captures
  essentially the whole miner pool and the subnet's price share is
  multiplied by 0.01 before renormalisation. Both legs point the same way,
  so these are cut outright, not ranked low. Measured 2026-08-07: 10
  subnets. Operator decision, 2026-08-07.
- Miner-accessible alpha per day = `alpha_out_emission` per day times 0.41
  times `(1 - emission_miner_burn)`. **Corrected during implementation
  2026-08-07:** the base is `alpha_out_emission`, the alpha distributed to
  participants, not `alpha_in_emission`, which is the capped TAO-side pool
  injection. `run_coinbase.rs` annotates `alpha_out_i` as "Total alpha
  emission per block remaining"; `metagraph.rs` documents `alpha_in_emission`
  as the alpha-reserve injection. The 41 percent leg is fixed at protocol
  level. The burn factor is correct here and is not a double count: the
  share penalty is already inside the observed emission, this term is the
  separate withholding at distribution.
- **Quantity is constant, so it is not a ranking input.**
  `alpha_out_emission` is 1.0 on all 127 non-root subnets, gate-enabled or
  not. Miner-accessible alpha is therefore identical everywhere and the
  ranking is driven by `price_tao x (1 - burn)` against concentration.
- Competition, from the chain `Incentive` vector rather than a headcount.
  Record earner count (UIDs with incentive above zero), top-1 share, and
  top-10 share. A subnet where top-10 is at or near 100 percent pays a new
  entrant nothing until it displaces an incumbent, whatever the pool size.
  This replaces the naive divide-by-field-size, which would have been
  meaningless: `SubnetworkN` is 256 nearly everywhere while earners number
  in the single digits.
- Per-miner expectation is reported as a displacement question, not a
  division. Two figures: what the median earner currently receives, and
  what rank you would need to reach to clear the rent.
- Exit haircut. Selling that alpha daily into a pool of `alpha_in_pool`
  against `root_in_pool` moves the price. Apply constant-product slippage
  for the daily sale size and record the haircut percentage as its own
  field, not folded silently into the headline.
- Entry cost. `registration_cost` (median 0.006 TAO) is fully burned today:
  collateral is dormant chain-wide, so there is no lockup component. Entry
  is cheap and the recurring rent dominates. Watch `CollateralLockShare`
  for a transition rather than modelling it: if a subnet flips it on, up to
  95 percent of the registration price becomes a deposit recoverable only
  by earning emission, which changes that subnet's risk profile completely.
- Net TAO per month, and the same figure against the baseline of simply
  staking the entry capital rather than mining it. Staking yield is the
  real do-nothing alternative, not zero.

**Stage B, free code filters over the existing index.** No new fetching;
`fleet_files_fts` is already built and sha-gated rescanning already exists
in `atlas_fleet_metrics.py`. Per active slot, record with `file:line`
evidence:

- `min_compute.yml` if present. The Bittensor subnet template convention
  puts explicit GPU, RAM, and bandwidth floors in this file. Highest value
  single target in the whole scan.
- Miner entrypoint presence and path (`neurons/miner.py`, `miner.py`,
  `template/miner/*`). Absent entrypoint is a strong signal the repo is a
  stub or the miner is closed.
- GPU tells: `torch.cuda`, `device="cuda"`, `vllm`, `bitsandbytes`,
  `nvidia`, dockerfiles with CUDA base images.
- Closed-shop tells: the miner body calling a hosted inference API
  (`openai`, `anthropic`, `api_key` in miner paths). Not disqualifying, but
  it changes the cost structure from rent to per-token spend and should be
  labelled.
- Staleness, reused from `metric_activity` and `metric_branch_tips` rather
  than recomputed.

**Stage C, join and cut.** One ranked table. Order by net TAO per month,
require feasibility not-impossible, emit the top ten to a board page and
a JSON view. Everything cut stays visible with the reason it was cut, so
the screen can be argued with.

**Stage C2, the question surface.** The same joined table exposed as
read-only MCP tools on the existing `atlas-fleet` server, so the shortlist
can be asked about in Hermes rather than only looked at. Without this the
deliverable is a page; with it the screen is queryable as the numbers move,
which is the point of running it every pass rather than once.

**Stage D is not automation.** For the roughly ten survivors, the deep read
is done with `fleet_search`, `fleet_file`, and `atlas-repo`, by hand or by
an agent, answering what the incentive mechanism actually rewards, how
validators score, and what "competitive" would take. Building a tool for
that step before Stage C has run once would be inventing work.

## Keep-going demo

One page at `http://192.168.0.150:8480/mining.html`, served by the existing
`atlas-dashboard.service`. Ten rows. Each row: netuid and name, net TAO per
month, the hardware floor with the `file:line` it came from, burn percent,
earner count and top-10 share, exit haircut percentage, and an honest
confidence marker where an input was null or stale.

Then the same question asked in Hermes, out loud: "which subnets are worth
mining right now, and what changed since the last pass". The answer should
cite the same figures as the page, with block reference and scan
timestamps, and should say `unknown` where the data is missing rather than
smoothing over it.

The bar: after the page and that one exchange, you can name the subnet you
would rent a box for, and say why in a sentence that cites a number. If it
cannot survive that, it is a dashboard opened twice.

## Design

**Data sources.** `subnets_taoswap` for pool depth, price, emission, burn,
and registration cost, already contracted and keyless. The gate poll's
existing bar state for the gate check. Keyless finney RPC for
`SubnetworkN`, the `Incentive` vector, and the `CollateralLockShare` watch.
The fleet FTS index and clones for feasibility. `signal_prices` for alpha
price history. A config constant table for GPU rent bands, set by hand.

No TaoStats. The wedge consumes zero of the 10k monthly ledger.

**Provider boundary (review F1).** All chain and provider access lives in
`livedata/atlas_live.py`, which already owns the finney endpoint list,
retry policy, timeouts, quota ledger, and audit table. The mining collector
imports it rather than opening its own sockets, the same way `fleet`
already reuses repotrack's `collect_range`. Two additions there: a
`twox128` helper and a `read_subnet_maps()` returning field size,
incentive vector, and collateral share per netuid. Every chain read the
screen makes therefore lands in the existing `audit` table, and there is
one place to fix an endpoint. Nothing in `fleet/` calls a network directly.

**Batched reads (review F2).** `state_queryStorageAt` takes many keys at
one block hash, collapsing roughly 260 sequential POSTs into a handful.
Beyond speed, it pins the whole screen to a single block, so earner counts
and burn figures in one pass are internally consistent rather than smeared
across two minutes of chain movement. `state_getKeysPaged` still enumerates
each map prefix once to discover live netuids.

**Storage key derivation.** These are netuid-keyed maps under the
`SubtensorModule` pallet with the **Identity** hasher, so the key is
`twox128("SubtensorModule") ++ twox128(item) ++ netuid_u16_le`, with no
twox64 concat on the key tail. Verified by enumerating each prefix and
observing 2-byte tails. The `twox128` implementation is self-tested against
the three gate keys already pinned in `livedata/config.json` and verified
against live Finney, which is a free correctness check. Value codecs:
`SubnetworkN` u16, `Incentive` SCALE `Vec<u16>` behind a compact length
prefix, `MinerBurned` U96F32 (divide by 2^32, not 2^64),
`CollateralLockShare` u16 normalised by `u16::MAX`.

**Collector shape.** A new `fleet/atlas_fleet_mining.py`, following the
established pattern exactly: read-only, additive tables in the existing
`var/fleet/fleet.db`, per-slot fail-closed, never executes subnet code,
sha-gated rescanning, run inline and fail-isolated after
`atlas_fleet_metrics.run_pass` in the 6h reconcile. Renders a second page
into the existing `var/fleet/www/`. No new systemd unit, no new port, no
new credential.

**Failure paths (review A2).** The two external legs fail independently and
neither takes down the pass. Panel unavailable: no `mine_econ` rows for
that pass, the board renders last-known rows with a stale marker and the
age. Chain RPC unavailable: economics rows are written with
`confidence = chain-unavailable`, competition fields null, and
`net_tao_month` **not computed**, because a net figure without a
competition read is the fabrication this repo exists to avoid. Partial key
set: per-netuid fail-closed, that subnet is marked `unknown`, the rest of
the screen proceeds. A feasibility scan failure on one slot never blocks
another, matching `atlas_fleet_metrics.run_pass`.

**Retention (review F3).** `mine_econ` is pruned below a 90-day cutoff on
each pass, reusing the `DELETE ... WHERE ts < ?` pattern already in
`atlas_fleet_signals.py`. At roughly 516 rows a day the store stays under
50k rows. `mine_feasibility` is sha-keyed and does not grow with time.

**Schema sketch.**

```
mine_econ(ts, netuid, gate_state, alpha_emission_day, miner_burn_pct,
          miner_alpha_day, subnetwork_n, earner_count, top1_share_pct,
          top10_share_pct, median_earner_alpha_day, price_tao,
          alpha_in_pool, root_in_pool, haircut_pct, reg_cost_tao,
          collateral_lock_pct, rent_band, net_tao_month,
          baseline_tao_month, confidence, source_ts, block_ref,
          PRIMARY KEY (ts, netuid))

mine_feasibility(netuid, epoch, sha, min_compute_path, gpu_floor,
                 vram_gb, entrypoint_path, closed_api, evidence_json,
                 verdict, scanned_at,
                 PRIMARY KEY (netuid, epoch, sha))

mine_state(key, value)
```

`verdict` is one of `possible`, `needs-gpu`, `closed`, `stub`, `unknown`,
defined as a module constant rather than free strings. `unknown` is a real
value and is never rendered as `possible`.

Every percentage column carries a `_pct` suffix and is 0-100, not a 0-1
fraction. This is not decoration: `_pp_subnets_taoswap` already carries an
explicit unit warning that `emission_miner_burn` is 0-100, and a silent
factor-of-100 error would put a plausible wrong number on the board rather
than an obvious one.

**CLI, matching the existing shape.**

```
python3 fleet/atlas_fleet_mining.py status
python3 fleet/atlas_fleet_mining.py econ        # Stage A, one keyless call
python3 fleet/atlas_fleet_mining.py feasibility # Stage B, sha-gated scan
python3 fleet/atlas_fleet_mining.py report      # Stage C, ranked JSON
python3 fleet/atlas_fleet_mining.py render      # write var/fleet/www/mining.html
```

**MCP surface.** Three read-only tools added to the existing
`atlas_fleet_server.py` rather than a fourth stdio server, so Hermes needs
no new registration and there is one process, one store handle, one audit
path to reason about:

- `mining_board(limit?, include_cut?)` — the ranked shortlist, each row
  carrying net TAO per month, miner-accessible alpha per day, burn, earner
  count, top-10 share, hardware floor with its `file:line`, and the cut
  reason where a subnet was excluded.
- `mining_subnet(netuid)` — one subnet in full: every economics field with
  its block reference, every feasibility finding with its evidence path and
  scanned sha.
- `mining_history(netuid, field?)` — the recorded passes for a subnet, so
  "what changed" is answered from stored observations instead of inferred.
  Honest `insufficient-history` until at least two passes exist, matching
  how the rotation board reports `n/a` momentum.

Same posture as `fleet_search` and `fleet_file`: store opened `mode=ro`,
fails closed as `mining-screen-unavailable`, never fabricates a field, and
returns both the economics timestamp and the feasibility scan timestamp so
a caller can see which half of an answer is fresh. Economics move every
pass; feasibility is sha-gated and only rescans when a clone moves, which
is correct behaviour but must be visible rather than implied.

**Survives a month away.** It runs on a timer that already exists, needs no
key, writes additive tables to a store that already exists, and renders to
a server that already runs. Tests go in `fleet/tests/` under the existing
off-device pattern. If it is abandoned, the board keeps rendering and the
worst case is stale rows with honest timestamps.

## Fit with the end state

PRD §7 bars hosting a miner. This hosts nothing, signs nothing, holds no
keys, and submits no registration. It ranks evidence, in the same posture
as `fleet-rotation-metrics`, which explicitly "ranks evidence; recommends
nothing".

PRD §7 also bars "building investment scoring before core knowledge and
live-data accuracy are accepted". Those are accepted: Phases 0 to 5 are
complete on the device, the retrieval benchmark passed at 0.95 with zero
fabrications, and the outage battery closed the MV-RI-4 honesty class. The
precondition is met, so this is Phase 7 research territory arriving early
rather than a violation.

Sequencing was decided (D5): mining triage goes first and Phase 6 slips.
That makes `prd.md` §22 and the README "Next step" section wrong until they
are amended, which is part of the work, not a footnote.

## NOT in scope

- Running, deploying, or operating a miner. Different project, different
  hardware, outside this repo.
- Wallet keys, registration, signing, or any transaction. PRD §7 and the
  no-secrets invariant hold without exception.
- Incentive concentration via `metagraph_taostats`. Concentration itself is
  in scope and central, but it comes from keyless chain storage. The
  TaoStats route would cost a few hundred calls per sweep against a 10k
  monthly ledger, and its adapter truncates to 25 rows and drops
  `incentive`, so it could not serve this without a code change anyway.
- Scraping GPU rental prices. A hand-set config constant per band is
  accurate enough to rank and costs nothing to maintain.
- Backtesting the screen against historical outcomes. The
  `signal_outcomes` effectiveness pattern exists and can be reused later,
  but not before the screen has produced a first list.
- Validator economics. Different capital profile, different question.
- Any automated tuning of the cut rule.
- A separate `atlas-mining` MCP server. The three tools go on the existing
  `atlas-fleet` server; a fourth stdio process to register and supervise
  buys nothing.
- Write tools of any kind on the MCP surface. Read-only, in line with every
  other Atlas server.

## Open questions

Closed by the two 2026-08-07 checks: miner share (41 percent, cited),
endpoint outage (cleared), field nullability (128 of 129 populated),
`MinerBurned` semantics (owner capture, both legs real, formula confirmed),
collateral (dormant chain-wide), and `active_miners` (earners minus owner,
and superseded by the `Incentive` vector). Remaining:

- **Registration cost units.** The panel reports a median of 0.006, low
  enough to question whether the field is TAO or alpha denominated.
  Confirm against a chain read of the same subnet's `Burn` before it enters
  any net figure. Low stakes now that entry is known to be cheap and rent
  dominates, but it should not go on a page unlabelled.
- **The one subnet where chain `MinerBurned` and the panel disagree.**
  127 of 128 match. Identify which and whether it is tempo skew or
  something the screen should distrust.
- **How to express displacement.** "You must beat rank N to clear rent" is
  the honest framing given top-10 concentration near 100 percent, but the
  screen needs a defensible way to estimate what reaching rank N takes.
  Without it the board risks implying a subnet is winnable when the real
  answer is that four incumbents have held it for months. Candidate: pair
  concentration with incentive-vector churn over time, which needs history
  the store does not yet have.
- **Budget band (D2 deferred).** The hardware and capital envelope was
  deliberately left to the data. That decision is scheduled, not dropped:
  once the first board renders, pick a band. If it has not been picked two
  weeks after the first render, the honest conclusion is that mining is not
  actually being pursued and the screen should stop being maintained.
- **Holding period for amortising registration burn.** Affects the ranking
  materially. Needs a stated assumption, probably 90 days, flagged on the
  page.

## Assignment

Both verification rounds are done, 2026-08-07, results recorded above. The
Stage A formula is fully sourced and there is nothing left to guess at.

Next action is to build it: `/opsx:propose` a `mining-triage` change
carrying Stages A, B, C and C2, with the storage-key self-test against the
three pinned gate keys as its first test. Stage A over all 129 subnets is
one keyless panel call plus roughly 260 keyless storage reads, so a full
screen costs nothing but time and can run in the 6h fleet pass. The MCP
tools land on `atlas_fleet_server.py` in the same change, since a screen
you cannot ask about is half the deliverable.

Amend `prd.md` §22 and the README "Next step" in the same change, since
D5 put this ahead of Phase 6 and both documents still say otherwise.

## What already exists

Consume these, do not rebuild them.

| Need | Already in the repo |
|---|---|
| Panel economics, keyless, contracted, schema-pinned | `subnets_taoswap` in `livedata/config.json` + `_pp_subnets_taoswap` |
| Chain RPC endpoint list, retry, timeout, audit, quota ledger | `livedata/atlas_live.py` (`_rpc_call`, `QuotaLedger`, `audit`) |
| Verified twox128 storage keys to self-test against | `gate_signal.storage_keys` in `livedata/config.json` |
| Emission-gate bar state and side tracking | `poll_gate_state`, `gate_state`, `gate_sides` |
| Chain-parameter transition watch (host the collateral watch here) | `run_chain_param_watch`, `chain_params`, `chain_param_events` |
| Code search over 104 subnet clones | `fleet_files_fts`, `atlas_fleet_index.py` |
| Sha-gated rescan pattern | `metric_emission_scan` in `atlas_fleet_metrics.py` |
| Staleness and branch pulse | `metric_activity`, `metric_branch_tips` |
| Alpha price history | `signal_prices` in `atlas_fleet_signals.py` |
| Time-series retention pattern | `DELETE FROM signal_prices WHERE ts < ?` |
| Ranked static board render, atomic write, LAN serving | `atlas_fleet_dashboard.py`, `atlas-dashboard.service` |
| Read-only MCP server to extend | `atlas_fleet_server.py` |
| Off-device test pattern | `fleet/tests/` (240 tests green) |

Nothing here needs a new service, port, credential, or timer.

## Data flow

```
                    livedata/atlas_live.py  (sole network boundary)
                    ┌──────────────────────────────────────────┐
  TaoSwap  ───────► │ run_operation("subnets_taoswap")         │
  (keyless)         │   schema-validated, audited, quota-ledger│
                    │                                          │
  finney   ───────► │ state_getKeysPaged  → live netuids       │
  (keyless)         │ state_queryStorageAt → one block hash:   │
                    │   SubnetworkN, Incentive[],              │
                    │   MinerBurned, CollateralLockShare       │
                    │ twox128 self-test vs 3 pinned gate keys  │
                    └────────────────────┬─────────────────────┘
                                         │ import (no socket in fleet/)
                                         ▼
   var/fleet/fleet.db          fleet/atlas_fleet_mining.py
   ┌──────────────────┐        ┌─────────────────────────────────┐
   │ fleet_files_fts  │───────►│ Stage B  feasibility, sha-gated │
   │ metric_activity  │        │   min_compute.yml, entrypoint,  │
   │ signal_prices    │───────►│   GPU tells, closed-API tells   │
   └──────────────────┘        │                                 │
                               │ Stage A  economics              │
                               │   gate cut → burn≥99 cut →      │
                               │   0.41 × (1-burn) × emission →  │
                               │   concentration → haircut → net │
                               │                                 │
                               │ Stage C  join, rank, cut        │
                               └───┬──────────────┬──────────────┘
                                   │              │
                    ┌──────────────▼───┐   ┌──────▼──────────────┐
                    │ mine_econ (90d)  │   │ mine_feasibility    │
                    │ mine_state       │   │ (netuid,epoch,sha)  │
                    └──────┬───────────┘   └──────┬──────────────┘
                           └────────┬─────────────┘
                            ┌───────▼────────┐
                            │ Stage C render │───► var/fleet/www/mining.html
                            │ Stage C2 MCP   │───► atlas_fleet_server.py
                            └────────────────┘         mining_board
                                                       mining_subnet
                                                       mining_history
```

Cut ladder, in order. A subnet leaves at the first gate it fails and the
reason is recorded, never silently dropped:

```
129 subnets
  │
  ├─ emission_is_enabled false ..................... cut  (43 measured)
  ├─ miner_burn_pct >= 99 .......................... cut  (10 measured)
  ├─ feasibility verdict in {closed, stub} ......... cut
  ├─ hardware floor above chosen rent band ......... cut  (band pending, D2)
  │
  └─► ranked by net_tao_month, top 10 to the board
```

## Implementation tasks

Ordered, each independently landable with the fleet suite green after it.

1. `feat(livedata): add twox128 helper with pinned-key self-test` — pure
   function plus the three-key regression test. No network. Lands first
   because everything chain-side depends on it being right.
2. `feat(livedata): add batched subnet map reads` —
   `read_subnet_maps()` over `state_getKeysPaged` +
   `state_queryStorageAt` at one block hash, returning `SubnetworkN`,
   `Incentive`, `MinerBurned`, `CollateralLockShare` per netuid, with
   codec tests for u16, `Vec<u16>` behind all three compact length forms,
   and U96F32.
3. `feat(fleet): add mining store schema and state` — `mine_econ`,
   `mine_feasibility`, `mine_state`, additive, plus the 90-day prune.
4. `feat(fleet): add Stage A economics screen` — gate cut, burn cut,
   miner-accessible alpha, concentration, haircut, net and baseline, with
   the three failure paths and the no-net-without-competition rule.
5. `feat(fleet): add Stage B feasibility scan` — sha-gated, `file:line`
   evidence, verdict enum.
6. `feat(fleet): add Stage C ranked report and cut ladder` — JSON report,
   every cut carrying its reason.
7. `feat(fleet): render the mining board` — `var/fleet/www/mining.html`,
   atomic write, golden-file test alongside `test_dashboard.py`.
8. `feat(fleet): expose mining tools on the atlas-fleet MCP server` —
   `mining_board`, `mining_subnet`, `mining_history`, read-only,
   fail-closed, dual timestamps.
9. `chore(fleet): run the mining pass inline after metrics` — fail-isolated
   `run_pass` hook, no new unit.
10. `docs: record mining-triage and re-sequence the roadmap` — fleet
    README, `prd.md` §22, README "Next step", and the `CollateralLockShare`
    watch entry in `docs/decisions.md`.

## Test plan

Framework: pytest, `fleet/tests/`, off-device, no credentials, matching the
existing 240-test suite. Critical paths and edge cases:

**Regression tests for errors actually hit during verification.** Both of
these produced plausible wrong answers rather than failures, which is the
dangerous kind.

- U96F32 decode divides by 2^32. Decoding `MinerBurned` at 2^64 returned
  0.0 for every subnet and looked like a clean result.
- Netuid map keys use the Identity hasher. A twox64-concat key returned
  null storage for every netuid and looked like an empty map.
- `state_getKeysPaged` returning zero keys must be distinguishable from a
  wrong prefix. The control-map assertion (`MinerBurned` non-empty) is the
  test.

**Codec and unit.** Compact length prefix in all three forms including the
2-byte case a 256-element `Incentive` vector requires; `_pct` columns are
0-100 never 0-1; `SubnetworkN` u16; `CollateralLockShare` normalised by
`u16::MAX`.

**Contract.** No `mine_econ` row carries `net_tao_month` when any input was
null or the chain leg failed. Cut reasons are always populated for cut
subnets. Board rows never render `unknown` feasibility as `possible`.

**Failure paths.** Panel timeout, panel malformed, RPC timeout, RPC partial
key set, store locked by a concurrent reconcile, clone missing for an
indexed slot. Each isolates to its own row or pass and never raises out of
`run_pass`.

**MCP.** `insufficient-history` before two passes exist,
`mining-screen-unavailable` on a missing store, `mode=ro` enforced,
bounded result size, dual timestamps present on every response.

## REVIEW REPORT
Date: 2026-08-07
Sections: Architecture / Code Quality / Tests / Performance / Task Plan
Findings: 14 raised, 14 accepted, 0 rejected, 0 deferred
Outside voice: skipped, subagent dispatch is disabled in this session
Security pass: recommended, declined by operator 2026-08-07 (read-only,
no new credential, LAN-only exposure delta)
VERDICT: APPROVED WITH CHANGES

Accepted findings, all applied to this document:

- **F1 Architecture.** Chain reads moved out of `fleet/` into
  `livedata/atlas_live.py`. Fleet had been given its own sockets, endpoint
  config, retry policy, and a duplicate xxh64, and its chain reads would
  have bypassed the `audit` table.
- **F2 Performance.** ~260 sequential POSTs replaced with
  `state_queryStorageAt` at one block hash. Standard RPC, not a custom
  solution, and it makes each pass internally consistent.
- **F3 Performance.** 90-day retention on `mine_econ`, reusing the
  `signal_prices` prune. It was unbounded at ~188k rows a year.
- **A2 Architecture.** Failure paths for both external legs were unstated.
  Added, with the rule that no net figure is computed without a
  competition read.
- **A3 Architecture.** Primary keys were missing on both tables. Added.
- **A4 Architecture.** Collateral watch routed to the existing
  `run_chain_param_watch` rather than a new mechanism.
- **C1 Code quality.** One twox128 implementation, in livedata, self-tested
  against the three pinned gate keys.
- **C2 Code quality.** `verdict` is a module constant, not free strings.
- **C3 Code quality.** `_pct` suffix on every percentage column. The
  0-100 versus 0-1 trap is already documented in `_pp_subnets_taoswap` and
  would produce a plausible wrong board rather than an error.
- **T1-T5 Tests.** No test plan existed. Added, including regression tests
  for the two decode errors hit during verification, both of which
  returned clean-looking wrong answers.
- **D1 Document.** Three superseded findings contradicted their
  replacements: the formula double-count claim, collateral as "the entry
  cost that matters", and `active_miners` as unusable. An implementer could
  have read either half. Rewritten.
- **D2 Document.** Stale references to `active_miners` in the Stage A field
  list, the demo row spec, and the NOT-in-scope bullet, which wrongly
  excluded concentration rather than excluding the TaoStats route to it.
- **D3 Document.** "Three stages" described five.

Security pass rationale: the change adds a page to a LAN-served directory
and three new tools to the Hermes MCP surface. Neither adds a credential
and both are read-only, so the exposure delta is small, but it is not zero
and the review is cheap.

NO UNRESOLVED DECISIONS
