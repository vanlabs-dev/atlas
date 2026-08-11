## Context

Atlas holds two halves of the mining question and joins neither. `fleet/`
tracks 104 subnet clones with a `(netuid,epoch)` code index and sha-gated
metrics. `livedata/` polls TaoSwap and finney, tracks the spec-440/443
emission gate, and watches root-settable chain parameters. Nothing asks
whether a new independent miner would earn anything on a given subnet.

The full brainstorm, the on-device verification of every input, and an
applied plan review are in `docs/design/2026-08-07-mining-triage-design.md`.
That document is the source of truth for scope, cut thresholds, schema,
failure paths, and the test plan. This file records only the technical
decisions and their alternatives.

Verification on 2026-08-07 established the facts the design rests on. The
emission gate is disabled on 43 of 129 subnets. `MinerBurned` is not an
owner-set knob but a measured per-tempo proportion of miner incentive that
landed on owner or owner-associated immune hotkeys and was burned or
recycled; it both withholds from the miner leg at distribution and penalises
the subnet's price share afterwards. TaoSwap's `emission_miner_burn` matches
chain `MinerBurned` on 127 of 128 subnets. `SubnetworkN` is 256 nearly
everywhere while only 3 to 15 UIDs earn anything, with the top ten taking
substantially all of it. Miner registration collateral exists in the runtime
since spec 435 and is unset across every subnet today.

Constraints: PRD §7 bars running a miner, holding wallet keys, and
submitting any transaction. The device is a Pi 5 with no GPU and no
passwordless sudo. Code reaches it by `git pull`. Every provider call is
expected to be validated, audited, and quota-accounted.

## Goals / Non-Goals

**Goals:**

- Rank subnets by what a new independent miner could earn, with every
  exclusion carrying its reason and every feasibility claim carrying a
  `file:line`.
- Consume zero TaoStats quota. All inputs keyless.
- Add no systemd unit, no network port, no credential, no provider
  contract.
- Answer the same question on a LAN board and through Hermes, from one
  collector.
- Fail closed: never present a net income figure assembled from an
  incomplete read.

**Non-Goals:**

- Running, deploying, or operating a miner. Different hardware, different
  project, and barred by PRD §7.
- Wallet keys, registration, signing, or any transaction.
- Backtesting the screen against realised outcomes. The `signal_outcomes`
  pattern exists for this later; it is not needed to produce a first list.
- Scraping GPU rental prices. A hand-set config constant per band ranks
  adequately.
- Automated tuning of the cut thresholds.
- A fourth MCP server.

## Decisions

**All network access stays in `livedata/`, and `fleet/` imports it.**
The collector needs a TaoSwap panel and roughly 260 chain values per pass.
Putting `state_getStorage` calls in `fleet/atlas_fleet_mining.py` would have
duplicated the endpoint list, retry policy, timeouts, and an xxh64
implementation, and those chain reads would have bypassed the live-data
`audit` table, leaving no single record of what Atlas asked the chain.
Instead `livedata/atlas_live.py` gains a `twox128` helper and
`read_subnet_maps()`, and the collector imports them, the way `fleet`
already reuses repotrack's `collect_range`.
*Alternative rejected:* a new livedata poll command writing to
`var/livedata/`, with fleet joining across two stores. Cleaner separation,
but it needs a second scheduled unit and lets the fleet pass read from a
poll that may not have run.

**Batched reads at one finalized block, via `state_queryStorageAt`.**
Roughly 260 sequential POSTs would take one to two minutes and, worse, would
read different subnets at different blocks, smearing a moving chain across
one reported snapshot. The batched call is a standard Substrate RPC, not a
custom mechanism, and it makes each pass internally consistent by
construction. `state_getKeysPaged` still enumerates each map prefix once to
discover live netuids.
*Alternative rejected:* sequential `state_getStorage`, which is exactly the
already-proven gate-poll path, but pays both costs for no benefit at this
key count.

