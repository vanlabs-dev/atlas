## Context

Atlas's gate signal shipped 2026-07-28 against spec 440, where the emission
gate bar was a q-mass quantile: sort demand shares descending, accumulate
until the running total crosses q, take the crossing share as theta. Spec 441
(PR #3014) added a second selection mode. From
`pallets/subtensor/src/coinbase/subnet_emissions.rs` at tag v443,
`maybe_update_emission_gate_bar` now branches on `EmissionBarRank`:

- N > 0 (rank mode): theta is the Nth-largest *positive* demand share, so
  exactly the top N subnets sit at or above the gate midpoint. If fewer than
  N subnets have demand, theta falls back to the smallest positive share and
  the gate stops biting.
- N = 0 (q-mass mode): the original spec-440 behaviour.

`EmissionBarRank` is `StorageValue<_, u16, ValueQuery, DefaultEmissionBarRank>`
with a default of **32** (`pallets/subtensor/src/lib.rs`), chosen because
q = 0.75 was crossing at about rank 28 on then-current demand — the upgrade
was deliberately tuned not to shift the emission curve. Chain reads on
2026-08-06 confirm the live state: `EmissionBarRank` unset (default 32
applies, rank mode active), `EmissionBarQuantile` explicit at 0.75 but inert,
`EmissionGateExponent` unset (default 3).

Note for anyone re-deriving this: the v441 release notes state the rank
default is 64. The shipped code says 32. The code is authoritative.

Root Reborn landed in the same runtime. `RootWeightSettingEnabled` is
`StorageValue<_, bool, ValueQuery>` — default false, and unset on chain, so
basket curation is off and every fund runs the null strategy. The storage
comment is explicit that this is a deliberate staged launch. The flip will
come via `AdminUtils::sudo_set_root_weight_setting_enabled` or a migration in
a later runtime.

### What the deployed store already shows

The Pi's `gate_sides` table currently reads **32 above / 96 below**. That is
not a coincidence — it is N. Atlas's independently computed, panel-derived
demand shares, compared against the chain-read theta, reproduce the chain's
rank-32 pin exactly. Rank mode therefore hands Atlas a correctness oracle it
was not built to use, and this design takes it (see Decisions).

The migration is legible in the same store. Mainnet took spec 441 at
2026-08-03T19:18:36; `migrate_reset_emission_gate_bar` cleared the stale
quantile bar. Atlas's theta series across that window:

| observed | theta |
|---|---|
| 19:01 | 0.008884 |
| 20:07 | 0.007598 |
| 21:06 | 0.007321 |

A 14.5% single-poll drop, the largest move in the series. At 21:06, four
subnets — 49, 67, 79, 81 — recorded `rose-above` in one pass, with shares of
0.0086 to 0.0094 against a theta of 0.0073. Their demand did not rise. The
bar came down onto them. And 28 (the sides seeded on 07-28 under q-mass) plus
those 4 is exactly the 32 sitting above today.

Two consequences follow, and both are defects in the shipped signal rather
than hypotheses:

1. **A bar-parameter change produces exactly |M − N| simultaneous crossings.**
   The per-netuid cooldown offers no protection because every event is a
   different netuid. This one was small (4) only because the chain tuned the
   default to be near-neutral. A governance move from 32 to 64 would page 32
   alerts in one pass.
2. **Those alerts were affirmatively misleading.** Four subnets were reported
   as having crossed on their own demand when the cause was the chain
   changing its bar selection rule. This is a correctness problem in what
   Atlas told the operator, not merely noise.

### Existing machinery this should reuse rather than duplicate

`run_gate_pass` already handles a mass re-classification correctly for one
case: a gate-inactive to gate-active transition does `DELETE FROM gate_sides`
and re-seeds silently, emitting no events for the transition pass. A
bar-parameter change is the same situation and deserves the same treatment.

`poll_gate_state` already computes a `params_changed` boolean by comparing q
and h against the previous observation — but it is only returned in the pass
summary. It is never persisted and never paged, so the existing spec's
"parameter changes are visible facts" is satisfied only in the weakest sense.
Adding a separate durable transition path for rank alone would leave two
parallel change-detection mechanisms with inconsistent coverage.

### Constraints

The gate signal is deployed and delivering, so schema and behaviour changes
must be additive and must not disturb crossing detection. The corpus is a
verbatim hash-verified snapshot of files owned by another repo, so corpus
edits are upstream-first by construction.

## Goals / Non-Goals

**Goals:**

- Every `gate_state` observation states which mechanism produced its theta.
- A bar re-pricing is reported once, as a bar re-pricing, instead of as a
  burst of per-subnet demand events.
- Atlas notices when a root-settable economic knob moves — every gate knob,
  plus the Root Reborn curation switch — with the fail-closed discipline the
  gate poll already applies.
- The rank invariant is used as a standing check on the share pipeline.
- The corpus answers gate and root-dividend questions correctly at spec 443.

**Non-Goals:**

- Recomputing theta locally. Atlas reads the chain's theta and always will.
  Reading rank is for attribution, change detection, and the invariant check
  — not a reimplementation of `maybe_update_emission_gate_bar`.
- Modelling beta-basket internals (NAV, shares, holdings). Root Reborn enters
  the corpus as knowledge and enters livedata only as the one switch that
  gates it.
- Re-tuning gate hysteresis. The SN9 flap belongs to the ~2026-08-11
  calibration read; this change only supplies it better evidence.
- A generic chain-storage-watch framework. The watch set is a short config
  list, not a plugin system.

## Decisions

**The rank invariant becomes a standing correctness check.** In rank mode,
`count(above) == N` holds by construction. Atlas can therefore validate its
panel data, its normalization universe, and its theta read together against
the chain's own selection rule, every pass, for the cost of a COUNT. Each
rank-mode pass persists the above-bar count beside the effective N and raises
a health event on divergence beyond a tolerance. It never suppresses events
or discards a pass — a divergence means Atlas and the chain disagree about
demand, which is information, not an error. Alternative considered: leave it
as a manual spot-check. Rejected — it is the only cheap independent check on
a pipeline whose inputs (panel prices, miner burn, universe membership) can
drift silently, and it is free.

**A bar-parameter transition re-seeds sides silently.** Reusing the existing
gate-reactivation path: on a pass where the effective N, q, or h changed, all
sides re-seed from current shares and theta, and no crossing events are
recorded. The single `chain-parameter-change` alert carries the story, and it
says explicitly that the bar was re-priced and per-subnet pages were withheld
— otherwise the silence looks like a gap. Alternatives considered: a burst
damper (a cap on events per pass) — rejected, it would drop real information
arbitrarily and still misattribute what it did send; or paging all |M − N|
crossings — rejected, that is what just happened on 08-03 and it misinformed.

**Crossings record the previous observation's theta.** A rank-pinned bar is
itself a demand share, so it moves on its own. Without the prior theta, a
crossing cannot distinguish "my share moved" from "the bar moved onto me".
Storing one extra float per event makes the attribution computable at render
time and gives the 08-11 calibration read the evidence it needs. Checked
against the live data: SN9's three crossings were genuine share movement
(0.0035 → 0.0192 → 0.0065 against a theta drifting only 0.0072 → 0.0079), so
the SN9 flap is share-side volatility, not bar movement — worth knowing
before tuning hysteresis for the wrong cause.

**One transition mechanism covering all four knobs.** The watch set is rank,
q, h, and `RootWeightSettingEnabled`. Paging rank while leaving h unpaged
would be arbitrary: h changes gate sharpness for every subnet, and q governs
the bar whenever rank is 0. This also supersedes the ephemeral
`params_changed` boolean rather than running beside it.

**Bar parameters are read once and flow from the gate poll into the watch.**
An earlier draft had the watch re-read rank independently, accepting a double
read for separation of concerns. That was wrong: it creates two records of
one fact and a second decode path that can disagree with the first. Instead
the gate poll hands its decoded N/q/h to the watch, and the watch
independently reads only what the gate poll does not touch — today just
`RootWeightSettingEnabled`. One read per item, one history.

**The watch is not gated by the emission-gate kill-switch.** `run_gate_pass`
returns early when `gate_signal.enabled` is false. If the watch lived wholly
inside that pass, rolling back the gate signal would silently stop watching
the Root Reborn curation switch — a parameter with nothing to do with the
gate, and the one thing you would most want to keep seeing during a rollback.
So the watch obtains its own finalized head when the gate pass is not
running, and piggybacks the gate poll's block when it is. Bar-parameter
history naturally pauses while the gate poll is off, since that is where
those values come from; that is honest rather than silent.

**Per-item failure isolation, but only for independently read items.** The
gate poll persists nothing if any of its reads fail, because theta, q, h, and
rank are one coherent state. Independently read items are unrelated facts, so
one unreadable key must not blind the others.

**A provenance change is not a transition.** Setting rank explicitly to 32 —
the value it already had by default — moves provenance from `assumed-default`
to `explicit` at an unchanged value. Worth recording (it is now pinned rather
than inherited), wrong to page as a value change.

**A per-item codec, declared in config.** Rank is `u16` (2 bytes LE) and the
root switch is `bool` (1 byte); feeding either to `decode_u64f64` fails its
16-byte length check, so the failure is loud — but only if the codec is
chosen per item rather than assumed. The boolean decoder additionally rejects
a correct-length payload that is neither encoded true nor encoded false, a
case length checking alone would pass. Alternative considered: infer the
codec from payload length. Rejected — unambiguous today, silently wrong for
the first item that shares a length.

**Storage keys are pinned, and the derivation is reproducible.** Derived as
`twox128("SubtensorModule") ++ twox128(<item>)`, validated by reproducing
Atlas's existing pinned `EmissionGateBar` key byte-for-byte before trusting
the new ones:

- `EmissionBarRank`
  `0x658faa385070e074c85bf6b568cf0555d33bd686290d014475513443305882be`
- `RootWeightSettingEnabled`
  `0x658faa385070e074c85bf6b568cf055543f3dc4dfa03eb004921d663110b49b0`

Both read null against live Finney during design, matching the expected
unset-with-default state.

**Transitions need no hysteresis.** A watched parameter is a discrete value
written by an extrinsic; it does not flap. A confirmation window would only
delay a page that is by definition material.

**A sixth Telegram class, with no cooldown.** A knob flip and a runtime swap
differ in cause, urgency, and body, and a separate class keeps the watermark
and failure isolation independent. No cooldown: a root-settable knob cannot
burst, and suppressing the second flip of a switch governing network
economics would be the wrong failure.

**Corpus goes upstream-first.** Editing the snapshot directly would break
ingest at the hash check — correctly, since it is designed to catch that. So:
edit upstream, re-snapshot, refresh `hashes.json` and `SOURCES.md`, re-ingest,
re-benchmark. The rewrite states rank-pinning as current fact rather than
layering a supersession marker over a stale q-mass claim, matching how the
07-28 re-sync handled the root_prop removal and keeping the marker file for
genuine unresolved conflicts.

## Risks / Trade-offs

**Re-seeding on a bar-parameter change hides genuine demand crossings that
happened in the same pass** → Accepted, and it is the right trade. On a pass
where the bar was re-priced, no per-subnet crossing is attributable to demand
with any confidence, so reporting them individually asserts more than the
data supports. A genuine demand crossing that survives the re-pricing
re-appears on the next pass through the normal hysteresis path, one hour
later. The parameter alert makes the withholding explicit.

**The rank invariant could fire spuriously and become noise** → It is a
health event, not a page, and it carries a configurable tolerance. Exact
agreement at 32/96 today suggests the tolerance can start tight. If it proves
noisy, the tolerance is the knob; the check is still worth having because a
persistent divergence is the only automatic evidence that the share pipeline
has drifted from the chain's view.

**The rank default could change in a later runtime, silently shifting what
`assumed-default` means** → The `assumed-default` provenance exists to mark
exactly this. The residual risk is that the number behind it goes stale in
config after an upgrade — accepted, and identical to the exposure the
existing q and h defaults already carry. The rank invariant would also catch
it: a stale local default paired with a changed chain default shows up as a
count/N divergence.

**Additive `gate_state` columns leave historical rows with NULL bar mode** →
Correct and intended. Rows before 2026-08-03 genuinely were q-mass-derived
and rows between the migration and this change genuinely do not know their
mode; back-filling would be fabrication. Readers treat NULL as "mode
unrecorded", and the notifier renders such crossings without asserting a
mode. The calibration read should know that events 1 to 26 predate mode
tracking, and that events at 2026-08-03T21:06 are migration artefacts rather
than demand signals.

**Corpus re-ingest could regress retrieval quality** → The retrieval
benchmark is the existing gate (last run perfect over the 07-28 corpus).
Because the Root Reborn and rank-pinning material is new, the benchmark has
no questions for it, and a perfect score would prove nothing about the new
content — so benchmark questions are extended to cover both, including a
refusal case that must not be answerable from the stale q-mass claim.

**Paging a flip with no economic effect** → The provenance-only rule keeps an
explicit-set-to-current-value off the wire. A genuine change to any of the
four knobs always moves the bar or the curation regime, so it always merits a
page.

## Migration Plan

1. Off-device: schema and poll changes, watch set, invariant check, notifier
   changes, tests. Livedata schema additions are `ALTER TABLE ... ADD COLUMN`
   on `gate_state` and `gate_events` plus two new tables — no rewrite of
   existing rows.
2. Corpus upstream edits, re-snapshot, hash refresh; benchmark questions
   extended for the new material.
3. Ship to the Pi via `git pull`, ship OFF: the chain-parameter watch and its
   Telegram class default disabled, so the first deployed pass changes
   nothing but the additive columns and the invariant health event.
4. Verify one poll writes rank 32 `assumed-default`, bar mode `rank`, and an
   above-bar count of 32 matching N with no divergence event.
5. Enable the watch; confirm all four items seed observations with no
   spurious transitions (first-observation rule).
6. Enable the `chain-parameter-change` class, seeding its watermark so the
   seeded observations cannot backfill-flood.
7. Re-ingest the corpus and re-run the retrieval benchmark on device.

Rollback: the watch and the class each have an independent config
kill-switch, and neither gates crossing detection. The re-seed-on-parameter-
change behaviour is inert when no parameter changes. Additive columns are
harmless if the feature is disabled. The corpus reverts by restoring the
prior snapshot and re-ingesting.

## Open Questions

None blocking. Two to revisit after a live window: the invariant tolerance
(start tight at exact agreement, widen only on evidence), and whether the
seeded first observation of each watched item deserves a distinct "watch
established" line in status output or whether the observation history is
sufficient.
