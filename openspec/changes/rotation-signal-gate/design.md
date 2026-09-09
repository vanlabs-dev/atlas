## Context

See proposal.md, Why. Three facts shape the approach.

The effectiveness ledger already exists and is nearly class-agnostic.
`_ensure_measurement_rows` (`fleet/atlas_fleet_signals.py:1311`) selects events
by `tier = instant`, resolves netuid members, and writes `signal_entries` plus
`signal_outcomes` rows per configured horizon. `default_price_fetcher` pulls
the whole fleet price vector through the live-data layer once per pass and
stores it, so baselines cost no extra calls. What is missing is a way for an
event that did not originate in `signal_events` to be entered.

The root weight read was probed live on 2026-09-09 at finalized head
`0xab6d1b7b`. `Weights` at the root netuid is a double map keyed
Identity(NetUid) ++ Identity(uid), so the validator uid is recoverable from
the key tail. It held 20 entries, 1833 payload bytes, decoding as
compact-length-prefixed `Vec<(u16 netuid, u16 weight)>` with 68, 23 and 26
destinations in the first three. The unweighted aggregate covered 96 distinct
destinations with a largest share of 5.24% against the 6.25% cap.
`state_getPairs` is refused by the public endpoint with code 4003;
`state_getKeys` and `state_queryStorageAt` both succeed.

Constraints carried from the existing system: no new provider, credential,
port, service, or model; tests off-device under `unittest`; the Pi is the
acceptance environment; livedata owns chain reads and telegram owns delivery;
the notifier opens every source store read-only.

## Goals / Non-Goals

**Goals:**

- One measurement path that every netuid-scoped class flows through, so
  "is this class worth paging" is always answerable from stored data.
- A class cannot page until someone has looked at that answer.
- The curated root flow is observed at the same cadence and the same block as
  the gate state, keylessly.
- Every demotion in this change is reversible by a config value and leaves its
  evidence in the decision log.

**Non-Goals:**

- Predicting rotation, ranking destinations, or recommending an allocation.
  The ledger measures; it never advises. This preserves the existing
  "measurement only, no recommendation derived" contract.
- Modelling root dividend TAO amounts per destination. The map is a share of
  weight, not a flow in TAO.
- Touching `mining-triage`, the mining board, or the `fail-closed` schedule
  gap. Both are out of scope by operator instruction.
- Removing any detector. Every demotion keeps its detection intact.

## Decisions

**D1. `state_getKeys` then `state_queryStorageAt`, both at the gate poll's
finalized block.** Probed live: `state_getPairs` returns code 4003 "RPC call is
unsafe to be called externally", so the one-call prefix read is unavailable.
Enumerating with `state_getKeys` and batching the values with
`state_queryStorageAt` is two calls total and reuses the batched multi-key
read the chain-parameter watch already has. Alternative: 20 individual
`state_getStorage` calls, which is what the probe did first. Rejected: it
costs a round trip per validator, grows with adoption, and cannot be pinned to
one block as cleanly.

**D2. The aggregate map declares its weighting basis, and ships unweighted if
stake weighting is not cheap.** An unweighted aggregate treats a validator
with 1,000 TAO of root stake the same as one with 500,000, which is wrong as a
description of dividend flow. Stake weighting needs uid to hotkey
(`Keys[ROOT][uid]`) and then that hotkey's root stake, which is two further
batched reads of the same 20 keys at the same block. Task 2.4 verifies that
cost before it is committed to the hourly pass. Whichever way it lands, the
basis is persisted with the map and the renderer states it, because a share
labelled as flow when it is not is the failure mode this system exists to
avoid. Alternative: block the change on stake weighting. Rejected: an
unweighted map that says it is unweighted is still a usable rotation signal,
and the label makes it honest.

**D3. Delayed eligibility, not page-then-retract.** A crossing cannot be known
to be durable at the moment it is recorded. Two options: page immediately and
send a correction when it reverses, or withhold until the window passes. A
retraction is another page, which makes the volume problem worse. Eligibility
is persisted on the event so a restart cannot resurrect a reversed crossing,
and the standing "at the bar" briefing line covers the immediacy the delay
gives up. The window is config, defaulting to 48 hours because 18 of the last
55 crossings reversed inside that span.

