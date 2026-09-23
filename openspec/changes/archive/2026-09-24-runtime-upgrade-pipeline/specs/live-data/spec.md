## MODIFIED Requirements

### Requirement: Live runtime spec_version changes are recorded

The live-data component SHALL persist the last-seen live runtime `spec_version`
(with its reference block and observation time) and SHALL record a durable
upgrade event whenever a validated live chain-head response reports a
`spec_version` different from the last recorded one. The `spec_version` SHALL
be read first through keyless RPC at a finalized block, with TaoStats as
fallback only when every RPC endpoint fails. The read SHALL run on its own
hourly schedule and SHALL NOT depend on the repository update succeeding.
The upgrade record SHALL be
written only from a live, typed-validated response (never from stale or
unvalidated data) and SHALL capture the previous `spec_version`, the new
`spec_version`, the reference block, and the source used. A restart SHALL NOT
re-emit an upgrade for an already-recorded `spec_version`.

#### Scenario: New live spec_version records an upgrade

- **WHEN** a validated live chain-head reports a `spec_version` different from the
  last recorded one
- **THEN** an upgrade event is persisted with the previous `spec_version`, the new
  `spec_version`, and the reference block, and the last-seen value is advanced

#### Scenario: Unchanged spec_version records no upgrade

- **WHEN** a validated live chain-head reports the same `spec_version` as the last
  recorded one
- **THEN** no upgrade event is written and the last-seen observation time is
  updated

#### Scenario: Upgrade detection never uses stale data

- **WHEN** a live chain-head request fails or its response fails validation
- **THEN** no `spec_version` upgrade is recorded and the last recorded value is
  left unchanged

#### Scenario: TaoStats down

- **WHEN** TaoStats fails and a keyless RPC endpoint answers
- **THEN** the `spec_version` is read and recorded from RPC with source `rpc`

#### Scenario: Repository update failing

- **WHEN** the repository update service fails
- **THEN** the hourly `spec_version` read still runs