**Storage keys are derived, then self-tested against the pinned gate keys.**
Pinning a key per netuid per item is unmaintainable at 129 subnets and four
items. Derivation needs `twox128`, which needs xxh64, which is not installed
on the device and must be implemented. The self-test makes that safe and
free: the three gate keys in `livedata/config.json` were verified against
live Finney on 2026-07-28, so a derivation that reproduces all three is
correct. A failed self-test blocks every derived read, because a wrong
prefix returns empty results indistinguishable from an empty map.
*Alternative rejected:* adding an xxhash dependency to the Pi, which
introduces a package to install and pin for forty lines of pure Python.

**Map key layout is observed, not assumed.** These netuid maps use the
Identity hasher, so the key tail is the raw two-byte netuid with no twox64
concat. That was established by enumerating each prefix and observing
two-byte tails, after an assumed twox64-concat layout returned null for
every netuid and looked exactly like an empty map. Enumeration stays in the
implementation as the way layout is confirmed, and a control map known to be
populated distinguishes "empty" from "wrong prefix".

**Competition comes from the incentive vector, not a headcount.** Dividing
subnet emission by `active_miners` or by `SubnetworkN` would have overstated
per-miner income by more than an order of magnitude, because registered UIDs
are 256 while earners are single digits and reward is winner-take-most. The
screen records earner count, top-1 and top-10 share, and expresses a new
entrant's prospects as a displacement rank.

**The base quantity is `alpha_out_emission`, not `alpha_in_emission`.**
Found during implementation on 2026-08-07. `alpha_out_emission` is the alpha
distributed to participants per block, annotated in `run_coinbase.rs` as
"Total alpha emission per block remaining" and the quantity the root
proportion and validator split are applied to. `alpha_in_emission` is the
alpha-reserve injection, the TAO side, and it is capped, with the remainder
surfacing as `excess_tao_emission`; for netuid 1 it happens to equal
`emission_value / price` exactly, and for netuids 5, 8 and 64 it does not.
Ranking on it would rank pool inflow rather than miner income.

The consequence reshapes the ranking. `alpha_out_emission` is 1.0 on all 127
non-root subnets, so miner-accessible quantity is identical everywhere and
carries no ranking information. What separates subnets is the TAO value of
that alpha and how few people share it: `price_tao x (1 - burn)` against
concentration. Emission quantity is recorded as context, never as a
differentiator.
*Alternative rejected:* ranking on `alpha_in_emission` as originally
designed, which is the exact class of error the verification effort existed
to prevent.

**The burn factor is applied exactly once, to the miner leg.** The share
penalty is already inside the observed emission; the withholding is a
separate deduction at distribution. Applying it to both, or to neither, is
wrong, and the correct placement is only visible from `run_coinbase.rs`.
The protocol miner share is sourced with a recorded citation rather than
hardcoded, and the screen refuses to compute without one.

**A gate-disabled subnet is cut for unbacked alpha, not for absent payment.**
`get_subnet_block_emissions` keeps disabled subnets in the map "so the normal
alpha_out path still runs", and the panel confirms alpha_out is 1.0 on all 43
disabled subnets. They pay their miners alpha; they lose the TAO inflow
backing it, so the price decays and TAO income tends to zero. The cut stands,
the stated reason is corrected.

**Collateral is watched, not modelled.** It is dormant across every subnet,
so a cost model for it would compute zero at some expense. It is settable up
to 95 percent of the registration price and recoverable only by earning
emission, so a subnet enabling it changes that subnet's entry risk
completely. That belongs in the chain-parameter watch as a transition event.
Because the item is netuid-keyed and the existing watch handles scalar
pinned-key items, this is a new requirement on live-data rather than a
config addition.

**Three tools on the existing `atlas-fleet` server.** A fourth stdio server
adds a Hermes registration, a process to supervise, and a second store
handle for no benefit.

**Retention at 90 days, reusing the `signal_prices` prune.** `mine_econ` is
a per-pass time series at roughly 516 rows a day, unbounded at about 188k
rows a year. Backtesting is out of scope, so long history buys nothing that
is currently planned. `mine_feasibility` is keyed by scanned commit and does
not grow with time.

## Risks / Trade-offs

- **A wrong decode returns a plausible number rather than an error.** Both
  decode errors hit during verification did exactly this: a fixed-point
  value read at the wrong scale gave 0.0 for every subnet, and a wrong key
  layout gave an empty map. → Regression tests for both, the pinned-key
  self-test, and a populated control map asserted in the same pass.