**D4. Ledger entries gain a source triple; non-fleet events are not copied
into `signal_events`.** An entry becomes keyed by (class, source store, source
row id, netuid) rather than by a `signal_events` row id. The hourly fleet pass
reads livedata's gate and rotation stores read-only and enters their new
eligible or shadow events, which keeps one price fetch per pass and one place
where measurement lives. Alternative: mirror gate and rotation events into
`signal_events`. Rejected: it would make the fleet store the owner of events
livedata produces, and two stores would then disagree about the same event's
identity.

**D5. The econ judge keeps running while econ-code is demoted.** The judge
costs model calls and the class no longer pages, so switching it off is
tempting. It stays on because the verdicts are what populate the briefing
lines and what keep the 30-day horizon filling, and the 30-day row is the only
one that could reverse this demotion. Turning off measurement at the moment of
demotion would make the demotion permanent by construction.

**D6. Promotion needs 30 filled 7-day outcomes, as a calibrated strawman.**
The number is config with a default of 30, following the existing
"strawman, run `calibrate` on-device and set from the evidence" idiom in
`fleet/config.json`. It is a floor on sample size, not a significance test:
the report prints medians and counts and a human decides. Alternative: a
bootstrap confidence interval. Rejected as unjustified precision on a
single-operator system where the decision is already recorded by hand.

**D7. Volume target is stated and checked, not assumed.** Acceptance includes
a one-week read of delivered counts per class against the pre-change baseline
of 199 in 30 days. If the result is not 1 to 2 pages a day, the tier values
are wrong and are adjusted before the change is archived.

## Risks / Trade-offs

- [Validator adoption grows and the enumeration becomes unbounded] → Cap the
  number of enumerated keys per pass in config, fail the read closed above the
  cap with a health event rather than truncating, and record the observed
  count each pass so the cap can be raised deliberately.
- [Stake weighting turns out to need more reads than the pass can afford] →
  The spec already covers both branches; ship unweighted and labelled, and
  make weighting its own change. This is why the basis is a persisted field
  and not an assumption.
- [Demoting econ-code hides a genuinely material subnet change] → Detection,
  the judge, the cooldown breakthrough and the digest all survive; a `high`
  verdict still reaches the operator the same day in the briefing. Only the
  page is removed, and the ledger keeps accruing the evidence to reverse it.
- [The 30-day econ-code horizon matures positive and the demotion was wrong]
  → That is the designed outcome of D5: measurement continues, and the
  decision log records the read that justified the call so the reversal is a
  one-value change with its own recorded evidence.
- [`root-rotation` sits in shadow for weeks and the operator forgets it] →
  The effectiveness report prints every class with its tier, and the weekly
  pulse edition is where that read is meant to surface. Task 6.4 sets the date
  of the first promotion decision rather than leaving it open.
- [Delayed eligibility hides a real, fast, one-way collapse below the bar] →
  The standing "at the bar" briefing line names every subnet currently within
  the hysteresis band each day, so a subnet on the edge is visible before its
  crossing is eligible.
- [The tier registry becomes a second place where classes are configured and
  drifts from the class list] → The registry is the existing `classes` block
  in `telegram/config.json` with a `tier` value, not a new file; a class
  absent from it cannot deliver, which makes drift fail closed.

## Migration Plan

1. Off-device: ledger source triple and entry point, shadow tier, tier
   registry read, root vector read and decode, rotation event recording,
   reversal guard, renderers, config defaults. Tests green across `livedata`,
   `fleet`, `telegram`.
2. Push; `git pull` on the Pi. No new unit, timer, port, or credential.
3. Root vector read starts on the next hourly pass. The first map seeds
   silently. Confirm the enumerated count, the decoded destination count, and
   the recorded weighting basis against a manual read at the same block.
   Rollback: disable the root read's config block.
4. Flip `econ-code` and `subnet-registry` to `briefing` in one commit. Confirm
   the next scan records them as briefed and pages nothing. Rollback: revert
   the two tier values.
5. Gate-crossing durability window takes effect on the next pass. Existing
   recorded crossings are treated as eligible so the change does not silently
   swallow a backlog. Rollback: set the window to zero.
6. After one week, read delivered counts per class and the effectiveness
   report; record both in the decision log with the promotion decision for
   `root-rotation`.

## Open Questions

- Whether the aggregate destination map can be stake-weighted within the
  hourly pass's read budget (D2, task 2.4). The specs cover both outcomes and
  the renderer states whichever applies, so this can be answered during
  implementation without changing the approach or the task breakdown.
- Whether the standing "at the bar" briefing line belongs in the daily or the
  weekly edition. It is a briefing composition detail under existing
  `pulse-briefing` requirements and does not affect any spec here.
