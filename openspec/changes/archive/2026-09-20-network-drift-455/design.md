## Context

See proposal.md "Why" for motivation and the evidence trail. The design-level
facts that shape the approach:

- **The watch machinery already exists.** `run_chain_param_watch` runs inside
  the gate pass, is handed the bar parameters rather than re-reading them, and
  already covers one netuid-keyed item (`CollateralLockShare`) under the
  "Netuid-keyed economic parameters" requirement. This change adds a second
  item to that set, not a new subsystem.
- **The key derivation already covers the shape.** `SubnetEmissionEnabled`
  enumerates 128 entries under `twox128("SubtensorModule") ++
  twox128("SubnetEmissionEnabled")` with a **2-byte raw little-endian netuid
  tail**, the Identity hasher, the same layout `CollateralLockShare` uses.
  `storage_key_identity_u16` and `verify_key_derivation` apply unchanged.
- **The read is free.** `read_subnet_maps` batches every netuid-keyed item
  through one `state_getKeys` plus chunked `state_queryStorageAt` at a single
  finalized block. Adding an item adds keys to an existing batch, not a pass.
- **The value is a bool with meaningful absence.** Present entries are `0x01`
  or `0x00`; the runtime's `ValueQuery` default is false, so an absent entry
  means disabled. Absence is a state, not a read failure, and the existing
  items' codecs (`u16`, `u96f32`, `identity_name`) do not cover it.
- **The historical event is already past.** The 2026-09-09 flip is in
  `panel_snapshot` but not in `chain_param_events`. The watch starts from the
  state it first observes.

## Goals / Non-Goals

**Goals:**

- One page, not 49, when a root key flips the switch for a batch of subnets.
- The board, the alerts and the corpus all name the switch as a switch, so a
  root action is never read as a demand move.
- No new provider call, credential, port, service or quota.

**Non-Goals:**

- **Backfilling the 2026-09-09 event into `chain_param_events`.** The event
  is recorded in `docs/decisions.md` with its evidence. Synthesising watch
  rows for a transition the watch did not observe would put a fabricated
  reference block into a store whose whole value is that every row was read
  from the chain.
- **Watching every netuid-keyed bool.** The switch earns its place because it
  is root-settable, silent in every other figure, and demonstrably in use.
  A general sweep is a different change.
- **Changing the share normalization universe.** The `live-data` delta records
  the deviation and makes the cross-check its standing measure. Narrowing the
  universe to the chain's emit-to filter would need `FirstEmissionBlockNumber`,
  `SubtokenEnabled` and the registration flag read every pass, and the measured
  residual (+0.34%, 32 of 32 above the bar) does not justify it.

## Decisions

### The switch is a watch item, not a new signal class

It routes through the existing instant-tier `chain-parameter-change` class.

*Why:* the class already means "a root-settable economic knob moved", has no
cooldown by requirement, and is exactly what this is. A root action is rare
(one batch in the ~4 months of history checked) and unconditionally material.

*Alternative considered:* a new netuid-scoped class, which under the
`signal-effectiveness-gate` rule would default to `shadow` and reach a paging
tier only on a filled effectiveness read. Rejected: at roughly one event a
quarter the ledger would never fill, so the rule's evidence path is unusable
here, and the class would be permanently silent by construction. The
effectiveness gate governs netuid-scoped **market** signals whose value is
measurable against a price baseline; a governance action is not that kind of
signal. This reasoning is recorded in `docs/decisions.md` so the exemption is
explicit rather than an oversight. Operator decision, 2026-09-11.

### Collapse is a rendering rule keyed on (item, reference block)

The notifier groups unseen netuid-keyed transitions by item and reference
block, renders one message per group, and ledgers each underlying event
individually.

*Why:* the grouping key is the chain's own unit of atomicity. Two subnets that
change at the same block changed together; two that change at different blocks
are two facts. Keeping the ledger per event preserves de-duplication,
replay-safety and the "suppressed, recorded, never dropped" rule the notifier
holds everywhere else.

