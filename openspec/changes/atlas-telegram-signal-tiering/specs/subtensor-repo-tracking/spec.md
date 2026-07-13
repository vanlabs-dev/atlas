## MODIFIED Requirements

### Requirement: Change record per tracked commit range

For every change to the tracked branch, Atlas SHALL record: previous SHA, new
SHA, commit list, changed file paths, additions and deletions where available,
tags or releases encountered in the range, retrieval timestamp, whether indexing
succeeded, a machine-generated summary stored with a fixed label marking it as a
summary (not verified effect), and the runtime `spec_version` at both the
previous and new heads where the runtime manifest is present. The
`spec_version` values SHALL be read from the tracked clone's runtime manifest
(e.g. `runtime/src/lib.rs`) for the recorded SHAs; when the manifest or field is
absent, the values SHALL be recorded as unknown rather than guessed.
(ATLAS-REPO-005)

#### Scenario: Change record written on update

- **WHEN** an update advances the tracked branch
- **THEN** a change record with all required fields is persisted, and its summary
  text carries the machine-summary label

#### Scenario: Runtime spec_version delta recorded

- **WHEN** an update advances the tracked branch and the runtime manifest is
  present at both heads
- **THEN** the change record captures the previous-head and new-head
  `spec_version`, enabling a spec delta to be derived without re-reading the clone

#### Scenario: Missing runtime manifest recorded as unknown

- **WHEN** the runtime manifest or its `spec_version` field cannot be read at a
  recorded head
- **THEN** that head's `spec_version` is recorded as unknown and the update still
  succeeds
