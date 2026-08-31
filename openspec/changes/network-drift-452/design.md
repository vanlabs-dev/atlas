## Context

See proposal.md, Why. The corpus is a verbatim snapshot with recorded
provenance and hashes, ingested into units and activated behind a benchmark
gate. Re-syncs in July and August rewrote superseded claims rather than
marking them, verified each claim against the merged subtensor code at the
release tag and against live Finney reads, and left
`supersession-markers.json` empty. The chain-parameter watch already reads
independent items at the gate poll's finalized block, self-tests derived
keys, and handles netuid-keyed maps (`CollateralLockShare`) with a verified
hasher. The rank cross-check has a configurable tolerance that ships at zero.

Constraints: no new credential, provider, port, or service; tests off-device
under `unittest`; the Pi is the acceptance environment; the model stays
`grok-4.5`.

## Goals / Non-Goals

**Goals:**

- Every corpus claim about takeover gating, root curation, and beta pricing
  is true at spec 452 and dated.
- The benchmark proves the three corrected claims are what the model says.
- The one new root-settable economic knob is watched.
- The cross-check stops alarming on a boundary condition and still catches a
  real divergence.

**Non-Goals:**

- Modelling beta baskets, fund NAVs, or the basket index in livedata. The
  corpus explains the convention; no tool computes it.
- Watching every new storage item (`LiquidAlphaConsensusMode`,
  `TotalVotingPower`, `ConsensusByMechanism`). None is a root-settable
  economic knob in the sense the watch defines; they are mentioned in the
  corpus and left unwatched.
- Changing hysteresis, cooldown, or any alerting behaviour. That belongs to
  the pulse-briefing change.
- A model swap.

## Decisions

**D1. Verify against tag v452 and one finalized block, then rewrite.** Same
method as the two prior re-syncs. Each rewritten claim cites the file that
carries it (`pallets/subtensor/src/staking/lock.rs` for the 18% gate,
`pallets/admin-utils/src/lib.rs` and the v449 migration for the cap and the
switch, `pallets/subtensor/src/staking/beta_pricing.rs` for baselines and
the index) and the live value read the same day. Alternative: mark the stale
lines with supersession markers and leave the text. Rejected as before: the
old text is not merely qualified, it instructs the model to deny a live
mechanism, and a marker would leave the instruction in the retrieval path.

**D2. Tolerance one, not recalculation-block detection.** The exact
alternative is to evaluate the invariant only on polls where theta changed
since the previous observation. That requires the poll to know it landed on
a recalculation boundary, which the chain does not expose directly and a
theta comparison only approximates (theta can recalculate to the same value).
Tolerance one keeps the check simple, removes the boundary artefact, and
still fires on a divergence of two, which is the smallest divergence that
cannot be explained by the boundary subnet. The requirement states the
reason so the tolerance is not "loosened" back to zero later.

**D3. `RootWeightsCap` at the root entry, through the existing netuid-keyed
path.** The storage is `StorageMap<Blake2_128Concat, NetUid, u16>` with a
`ValueQuery` default. The key is derived as pallet-prefix plus item-prefix
plus `blake2_128(netuid) ++ netuid`, using the derivation the mining-triage
change already verifies against observed key tails. Which entry the runtime
consults is confirmed from the `set_root_weights` path at v452 before the
entry is pinned (task 1.4); the proposal assumes the root entry by analogy
with `RootClaimableThreshold`. Alternative: enumerate the whole map as the
collateral watch does. Rejected: one entry is consulted, and 128 inert rows
per hour would be noise in `chain_params`.

**D4. Default value comes from the runtime, not the release note.** The v441
release note was wrong about `EmissionBarRank`'s default. The `u16` default
for `RootWeightsCap` is read from `DefaultRootWeightsCap` in `lib.rs` at
v452 and recorded with its source, then cross-checked against the live read
(which is expected to be explicit after the v449 migration).

**D5. Battery cases test the correction, not the keyword.** Each new case is
phrased to tempt the stale answer ("is it still 10% of alpha?", "root
dividends just pile up, right?", "what's a beta worth right now?") and the
expected-evidence markers require the dated corrected fact or a refusal. A
case that hands the model the right answer in the question would pass
against the stale corpus and prove nothing, which is the MV-VP-1 lesson from
the voice change.

**D6. Glosses are added where the words can appear.** `RootWeightsCap`
enters the `governs` map so a transition page explains itself.
Beta, basket, basket index, and display price enter the voice gloss map so a
chat answer built from the new corpus section stays inside the lexicon rule.

## Risks / Trade-offs

- [The v452 clone on the Pi is the tracked clone; a verification step that
  checks out a tag would disturb it] → Read with `git show v452:<path>`
  and `git diff v443..v452`; never check out. The clone stays at the tracked
  head.
- [A corpus rewrite drifts the benchmark's older expected markers] → Re-run
  the whole battery, not only the new cases; the existing gate (0.9
  correct-with-evidence, zero fabrications) decides acceptance.
- [The root entry assumption for `RootWeightsCap` is wrong] → Task 1.4
  verifies the consulted entry in code before the key is pinned; if the cap
  is per-subnet in practice, the item moves to the netuid-keyed enumeration
  path instead.
- [Tolerance one hides a persistent off-by-one that is real] → The count is
  still persisted every pass; a weekly read of the distribution (task 6.3
  records the current one: 31 on 32 polls, 32 on 16) would show a real
  one-sided drift. The pulse-briefing change surfaces this line.
- [`stake_into_basket` gating changed silently] → Verified at v452 by
  reading the dispatchable, stated as found, with the block of the read.

## Migration Plan

1. Off-device: corpus edits, battery cases, watch item, tolerance, tests
   green (`livedata`, `knowledge`, `telegram`).
2. Push; `git pull` on the Pi.
3. Ingest and activate the corpus; run the battery; record the run id and
   verdict in the decision log. Rollback: re-activate the previous ingest run.
4. Watch item appears on the next hourly pass; first observation seeds
   silently. Rollback: remove the item from `chain_params.items`.
5. Tolerance takes effect on the next pass; the health event stream goes
   quiet unless a real divergence exists. Rollback: set it back to zero.

## Open Questions

- Whether spec 448's `TotalAlphaStaked` per netuid should later become a
  polled quantity for the pulse briefing. It is not needed for this change
  and does not affect its specs.
