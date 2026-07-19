# subnet-repo-fleet Specification

## Purpose
Maintain a chain-driven fleet of local subnet repository clones: the
TaoStats-reported on-chain SubnetIdentity github_repo map is the desired
state; a registry plus blobless, never-executed clones under var/fleet/
are the actual state. Reconciliation clones what is new, advances what
exists, re-points identity churn into new epochs, discards what
deregistered — per-slot fail-closed, mass-discard guarded, bounded per
pass, reusing repotrack's journaled update primitives.

## Requirements
### Requirement: Fleet identity is derived from validated chain-reported subnet identity

The fleet's desired state SHALL be the `netuid → github_repo` map obtained from
the live-data subnet-identity operation, which is typed-schema-validated and
freshness-checked before use. The map's provenance SHALL be recorded as
TaoStats-reported chain identity with its reference block, not as chain-verified
truth. A subnet whose on-chain identity carries no usable `github_repo` SHALL be
recorded as a tracked slot with no clone (it counts toward the fleet but is not
cloned). The reconciler SHALL NOT derive identity from any unvalidated or cached
source.

#### Scenario: Validated map drives the fleet

- **WHEN** a reconcile pass obtains a schema-valid, in-freshness subnet-identity
  map
- **THEN** each subnet with a usable `github_repo` becomes a desired fleet slot
  keyed by netuid, and subnets without one are recorded as no-repo slots

#### Scenario: Identity provenance is recorded honestly

- **WHEN** a slot is cloned or updated from the map
- **THEN** its recorded identity provenance names the provider and reference
  block and does not claim direct chain verification

### Requirement: Reconciliation is idempotent, bounded, and resumable

A reconcile pass SHALL compute a per-slot plan by comparing the validated desired
map against the local registry, producing exactly one action per slot from
{clone, update, re-point, discard, no-repo}. New clones and re-points SHALL be
bounded to a configured maximum per pass; updates of already-active slots MAY all
proceed. Each slot SHALL carry a status that makes an interrupted pass resumable
and a completed pass a no-op on re-run. A single unreachable, malformed,
oversized, or non-GitHub repository SHALL be recorded and skipped without
blocking any other slot.

#### Scenario: Cold start spreads across passes

- **WHEN** the registry is empty and the desired map has more repositories than
  the per-pass clone bound
- **THEN** the pass clones up to the bound, leaves the remainder pending, and
  subsequent passes converge without re-cloning what already succeeded

#### Scenario: One bad repository does not stall the fleet

- **WHEN** a slot's repository is unreachable, has an unparsable URL, or exceeds
  the size or file-count cap
- **THEN** that slot is recorded as unreachable / invalid-url / quarantined and
  the remaining slots are processed normally, and the per-slot failure is
  counted by its status rather than as a process error (so a scheduled pass
  that ran is reported healthy even while dead repositories exist)

#### Scenario: A persistently unreachable repository is backed off, a fix is not

- **WHEN** a slot's repository stays unreachable across passes (a placeholder
  URL, a private repository the read-only token cannot access, or a deleted
  repository)
- **THEN** its retry is throttled by an escalating backoff so it stops consuming
  a clone attempt every pass; but if the owner publishes a different repository
  URL, the identity fingerprint changes and the slot is re-pointed immediately,
  without waiting for the backoff

#### Scenario: Re-running a converged pass changes nothing

- **WHEN** a reconcile pass runs against a registry already matching the desired
  map
- **THEN** no clone, re-point, or discard occurs and only bookkeeping timestamps
  update

### Requirement: Degraded identity data is never destructive (mass-discard guard)

Discard and re-point are the only destructive actions and both are driven by the
identity map. They SHALL be produced ONLY when the identity fetch for the pass is
successful, schema-valid, within its freshness envelope, and paginated to
completion. On any degradation of the identity fetch the pass SHALL make no
destructive change and SHALL preserve the last good registry and clones. A
partial, stale, or unvalidated map SHALL NEVER be interpreted as subnets having
deregistered or changed.

#### Scenario: Incomplete map discards nothing

- **WHEN** the identity fetch fails validation, is stale, or cannot be paginated
  to completion
- **THEN** the pass performs no discard and no re-point, the registry is
  unchanged destructively, and the degradation is recorded

#### Scenario: Deregistration acted on only from a good read

- **WHEN** a subnet is absent from a fully validated, complete, in-freshness map
  that was present before
