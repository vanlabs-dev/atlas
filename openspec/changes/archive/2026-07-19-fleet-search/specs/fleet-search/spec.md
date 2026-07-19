## ADDED Requirements

### Requirement: Shared full-text index scoped by netuid and epoch

The fleet-search component SHALL maintain a single full-text index over the
maintained subnet-repo clones, stored in the fleet store (`var/fleet/fleet.db`)
as `fleet_files` (rows keyed uniquely by `(netuid, path)`, carrying `epoch`,
`indexed_sha`, byte size, and indexed timestamp), a companion FTS5 virtual
table joined by rowid, and a per-slot `index_state` row (indexed SHA, indexer
schema version, file count). Index rows SHALL carry the netuid and the epoch of
the slot they were indexed from, so a search can be scoped to one netuid and so
a recycled netuid's distinct projects never share index rows. The index tables
SHALL be created idempotently by the indexer without modifying the reconcile
store's own schema.

#### Scenario: Two subnets with the same path do not collide

- **WHEN** two different netuids each have a file at the same relative path and
  both are indexed
- **THEN** both files are retained as distinct rows keyed by `(netuid, path)`
  and each is attributable to its own netuid

#### Scenario: Index rows are attributable to a netuid and epoch

- **WHEN** a slot at a given epoch is indexed
- **THEN** every index row written for it records that netuid and epoch

### Requirement: Index generalizes the repotrack indexer without forking it

The fleet-search indexer SHALL reuse the subtensor tracker's pure indexing
helpers — the indexability filter (extension allowlist, maximum file size, and
binary sniff), the working-tree walk, and the local-commit-SHA read — rather
than duplicating them, and SHALL NOT modify the single-repo `run_index` path or
any other subtensor-tracker behavior. The index SHALL only read files already
materialized in a clone's checked-out default-branch working tree; it SHALL NOT
check out other branches, fetch submodules, or build, test, install, or execute
any subnet code.

#### Scenario: Only allowlisted, in-size, non-binary files are indexed

- **WHEN** a clone's working tree contains files of assorted extensions, sizes,
  and binary content
- **THEN** only files whose extension is allowlisted, whose size is within the
  configured maximum, and which are not binary are indexed; the rest are skipped

#### Scenario: Indexing never executes subnet code

- **WHEN** a slot is indexed
- **THEN** the indexer performs only file reads and store writes, invoking no
  build, test, install, checkout of another branch, submodule fetch, or
  execution of repository contents

### Requirement: Reconcile keeps the index in step with the clones

Each reconcile pass SHALL update the index in step with the clone actions it
performs: a new clone or an active re-point SHALL fully index the resulting
working tree; a re-point SHALL purge the prior epoch's index rows and a discard
SHALL purge all of that netuid's index rows, in the same transaction as the slot
transition so no search ever returns a hit for a removed slot or superseded
project; and a no-change update SHALL perform no indexing work.

An update SHALL index incrementally ONLY when it is a clean fast-forward whose
change range is not truncated and the slot already has a current-schema index at
the same epoch; in every other case — a truncated range, a non-fast-forward
(history rewritten) advance, an advance whose change range could not be
collected, or a slot with no valid current baseline — it SHALL fall back to a
full index of the working tree, so the index never silently omits changed files.

Indexing SHALL be per-slot fail-closed and transactionally isolated from the slot
transition: the slot transition SHALL be committed first, the index SHALL be
applied in a separate transaction, and a failure to index one slot SHALL roll
back only that index, be recorded, and SHALL NOT fail the reconcile pass, undo
the recorded clone/update, or affect other slots.

#### Scenario: A clean fast-forward indexes only changed paths

- **WHEN** a reconcile pass advances an active, already-indexed clone by a clean
  fast-forward with a complete (non-truncated) change range
- **THEN** the index for that netuid is updated for the changed paths only and
  its `index_state` records the new local SHA

#### Scenario: A truncated or rewritten-history advance triggers a full index

- **WHEN** a reconcile pass advances a clone whose change range is truncated, or
  whose advance was a non-fast-forward reset, or whose range could not be
  collected
- **THEN** that netuid is fully reindexed from its working tree rather than
  patched from an incomplete path list

#### Scenario: An advance on an unindexed slot fully indexes it

- **WHEN** a reconcile pass advances an active clone that has no current-schema
  index baseline
- **THEN** the slot is fully indexed rather than incrementally patched over an
  absent baseline

#### Scenario: A re-point does not leak the previous project's files

- **WHEN** a slot's identity churns and the slot is re-pointed to a different
  repository at a new epoch
- **THEN** the prior epoch's index rows are purged and only the new project's
  files are searchable for that netuid

#### Scenario: A discard purges the netuid from the index

- **WHEN** a slot is discarded because its subnet deregistered
- **THEN** all of that netuid's index rows are removed and it no longer appears
  in search results

#### Scenario: One slot's index failure does not fail the pass or lose the advance

- **WHEN** indexing one slot raises an error during a reconcile pass
- **THEN** only that slot's index write is rolled back, the recorded clone/update
  for that slot is preserved, the failure is recorded, and the pass completes and
  reconciles and indexes the other slots normally

### Requirement: Standalone index command backfills and repairs

