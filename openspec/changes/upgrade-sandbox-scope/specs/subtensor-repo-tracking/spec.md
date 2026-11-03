## MODIFIED Requirements

### Requirement: Safe journaled update process

The update process SHALL: take an exclusive update lock on the clone,
waiting a bounded time for it; verify the remote matches the pinned
identity; verify the working tree is clean; verify free disk is at or
above the configured `min_free_bytes`; fetch remote changes and tags;
record previous and new tracked SHAs; determine whether the tracked branch
changed; advance the working tree only by fast-forward or by deterministic
reset to the confirmed remote branch (recording when the range was not
fast-forward); never create a merge; and record start, finish, status, and
error for every run. Any other process that reads the clone's working tree
while it must not move SHALL hold the same lock. The update interval SHALL
be a configuration value, not hard-coded, and scheduled execution SHALL
NOT be activated before the interval decision (PRD §21 Q20) is recorded.
(ATLAS-REPO-004)

#### Scenario: Normal update succeeds

- **WHEN** `update` runs and the remote branch has new commits reachable by
  fast-forward
- **THEN** the working tree advances to the new SHA by fast-forward, the
  run record holds previous SHA, new SHA, start/finish, and status ok

#### Scenario: Upstream history rewrite

- **WHEN** the fetched remote branch head is not a descendant of the local
  tracked SHA
- **THEN** the working tree is deterministically reset to the remote SHA,
  no merge is created, and the run and change records mark the range as
  non-fast-forward

#### Scenario: Unexpected local modifications detected

- **WHEN** `update` finds the working tree dirty before fetching
- **THEN** it aborts with a local-modifications finding and the tree is
  left untouched

#### Scenario: Remote identity mismatch aborts

- **WHEN** the clone's remote URL no longer matches the pinned identity
- **THEN** `update` aborts before fetching and records the mismatch

#### Scenario: Low disk stops the fetch

- **WHEN** free disk at the clone is below `min_free_bytes`
- **THEN** `update` records the run as disk-limited, starts no fetch,
  leaves the tree untouched, and exits non-zero

#### Scenario: Failure preserves last good state

- **WHEN** the fetch or any later step fails
- **THEN** the previously tracked local state remains intact and the run
  record holds the error; subsequent status reporting reflects the failed
  attempt

#### Scenario: Two updates at once

- **WHEN** the repotrack timer and the upgrade job start `update` in the
  same second
- **THEN** one waits for the other's lock, and the two never fetch or move
  the tree at the same time

#### Scenario: Lock not released in time

- **WHEN** the lock stays held past the wait bound
- **THEN** `update` records the run as busy, touches nothing, and exits
  non-zero
