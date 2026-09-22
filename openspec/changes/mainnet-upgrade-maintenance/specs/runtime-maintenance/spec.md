# Runtime maintenance requirements

## Finalized discovery

The controller MUST verify Finney genesis and scan all finalized blocks in its
accepted range. A gap, unavailable history or inconsistent provider MUST block
cursor advancement. A runtime replacement MUST be detected even if the runtime
spec is unchanged or decreases. Baseline coverage MUST remain explicitly dated.

## Evidence and coverage

A source mapping MUST identify the deployed artifact, not merely a matching tag.
Every upstream changed path and Atlas subsystem MUST have an evidenced review
disposition. Storage absence MUST be interpreted using metadata and defaults.

## Authority

Models MUST NOT execute tools, access publication credentials or alter policy.
Candidate code MUST run only inside the approved test isolation. Independent
review and mandatory tests MUST bind to the exact candidate content. A malformed,
partial, stale or unsupported receipt MUST block publication.

The public renderer `subnt/atlas_subnt.py` MUST remain protected from automatic
candidate edits. The default mandatory suites MUST include `subnt/tests`.

## Publication and rollout

The publisher MUST use the personal identity and Atlas-only destination.
Publication MUST be fast-forward and remote-readback verified. Deployment MUST
be quiescent, clean-baseline checked, backed up and acceptance verified.
A failed activation MUST preserve a blocked/failed state and restore the last
accepted local release when rollback is safe. Never force-push history.

Producer coordination MUST use `atlas-subnt.service` and `atlas-subnt.timer`
for the current public publisher. User-unit preparation MUST preserve the
renderer command and timer schedule. Active system producer jobs or timers
MUST block enabling their user-unit replacements.

## Operations

A durable ledger MUST distinguish discovery, evidence, validation, publication
and activation. Retries MUST be bounded and resumable. Notifications MUST be
stable-key deduplicated without erasing failed delivery state.
