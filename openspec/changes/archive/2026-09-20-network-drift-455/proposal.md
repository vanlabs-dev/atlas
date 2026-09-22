# Network Drift 455

## Why

Two gaps, one change. The first is the scheduled one: Atlas is grounded at
subtensor spec 452 and Finney has run 453, 454 and 455 since. The second is
not scheduled and is the reason this change is being drafted now: on
**2026-09-09 at 12:16:48 UTC, block 9029889**, a root-origin call enabled
pool-side emission for **49 subnets in one block**, and Atlas recorded the
whole thing without telling anyone.

### The pool-side emission switch is a root knob nobody was watching

`SubnetEmissionEnabled` is a per-netuid `bool` in `SubtensorModule`, written
only by `AdminUtils::sudo_set_subnet_emission_enabled` (call index 94,
`ensure_root(origin)`). Per
`pallets/subtensor/src/coinbase/subnet_emissions.rs`, a disabled subnet keeps
its `alpha_out` path but its TAO-side share is zeroed and renormalised away
across the enabled subnets. It is a **separate mechanism from the
emission-gate bar**: the bar is a continuous Hill gate over demand share, this
is a binary root switch over the pool-side injection.

Verified against live Finney and the archive node at the step block:

- At block 9029888, 49 subnets read false. At 9029889, all 128 read true.
  The 49 are exactly the set the TaoSwap panel had been reporting as
  disabled, so the provider field is this chain item and Atlas's recorded
  data was correct throughout.
- The next block's coinbase acted on it: **18 subnets went from exactly zero
  `SubnetTaoInEmission` to nonzero** and have stayed there. SN8 went from `0`,
  held for at least six days, to `3,752,881` rao per block, with its price and
  demand share unmoved. Incumbents were diluted: SN1 fell from `85,587` to
  `77,450` rao per block, −9.5%. Earners went 70 to 88.
- The other 31 of the 49 sit at 100% miner burn, so their demand share is zero
  and the flip changed nothing for them.
- SN29 and SN36 were switched back off the same evening, at roughly 20:07 and
  21:08 UTC. They are the only two disabled today.

Ruled out at the step block, each checked directly: runtime upgrade (spec 455
both sides), every gate parameter (theta identical at `0.0078405453`, rank, q
and h unchanged), root weight rotation (95 destinations, same top, unchanged),
`SubtokenEnabled`, `MinerBurned`, `Tempo`, `FirstEmissionBlockNumber`.

Three Atlas failures follow from it:

- **Nothing paged.** The chain-parameter watch covers the bar knobs,
  `RootWeightSettingEnabled`, `RootWeightsCap` and `CollateralLockShare`. A
  root action that moved the pool-side emission of 18 subnets is not in the
  watch set, so it produced no event and no alert.
- **The mining screen moved and said nothing.** `mine_econ.gate_state` reads
  this flag and `gate-disabled` is the first rung of the cut ladder.
  Recomputing the ladder over the same rows with the pre-flip flags:
  **56 ranked becomes 65**. Nine subnets (9, 20, 34, 35, 43, 48, 83, 90, 92)
  are ranked today only because of the flip. The rung's own text calls it the
  "emission gate", which conflates a root switch with the bar.
