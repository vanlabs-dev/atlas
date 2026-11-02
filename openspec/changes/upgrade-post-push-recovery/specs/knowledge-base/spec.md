## ADDED Requirements

### Requirement: Status reports the active run

`knowledge_status` SHALL report the active run's id, coverage date, and
corpus files, taken from that run and not from the newest ingest. When a
staged run was ingested after the active run, the result SHALL name it as
`staged_newer_run`, with its id and coverage date. Otherwise the field
SHALL be null.

#### Scenario: Newer run staged, not active
- **WHEN** run 482 is active and run 486 is staged later
- **THEN** the status shows run 482 with its own coverage date, and
  `staged_newer_run` names run 486

#### Scenario: Newest run active
- **WHEN** the active run is the newest ingest
- **THEN** `staged_newer_run` is null
