# subnet-repo-fleet Specification (delta)

## ADDED Requirements

### Requirement: Reconcile records a per-slot branch-tips snapshot without fetching

For each active slot in a reconcile pass, the fleet SHALL record a snapshot of
the slot's remote branch tips obtained from a single `git ls-remote --heads`
against the slot's origin — a bounded `ref → sha` map (capped at a configured
maximum number of refs) scoped to `(netuid, epoch)` and the pass. Recording the
snapshot SHALL NOT fetch branch contents, check out, or date any branch commit,
and SHALL add no clone or blob cost. A slot whose `ls-remote` fails SHALL have no
snapshot recorded for that pass and SHALL be skipped without blocking other
slots or the reconcile outcome. Snapshots enable a downstream branch-pulse
metric derived purely from tip changes between passes.

#### Scenario: Active slot's branch tips are snapshotted cheaply

- **WHEN** a reconcile pass processes an active slot
- **THEN** a bounded `ref → sha` tip map is recorded for `(netuid, epoch, pass)`
  from one `ls-remote --heads`, with no fetch, checkout, or blob download

#### Scenario: ls-remote failure is fail-closed and non-blocking

- **WHEN** a slot's `ls-remote` call fails or times out during a pass
- **THEN** no tip snapshot is recorded for that slot that pass, the failure does
  not block other slots, and the reconcile outcome is unaffected

#### Scenario: Ref set is bounded

- **WHEN** a slot's remote exposes more branch refs than the configured cap
- **THEN** the recorded snapshot is bounded to the cap and the truncation does
  not fail the pass

#### Scenario: Snapshot is epoch-scoped across re-points

- **WHEN** a slot re-points and a new epoch opens
- **THEN** tip snapshots are recorded under the new epoch and are not compared
  against the prior project's snapshots