- **THEN** its slot is discarded; but the same absence in a degraded map is
  ignored

### Requirement: Identity churn re-points the slot and segments change history

Each slot SHALL carry a fingerprint derived from the normalized repository URL
(and the subnet owner where the identity source provides it), deliberately
excluding the subnet display name. The TaoStats subnet-identity endpoint does
not carry the owner, so in practice the fingerprint keys on the repository URL;
a re-registration is a different project with a different repository, so the
URL change re-points the slot. When
the fingerprint is unchanged the slot SHALL be updated in place. When the
fingerprint changes the slot SHALL be re-pointed: the old clone discarded, the
new repository cloned, the current identity epoch closed, and a new epoch opened.
Recorded change ranges SHALL be scoped to `(netuid, epoch)` so that a query for a
netuid never blends the commit history of two different projects that occupied
the same slot.

#### Scenario: Display-name rename does not re-clone

- **WHEN** a subnet's name changes but its owner and repository URL do not
- **THEN** the fingerprint is unchanged and the slot is updated in place, not
  re-cloned

#### Scenario: Slot re-registration re-points and starts a new epoch

- **WHEN** a slot's owner or repository URL changes (owner edit or
  deregistration + re-registration)
- **THEN** the old clone is discarded, the new repository is cloned, and change
  ranges recorded afterward belong to a new epoch distinct from the prior
  project's history

### Requirement: Fleet clones are minimal-footprint and are never executed

Fleet clones SHALL be blobless (full commit graph, blobs fetched on demand),
SHALL check out the remote default branch without a third-party API call, SHALL
be created with submodule recursion disabled, and SHALL have their push URL
disabled. Per-repository clone-size and file-count ceilings SHALL be enforced,
quarantining a slot that breaches them. Atlas SHALL NEVER build, test, execute,
install, or run hooks or submodule fetches for any subnet repository. A
configured disk ceiling SHALL stop new clones and record a disk-limited status
rather than exhausting device storage.

#### Scenario: Untrusted code is cloned but never run

- **WHEN** a subnet repository is cloned or updated
- **THEN** only git fetch/checkout and file reads occur; no build, test,
  install, hook, or submodule fetch is invoked

#### Scenario: Oversized repository is quarantined

- **WHEN** a repository exceeds the configured size or file-count cap
- **THEN** the clone is aborted and cleaned up, the slot is marked quarantined,
  and the pass continues

#### Scenario: Low disk headroom stops new clones

- **WHEN** free disk headroom falls below the configured ceiling
- **THEN** no new clone is started, the condition is recorded as disk-limited,
  and existing slots continue to update

### Requirement: Per-slot change records reuse the tracker's recorded range shape

For each successful update that advances a slot's head, the fleet SHALL record a
change range using the repository tracker's recorded shape — commits, per-file
additions and deletions, tags, and a labelled machine summary — scoped to the
slot's `(netuid, epoch)`, advancing by fast-forward or deterministic reset and
never by merge. A fetch or record failure SHALL preserve the slot's last good
state and be recorded, without corrupting the registry or affecting other slots.

#### Scenario: Advancing head produces an epoch-scoped range

- **WHEN** a slot's remote default branch advances and the fetch succeeds
- **THEN** a change range for `(netuid, epoch)` is recorded with the commits and
  per-file churn for the advance

#### Scenario: Fetch failure preserves last good state

- **WHEN** a slot's fetch or change-record step fails
- **THEN** the slot retains its previous recorded head and the failure is
  recorded, leaving other slots unaffected

### Requirement: Scheduled bounded refresh independent of the subtensor tracker

The fleet SHALL be refreshed on its own schedule, independent of the subtensor
repository tracker's timer. Each scheduled pass SHALL refresh the identity map
(one to two provider calls) and then perform a bounded set of clone/update
operations. Per-slot freshness SHALL be derived from the configured cadence, and
the fleet status surface SHALL report counts by status, total clone size, last
reconcile time, and the stalest slot.

#### Scenario: Fleet refresh runs on its own cadence

- **WHEN** the fleet timer fires
- **THEN** it refreshes the identity map and reconciles a bounded batch, without
  depending on or blocking the hourly subtensor update service

#### Scenario: Status surface reports fleet health

- **WHEN** fleet status is queried
- **THEN** it returns counts by slot status, total clone bytes, the last
  reconcile time, and the stalest slot
