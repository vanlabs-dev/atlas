# Delta for subtensor-repo-tracking

Covers PRD §12.6 (ATLAS-REPO-001…009) and the §12.10 tool requirements as
they apply to the repository tool surface. Phase 3 exit criteria map onto
the scenarios below.

## ADDED Requirements

### Requirement: Repository identity validation before setup

Before any clone is created, Atlas SHALL confirm and record: repository
owner and name, canonical clone URL, default branch, whether the repository
has moved or been archived, and which branch or release represents mainnet.
The confirmed identity SHALL be recorded in the decision log and pinned in
configuration. Any uncertainty SHALL block repository setup. (ATLAS-REPO-001)

#### Scenario: Identity confirmed and recorded

- **WHEN** `validate-identity` reports the repository metadata (canonical
  full name, archived flag, default branch, clone URL) and the operator
  confirms owner/name, URL, branch, and the mainnet-representing branch
- **THEN** the confirmation is recorded in `docs/decisions.md` and pinned in
  the repotrack configuration, and setup is permitted

#### Scenario: Uncertainty blocks setup

- **WHEN** the metadata query fails, reveals a move/rename or archived
  state, or the operator has not recorded confirmation
- **THEN** `setup` refuses to clone and reports the specific unresolved
  item; no repository state is created

### Requirement: Full non-shallow clone

Atlas SHALL maintain a non-shallow Git clone with complete reachable
history of the tracked repository at the pinned identity, on the device,
outside version control. Atlas SHALL NOT host or run a Bittensor node.
(ATLAS-REPO-002)

#### Scenario: Clone verified non-shallow

- **WHEN** `setup` completes
- **THEN** the clone reports `is-shallow-repository` false, the pinned
  branch is present, and the verification result is recorded

### Requirement: Read-only agent access

Hermes SHALL access repository information only through Atlas read-only
tools. No tool or component SHALL be able to push, rewrite history, modify
remotes, delete branches, or commit in the tracked repository; the clone's
push URL SHALL be disabled at setup as defense in depth. (ATLAS-REPO-003)

#### Scenario: Tool surface is read-only

- **WHEN** the MCP server's tool set is enumerated and exercised
- **THEN** only search/read/status/change-record tools exist, none invokes
  a mutating git operation, and the clone's push URL is set to an invalid
  value

### Requirement: Safe journaled update process

The update process SHALL: verify the remote matches the pinned identity;
verify the working tree is clean; fetch remote changes and tags; record
previous and new tracked SHAs; determine whether the tracked branch
changed; advance the working tree only by fast-forward or by deterministic
reset to the confirmed remote branch (recording when the range was not
fast-forward); never create a merge; and record start, finish, status, and
error for every run. The update interval SHALL be a configuration value,
not hard-coded, and scheduled execution SHALL NOT be activated before the
interval decision (PRD §21 Q20) is recorded. (ATLAS-REPO-004)

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

#### Scenario: Failure preserves last good state

- **WHEN** the fetch or any later step fails
- **THEN** the previously tracked local state remains intact and the run
  record holds the error; subsequent status reporting reflects the failed
  attempt

### Requirement: Change record per tracked commit range

For every change to the tracked branch, Atlas SHALL record: previous SHA,
new SHA, commit list, changed file paths, additions and deletions where
available, tags or releases encountered in the range, retrieval timestamp,
whether indexing succeeded, and a machine-generated summary stored with a
fixed label marking it as a summary, not verified effect. (ATLAS-REPO-005)

#### Scenario: Change record written on update

- **WHEN** an update advances the tracked branch
- **THEN** a change record with all required fields is persisted, and its
  summary text carries the machine-summary label

### Requirement: Incremental repository indexing

Atlas SHALL index tracked repository text files (extension-allowlisted,
size-capped) into a local full-text store with path and commit SHA
provenance. After the initial index, only changed files SHALL be
re-indexed, except that an indexer schema or parser change SHALL force a
recorded full rebuild. Indexing outcome SHALL be recorded in the change
record. (ATLAS-REPO-006)

#### Scenario: Only changed files re-indexed

- **WHEN** an update changes a subset of files
- **THEN** exactly the changed paths are re-indexed (removed files are
  deleted from the index) and the indexed SHA is updated

#### Scenario: Schema change forces full rebuild

- **WHEN** the indexer schema version differs from the stored one
- **THEN** a full re-index of the tracked SHA runs and is recorded as a
  rebuild

### Requirement: Repository freshness status

Atlas SHALL be able to report: local tracked SHA; remote tracked SHA from
the last successful fetch; last fetch attempt; last successful fetch; last
detected update; whether the working tree is clean; whether the index
matches the local SHA; and whether status is stale under the configured
policy. (ATLAS-REPO-007)

#### Scenario: Status answers all freshness fields

- **WHEN** `repo_status` is called
- **THEN** the response contains every field above, with stale computed
  from the configured interval policy

### Requirement: Honest failure and staleness reporting

If the remote is unavailable or the last fetch is older than the configured
policy allows, Atlas SHALL report repository status as unavailable or
stale. It SHALL NOT claim the local clone is current, and tools SHALL fail
closed with structured errors when the store or clone is missing or
inconsistent. (ATLAS-REPO-008)

#### Scenario: Remote unavailable

- **WHEN** an update attempt cannot reach the remote
- **THEN** the attempt is recorded as failed, local state is preserved, and
  `repo_status` reports stale/unavailable rather than current

#### Scenario: Inconsistent local state refuses service

- **WHEN** `repo_file` is called while the working tree is dirty or the
  index SHA does not match the local SHA
- **THEN** the tool returns a structured staleness refusal instead of file
  content

### Requirement: Repository evidence retrieval with provenance

Hermes SHALL be able to answer repository questions through read-only tools
that return content with commit SHA and file-path provenance. Search
results with no match SHALL return a structured no-evidence result. Tool
errors SHALL be structured (ATLAS-TOOL-002), the server SHALL expose no
generic query/shell/file/HTTP surface (ATLAS-TOOL-003), and every call
SHALL be auditable via an append-only redacted log (ATLAS-TOOL-004).

#### Scenario: Repository question answered with commit and file reference

- **WHEN** Hermes is asked a repository evidence question with the
  `atlas-repo` tools available
- **THEN** the answer cites at least one file path and commit SHA drawn
  from tool results

#### Scenario: No matching repository evidence

- **WHEN** `repo_search` finds no match for a query
- **THEN** it returns a structured no-repository-evidence result, never
  fabricated content

### Requirement: No routine build

Subtensor compilation SHALL NOT be required for normal operation and SHALL
NOT run as a scheduled job. A targeted manual build or test MAY occur only
under a separately approved specification after confirming device
resources. (ATLAS-REPO-009)

#### Scenario: No build in the update pipeline

- **WHEN** an update completes
- **THEN** no compilation or test execution of the tracked repository was
  invoked by any Atlas component