*Alternatives considered:* a time-window digest (rejected: invents a window
the chain does not have, and delays an instant class); a per-netuid cooldown
(rejected: the first 49 pages would still arrive, which is the actual
problem).

### Absence is decoded as off, and a failed read is neither

A `bool` codec is added that maps `0x01` to true, `0x00` to false, and a
missing entry to false-by-default, carrying the distinction between "absent,
so default" and "the batch did not return" into the recorded row the way the
gate poll already distinguishes `assumed-default` from `explicit` provenance.

*Why:* a wrong prefix returns an empty key set that is indistinguishable from
every subnet being disabled. That is the failure mode
`verify_key_derivation` and the `SUBNET_MAP_CONTROL` map exist to prevent, and
this item must fail closed the same way: a short or empty batch invalidates
the read rather than recording 128 spurious transitions to off.

### The first pass seeds silently

Consistent with `CollateralLockShare` and the existing requirement.

*Why:* the alternative is 128 transitions on the first pass after deploy,
including a false "just turned on" for every enabled subnet. The cost is that
a flip between drafting and deploy is absorbed into the seed. That cost is
already paid for this event, since the flip has happened, and the two subnets
currently off (SN29, SN36) will seed as off, which is correct.

### The mining rung is renamed in reason text, not in ladder position

The rung keeps its position and its trigger. The recorded reason, the rung
identifier and the board copy stop calling it the emission gate.

*Why:* the behaviour was never wrong; the existing reason text already
describes the mechanism accurately ("alpha is still distributed to miners but
no TAO inflow backs it", which matches the chain code). Only the name
conflated a root switch with the bar. `cut_reason` is computed at board build
and not persisted in `mine_econ`, so no stored row is rewritten and no
migration is needed.

## Risks / Trade-offs

- **A collapsed page hides which subnets matter to the reader** → the message
  carries the full netuid list, truncated visibly with the count stated, and
  the per-netuid rows stay queryable in the watch store.
- **The board's ranked count jumps without an obvious cause, again** → the
  `mining-triage` delta requires the board to carry the reference block of the
  switch state it was built from, so a jump is attributable to a recorded
  transition instead of looking like a change in subnet economics.
- **A wrong or renamed storage prefix silently records every subnet as off,
  and the next flip-to-on pages 128 transitions** → the read is gated by
  `verify_key_derivation` and the control-map rule, and a short batch fails the
  item closed rather than recording it.
- **The corpus gains a mechanism that the benchmark battery can regress on**
  → two adversarial cases pin it, and the battery is re-accepted under the
  existing threshold sheet before the corpus is activated on the device.
- **The public page could inherit the renamed rung text** →
  `subnt/atlas_subnt.py` reads `mine_econ` and `build_board` ordering, and
  its exclusion scan fails the pass closed on operator material. The rename is
  checked against that scan before publish rather than assumed safe.

## Migration Plan

1. Land the watch item, the collapse rule and the rung rename off-device, with
   suites green in `livedata`, `telegram`, `fleet` and `subnt`.
2. Re-sync the corpus, regenerate `hashes.json`, run the extended battery
   off-device.
3. `git pull` on the Pi. The next gate pass seeds the switch across every
   subnet with no alert.
4. Ingest and activate the new corpus run; the previous run deactivates
   automatically.
5. Confirm on the device: the seeded row count matches the observed subnet
   count, the board's ranked count is unchanged by the rename alone, and one
   synthetic collapsed render is inspected before the next real transition.

**Rollback:** remove the item from the `chain_params` watch set in
`livedata/config.json`; the class, the store and every other item are
unaffected. The rung rename and the corpus are reverted by `git`. The corpus
falls back by activating the prior ingest run.

## Open Questions

- Whether the two subnets currently off (SN29, SN36) are a deliberate
  long-term state or a pending re-enable. It changes nothing in this design:
  either way they seed as off and any later flip pages.
