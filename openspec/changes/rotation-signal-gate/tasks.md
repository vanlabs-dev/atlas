## 1. Ledger generalization

- [x] 1.1 Add a source triple (class, source store, source row id) plus netuid
      to `signal_entries` and `signal_outcomes`, additive with a migration that
      backfills existing rows as class `econ-code` / `narrative-cluster` /
      `watchlist` from their `signal_events` rows
- [x] 1.2 Replace the `tier = instant` selection in `_ensure_measurement_rows`
      with selection over every registered netuid-scoped class whatever its
      delivery tier, so a demoted class keeps filling (D5)
- [x] 1.3 Add an entry point that enters an externally produced netuid-scoped
      event into the ledger by source triple, idempotent on re-entry
- [x] 1.4 Have the hourly fleet pass read livedata's gate-event and
      rotation-event stores read-only and enter their new eligible or
      shadow-tier events through 1.3
- [x] 1.5 Extend `effectiveness` to report every registered measured class with
      its current tier, and to mark a horizon not readable when pending
      outcomes outnumber filled ones
- [x] 1.6 Add `min_filled_for_promotion` (default 30) to config with the
      strawman comment, and have `effectiveness` state per class whether the
      7-day sample meets it
- [x] 1.7 Tests: backfilled rows keep their class, external entry is
      idempotent, shadow events are entered, a majority-pending horizon is
      marked unreadable, the report names tiers

## 2. Root weight vector read

- [x] 2.1 Derive and self-test the `Weights` prefix at the root netuid against
      the observed key layout, using the existing derived-key self-test path;
      recover the validator uid from the key tail
- [x] 2.2 Enumerate with `state_getKeys` and read every returned key with one
      `state_queryStorageAt` at the gate poll's finalized block; do not use
      `state_getPairs` (endpoint code 4003)
- [x] 2.3 Decode each value as compact-length-prefixed `Vec<(u16, u16)>`; fail
      the pass closed with a health event on any decode failure, key-layout
      mismatch, or short batch, persisting nothing for that pass
- [x] 2.4 Verify the cost of stake weighting (D2): whether `Keys[ROOT][uid]`
      and the resolved hotkeys' root stake can be read in two further batched
      calls at the same block inside the pass's budget. Record the finding in
      `docs/decisions.md` and pick weighted or unweighted from it
- [x] 2.5 Persist per-validator vectors and the aggregate destination map with
      the block reference and the weighting basis as a stored field
- [x] 2.6 Add `max_enumerated_keys` to config; fail the read closed with a
      health event above the cap rather than truncating, and record the
      observed key count every pass
- [x] 2.7 Make the read independently disableable and not gated by
      `gate_signal.enabled`
- [x] 2.8 Tests: prefix self-test, uid recovery from key tail, decode of a
      known vector, short batch fails closed, undecodable vector fails closed,
      cap exceeded fails closed, basis is persisted, gate rollback leaves the
      read running

## 3. Rotation events

- [x] 3.1 Compare each pass's aggregate map against the previous one and record
      a rotation event per destination whose share moves past a configured
      threshold, or that enters or leaves the map
- [x] 3.2 Persist destination netuid, previous and new share, contributing
      validator count, weighting basis, block reference, observation time
- [x] 3.3 Seed the first map silently; re-seed silently and record no events on
      a pass where the curation master switch or the concentration cap
      transitions
- [x] 3.4 Tests: threshold crossing records once, sub-threshold move records
      nothing, entry and exit each record, first map seeds silently, a
      curation-parameter transition re-seeds without storming

## 4. Gate-crossing reversal guard

- [x] 4.1 Add a persisted eligibility state to gate-crossing events and a
      configurable durability window (default 48h)
- [x] 4.2 Mark a crossing eligible once the window elapses with no opposing
      crossing for that netuid; mark it reversed and permanently ineligible if
      one arrives inside the window, retaining both
- [x] 4.3 Treat crossings recorded before this change as eligible, so the
      deploy does not swallow a backlog
- [x] 4.4 Tests: window elapses to eligible, reversal inside the window blocks
      both permanently, restart preserves reversed state, pre-existing
      crossings are eligible

## 5. Tier registry and delivery

- [x] 5.1 Add a `tier` value to every class in `telegram/config.json` and make
      an unregistered class undeliverable
- [x] 5.2 Implement `shadow` in the notifier: record against the shadow tier,
      advance the watermark, send nothing, carry nothing into the briefing
- [x] 5.3 Record the governing tier in the delivery ledger for every processed
      event, whatever its tier
- [x] 5.4 Update the gate-crossing adapter to page only eligible crossings,
      record reversed ones as reversed and advance past them, and leave
      not-yet-eligible ones for a later scan without advancing
- [x] 5.5 Add the `root-rotation` adapter and renderer: destination netuid,
      previous and new share, contributing validators, weighting basis, block
      reference, all from recorded fields; state plainly when the basis is
      unweighted
- [x] 5.6 Add `root-rotation` to the `governs` map and the voice gloss map
      (root weight vector, destination share, weighting basis) so no paged term
      is unglossed
- [x] 5.7 Tests: shadow sends nothing and advances, promotion does not replay a
      backlog, ledger names the tier, reversed crossing never pages,
      not-yet-eligible crossing does not advance the watermark, rotation render
      uses only recorded fields, unweighted basis is stated, shrink order holds

## 6. Demotions, deploy, acceptance

- [x] 6.1 Push and `git pull` on the Pi; confirm no new unit, timer, port, or
      credential
- [x] 6.2 Confirm the first root read on the next hourly pass: enumerated key
      count, decoded destination count, and weighting basis checked against a
      manual read at the same block; first map seeds silently
- [x] 6.3 Flip `econ-code` and `subnet-registry` to `briefing` in one commit;
      confirm the next scan records them as briefed and pages nothing
- [x] 6.4 Set the date of the `root-rotation` promotion decision (earliest at
      which 30 filled 7-day outcomes are possible) and record it in
      `docs/decisions.md` as a dated open item
- [ ] 6.5 After one week: read delivered counts per class against the
      pre-change baseline of 199 in 30 days, confirm 1 to 2 pages a day, and
      adjust tier values before archive if not
- [x] 6.6 Record in `docs/decisions.md` the effectiveness read that justified
      each demotion, as filled count, class median and baseline median per
      horizon

## 7. Documentation

- [x] 7.1 `README.md` status: the tier registry, the shadow tier, the two
      demotions, and the root-rotation class
- [x] 7.2 `livedata/README.md`: the root weight vector read, its two RPC calls,
      the fail-closed conditions, and the weighting basis field
- [x] 7.3 `fleet/README.md`: the ledger now measures any registered
      netuid-scoped class, and the promotion rule