- **The corpus has no coverage of it at all.** Zero hits for
  `SubnetEmissionEnabled` or the pool-side switch across
  `knowledge/corpus/` and `docs/emission-metrics.md`. The model is documented
  as demand share into a Hill gate, full stop. Asked why a subnet with real
  demand earns nothing, Atlas has no grounding to answer from. The flag is not
  new drift: it landed 2026-05-12 (PR #2657), before the gate itself, and has
  simply never been covered.

`knowledge/corpus/SOURCES.md` currently states "No new root-settable knob
appeared, so the chain-parameter watch needs no new item." That sentence is
true about 453 to 455 and false about the watch set, and it is what let this
sit.

### The scheduled corpus drift

Detection worked for the releases themselves: `spec_upgrades` recorded 453
(block 8,988,192, 2026-09-03), 454 (8,996,901, 2026-09-04) and 455
(9,018,443, 2026-09-07) and the `chain-runtime-upgrade` class paged each.
Grounding did not follow. Nothing the corpus states was made false, but per
`SOURCES.md` three claims are incomplete and two areas have no coverage:

- `claim_root` redemption is described as pro-rata across every holding.
  Spec 454 narrowed it to root-relevant hotkeys, with admission at
  `root-relevant hotkeys + actual basket rows <= 256`, and a holding that
  rounds to a zero take now leaves the claim unsettled rather than charging a
  fee for nothing.
- The basket escrow is described without spec 453's rejection of user stake
  transfers into it (`CannotUseSystemAccount`).
- Subnet burn cost is described without the registration queue. Spec 453
  moved pricing and the rate-limit update to queue time for deferred
  registrations and reserves the hotkey for the paying coldkey.
- **Proxy call filters** have no coverage (453 closed nested-proxy filter
  laundering, 454 re-allowed `transfer_stake` through `ContractCallFilter`,
  455 denies EVM, Contracts and Crowdloan to `NonTransfer` and `NonFungible`),
  and neither does the **crowdloan pallet**.

### One share-universe refinement found while validating the bar

The bar itself is read, not computed: theta is `EmissionGateBar` from chain
storage on a pinned key that re-derives exactly as
`twox128("SubtensorModule") ++ twox128(item)`. What Atlas computes is the
demand share it compares against theta, and that reproduces the chain's own
selection rule closely: at block 9041640 the 32nd-largest share was
`0.0086453632` against a chain theta of `0.0086161991`, **+0.34%**, with
exactly 32 subnets at or above the bar. Dropping the miner-burn factor gives
−15.54% and 27 above, so the coupling is load-bearing and correct.

The `live-data` requirement names the normalization universe "the chain's
emit-to universe". The chain's actual `get_subnets_to_emit_to` filters on
three conditions: a set `FirstEmissionBlockNumber`, `SubtokenEnabled` true,
and network registration allowed. Atlas normalises over every non-root priced
panel subnet, which today includes SN59, SN76 and SN86, none of which the
chain emits to. Their shares are small enough to sit inside the +0.34%
residual, so this is a naming and precision defect rather than an observed
error, but the requirement should describe the filter it actually implements
and say why the difference is tolerable.

## What Changes

- **`SubnetEmissionEnabled` joins the netuid-keyed chain-parameter watch** as
  a second item under the existing per-subnet watch requirement, read in the
  same batched pass at the gate poll's finalized block on a derived,
  self-tested key. First observation seeds every subnet silently; a later
  transition records an event carrying the netuid, both values and the
  reference block.
- **A same-block batch of netuid-keyed transitions pages once, not once per
  netuid.** The `chain-parameter-change` class stays instant and keeps its no
  cooldown rule, but transitions of one netuid-keyed item sharing one
  reference block collapse into a single alert stating the item, the
  direction, the count and the netuid list. The 2026-09-09 event would have
  been one page naming 49 subnets. Every collapsed event is still recorded
  individually in the delivery ledger, so nothing is dropped to achieve the
  collapse.
- **The corpus gains the pool-side emission switch** as a distinct mechanism:
  root-settable per netuid, zeroes the TAO-side injection while `alpha_out`
  continues, redistributes to enabled subnets, and is not the emission-gate
  bar. With it, the negative-claim rule that a subnet with positive demand
  share necessarily earns TAO, which the current text implies.
- **Corpus re-sync 452 to 455**, verified against the merged subtensor code at
  tag v455 and live Finney reads at one finalized block, using the method of
  the 2026-07-28, 2026-08-06 and 2026-08-31 re-syncs: `claim_root` admission,
  the basket-escrow transfer rejection, the registration queue, proxy call
  filters, and the crowdloan pallet.
- **Benchmark battery extension.** Two adversarial cases pin the new
  grounding: a question about a subnet with real demand and zero earnings must
  name the pool-side switch and not the bar; a `claim_root` question must
  state the spec-454 admission rule. Re-run and re-accept under the existing
  threshold sheet.
- **The mining cut ladder's first rung is renamed and re-worded** to name the
  pool-side emission switch rather than the "emission gate", so the board
  never presents a root switch as the bar. The rung's position and semantics
  do not change.
- **The demand-share requirement states the chain's three emit-to filters**
  and records that Atlas normalises over the panel's non-root set instead,
  with the measured residual and why the difference is accepted.
- **Alert vocabulary.** The `chain-parameter-change` `governs` map and the
  voice gloss map gain the pool-side emission switch, so a paged transition
  and a chat answer use a term the lexicon can gloss.
- **Documentation.** README status, `docs/decisions.md` (the 2026-09-09 event
  with its evidence, and the acceptance entry), `knowledge/corpus/SOURCES.md`
  coverage date and the correction of its "no new watch item" sentence.

Not breaking. One additive watch item, one alert-rendering rule, corpus
content, and one rung rename. The model stays `grok-4.5`; a model swap would
invalidate the benchmark and is its own change.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `live-data`: the netuid-keyed chain-parameter watch set gains
  `SubnetEmissionEnabled`, the per-subnet root switch over pool-side TAO
  injection; the demand-share requirement states the chain's actual emit-to
  filters and the accepted deviation from them.
- `telegram-integration`: the instant-tier `chain-parameter-change` class
  collapses a same-block batch of netuid-keyed transitions of one item into a
  single alert, while still ledgering each event.
- `mining-triage`: the first cut rung names the pool-side emission switch and
  distinguishes it from the emission-gate bar.

The corpus re-sync, the new mechanism section and the battery extension
exercise existing `knowledge-base` requirements (supersession handling,
benchmark gate) without changing them.

## Impact

- **Code:** `livedata/atlas_live.py` (watch item registration and decode for a
  netuid-keyed `bool`), `livedata/config.json` (`chain_params` items),
  `telegram/atlas_telegram.py` (batch collapsing in the chain-parameter
  class), `fleet/atlas_fleet_mining.py` (rung name and detail text),
  `livedata/tests`, `telegram/tests`, `fleet/tests`.
- **Content:** `knowledge/corpus/ground-truth.md`, `fact-patterns.md`,
  `negative-claim-rules.md`, `SOURCES.md`, `hashes.json`;
  `knowledge/benchmark` battery and expected-evidence markers.
- **Config:** `telegram/config.json`
  (`classes.chain-parameter-change.governs`, `voice.gloss`).
- **Docs:** `README.md`, `docs/decisions.md`, `docs/emission-metrics.md`.
- **Device:** corpus ingest, activation and benchmark run on the Pi; one
  `git pull`; no new service, credential, port or provider. The watch item
  rides the existing batched read at the gate-poll block, so it adds no
  provider call and no TaoStats quota.
- **Downstream to check:** the mining board's ranked count will move again if
  the flag moves; `shinogi/atlas_shinogi.py` reads the mining figures and the
  board ordering, so a rung rename must not leak operator text onto the public
  page.