The fleet-search component SHALL provide a standalone command that indexes the
already-cloned fleet on demand — reindexing active slots whose recorded indexed
SHA differs from the clone's local SHA (or whose indexer schema version changed),
optionally scoped to one netuid, and rebuilding from scratch when asked. This
command SHALL be usable to backfill slots that were cloned before the index
existed, without requiring those slots to change first.

#### Scenario: Backfilling an unindexed but already-cloned slot

- **WHEN** the index command runs against an active clone that has no
  `index_state` row
- **THEN** the slot's working tree is fully indexed and its `index_state` is
  recorded

#### Scenario: Rebuild reindexes from scratch

- **WHEN** the index command is run in rebuild mode for a slot
- **THEN** the slot's existing index rows are discarded and the working tree is
  fully reindexed at the current local SHA

### Requirement: Read-only fleet code search with cited provenance

The fleet-search MCP surface SHALL provide a `fleet_search` tool that full-text
searches the fleet index, optionally scoped to one netuid, ranks results across
the searched scope, and returns for each hit the netuid, the slot's
repository identity, the file path, the commit SHA the file was indexed at, and
a matching snippet, so every result is attributable. A search with no scope
SHALL rank across all indexed subnets. A search that matches nothing SHALL
return a structured no-evidence result rather than an empty or fabricated
answer. The surface SHALL be read-only: the store SHALL be opened read-only and
no tool SHALL mutate a clone or run any mutating git command.

#### Scenario: Global search ranks across all subnets

- **WHEN** `fleet_search` is called with a query and no netuid
- **THEN** matching files across all indexed subnets are returned ranked, each
  citing its netuid, repository, path, and indexed SHA

#### Scenario: Netuid-scoped search restricts to one subnet

- **WHEN** `fleet_search` is called with a query and a netuid
- **THEN** only that netuid's matching files are returned

#### Scenario: No match returns structured no-evidence

- **WHEN** `fleet_search` matches no indexed file
- **THEN** a structured no-fleet-evidence result is returned instructing that
  the fleet cannot support an answer, not an empty success

#### Scenario: Query operators cannot break or inject the match

- **WHEN** `fleet_search` is called with a query containing full-text search
  operators or punctuation
- **THEN** the query is reduced to allowlisted search terms and executed safely,
  returning results or structured no-evidence rather than erroring

### Requirement: Bounded, staleness-guarded file read

The fleet-search MCP surface SHALL provide a `fleet_file` tool that returns a
bounded slice of one file from a given netuid's clone at that clone's current
local commit. It SHALL reject paths that escape the netuid's clone directory. It
SHALL serve content only when the slot is active, its working tree is clean, and
its recorded indexed SHA equals the clone's local SHA; otherwise it SHALL return
a structured staleness/unavailable refusal rather than serving mixed state.

#### Scenario: Serving a file at a consistent, current state

- **WHEN** `fleet_file` is asked for a path in an active, clean slot whose index
  matches its local SHA
- **THEN** a bounded slice of the file is returned citing the netuid, path, and
  commit SHA

#### Scenario: Refusing a path that escapes the clone

- **WHEN** `fleet_file` is asked for a path containing traversal outside the
  netuid's clone directory
- **THEN** it returns a structured invalid-path refusal and serves no content

#### Scenario: Refusing mixed state

- **WHEN** a slot's clone has advanced past its recorded indexed SHA, or its
  tree is dirty
- **THEN** `fleet_file` returns a structured staleness refusal rather than
  serving content

#### Scenario: Refusing an unknown or uncloned netuid

- **WHEN** `fleet_file` is asked for a netuid with no active clone (absent,
  no-repo, quarantined, or otherwise not materialized)
- **THEN** it returns a structured unavailable refusal and serves no content

### Requirement: Fleet and index freshness reporting

The fleet-search MCP surface SHALL provide a `fleet_status` tool reporting fleet
and index coverage — counts of indexed and stale slots and the total indexed
file count, and, when given a netuid, that slot's status, local SHA, indexed
SHA, staleness, and file count. It SHALL report staleness and unavailability
honestly and SHALL NOT present index contents as current when a slot's clone has
advanced past its indexed SHA.

#### Scenario: Reporting coverage across the fleet

- **WHEN** `fleet_status` is called with no netuid
- **THEN** it returns index coverage including indexed-slot and stale-slot counts
  and the total indexed file count

#### Scenario: Reporting a stale slot honestly

- **WHEN** `fleet_status` is called for a netuid whose clone has advanced past
  its recorded indexed SHA
- **THEN** it reports that slot as stale rather than current

### Requirement: Fleet-search fails closed and audits every call

The fleet-search MCP surface SHALL fail closed: when the fleet store or the
index tables are absent it SHALL return a structured unavailable result for
every tool rather than a false or empty success. Every tool call SHALL be
recorded to a size-capped, append-only, secret-redacted audit log beside the
store, and audit-log failure SHALL never break the tool path. Every error
returned SHALL be structured (category, component, retry-safety, a user-safe
message, and a correlation id).

#### Scenario: Unavailable index fails closed

- **WHEN** any fleet-search tool is called before the index has been built
- **THEN** it returns a structured `fleet-search-unavailable` result, not an
  empty or fabricated success

#### Scenario: Every call is audited

- **WHEN** a fleet-search tool call completes, whether success or error
- **THEN** a redacted, size-capped audit line recording the tool, parameters,
  and outcome is appended, and any failure to write it does not affect the
  returned result
