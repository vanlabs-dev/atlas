## MODIFIED Requirements

### Requirement: Index generalizes the repotrack indexer without forking it

The fleet-search indexer SHALL reuse the subtensor tracker's pure indexing
helpers (the indexability filter (extension allowlist, maximum file size, and
binary sniff), the working-tree walk, the clone containment check, and the
local-commit-SHA read) rather than duplicating them, and SHALL NOT modify the
single-repo `run_index` path or any other subtensor-tracker behavior, except
that both indexers skip symlinks and out-of-clone paths through the shared
containment check. The index SHALL only read files already materialized in a
clone's checked-out default-branch working tree; it SHALL NOT check out other
branches, fetch submodules, or build, test, install, or execute any subnet
code.

#### Scenario: Only allowlisted, in-size, non-binary files are indexed

- **WHEN** a clone's working tree contains files of assorted extensions, sizes,
  and binary content
- **THEN** only files whose extension is allowlisted, whose size is within the
  configured maximum, and which are not binary are indexed; the rest are skipped

#### Scenario: Linked paths are never indexed

- **WHEN** a clone's working tree holds symlinked files or folders
- **THEN** no index row is written for a path that passes through a link, and
  an incremental pass removes any old row for such a path

#### Scenario: Indexing never executes subnet code

- **WHEN** a slot is indexed
- **THEN** the indexer performs only file reads and store writes, invoking no
  build, test, install, checkout of another branch, submodule fetch, or
  execution of repository contents

### Requirement: Bounded, staleness-guarded file read

The fleet-search MCP surface SHALL provide a `fleet_file` tool that returns a
bounded slice of one file from a given netuid's clone at that clone's current
local commit. It SHALL reject paths that escape the netuid's clone directory or
pass through a symlink. It SHALL serve content only when the slot is active,
its working tree is clean, and its recorded indexed SHA equals the clone's local
SHA; otherwise it SHALL return a structured staleness/unavailable refusal rather
than serving mixed state.

#### Scenario: Serving a file at a consistent, current state

- **WHEN** `fleet_file` is asked for a path in an active, clean slot whose index
  matches its local SHA
- **THEN** a bounded slice of the file is returned citing the netuid, path, and
  commit SHA

#### Scenario: Refusing a path that escapes the clone

- **WHEN** `fleet_file` is asked for a path containing traversal outside the
  netuid's clone directory, or a path that passes through a symlink
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