- **The screen could imply a subnet is winnable when four incumbents have
  held it for months.** Concentration is a snapshot and says nothing about
  churn. → Present displacement rank rather than average income, and treat
  incumbent churn over time as a later refinement once history accrues.
  Until then the board states what it knows and not what it does not.

- **`emission_miner_burn` is 0-100, not a fraction, and the panel's own
  postprocessor carries a warning about it.** A factor-of-100 slip would put
  a plausible wrong figure on the board. → Unit suffix on every percentage
  column and a unit regression test.

- **The whole economics leg depends on one provider endpoint that was in
  outage the day before this was designed.** → Panel failure leaves prior
  rows intact and renders last-known with its age shown; the pass does not
  fail.

- **Importing livedata from fleet introduces a dependency direction that
  does not exist today.** → It mirrors the existing repotrack reuse, and the
  alternative is duplicating provider handling in a second subsystem.

- **The screen could be built and then never acted on.** → The budget band
  decision is dated: if it is not picked within two weeks of the first
  board, the honest conclusion is that mining is not being pursued and the
  screen should stop being maintained.

## Migration Plan

Additive throughout. Three new tables created on first run in the existing
`var/fleet/fleet.db`; no existing table, tool, or unit changes. Deploy is
`git pull` on the Pi, after which the next 6h fleet pass runs the screen
inline and renders the second board page into the directory
`atlas-dashboard.service` already serves. No sudo step, no unit install, no
port change.

Rollback is a config flag that makes the screen inert, matching the
gate-signal kill-switch pattern: the pass skips the screen, the existing
board is untouched, and the tables remain readable. Removing the change
entirely is a `git revert` plus dropping three tables.

## Open Questions

- Registration cost units. The panel reports a median of 0.006, low enough
  to question whether the field is TAO or alpha denominated. Confirm against
  a chain read of the same subnet's `Burn` before the value is presented.
  Low stakes now that entry is known to be cheap and rent dominates.
- The one subnet of 128 where chain `MinerBurned` and the panel disagree.
  Identify it and determine whether it is tempo skew or a value the screen
  should distrust.
- How to estimate what reaching a displacement rank actually takes. The
  candidate is pairing concentration with incentive-vector churn over time,
  which needs history the store does not yet have.

  **Partially informed 2026-08-11, and without waiting for history.**
  `ImmunityPeriod` is a per-subnet chain hyperparameter readable on any
  pass. Measured across 30 gate-enabled subnets it spans **100 to 65,535
  blocks (0.01 to 9.1 days), a 655x spread**: netuid 76 gives roughly eight
  minutes of protection, netuids 50 and 18 give 9.1 days. Two consequences.
  It bounds the runway an entrant has before becoming prunable, which is
  the entry-risk half of this question. And it explains the exception
  profile recorded above: long immunity stops dead slots recycling, so
  netuid 50 shows 235 of 248 slots earning while short-immunity subnets
  concentrate. It does **not** answer what out-competing rank N takes, so
  churn history is still required for that half.

  Related mechanic, from `pallets/subtensor/src/subnets/registration.rs`
  at release-444: registering into a subnet already at `max_allowed_uids`
  is not blocked, it evicts a UID (line 27). `get_neuron_to_prune`
  (line 285) selects lowest emission, tie-broken by oldest registration
  block, then lowest uid, skipping owner-immortal hotkeys and respecting a
  `MinNonImmuneUids` floor. Since most registered UIDs sit at exactly zero
  emission, the operative rule among them is oldest-first, and an entrant
  earning anything at all leaves the eviction pool immediately. A large
  idle UID count is therefore an eviction queue, not a wall of competitors.

  Measurements in `triage/hyperparams.json`; field-level notes in
  `docs/emission-metrics.md` section 5.1. Whether immunity belongs on the
  board or in the chain-parameter watch is not decided here.
- The hardware and capital budget band, deliberately deferred to the data.
  Dated: pick within two weeks of the first board render.
- Holding period for amortising registration burn. Needs a stated
  assumption, probably 90 days, flagged wherever it is used.
