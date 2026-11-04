## ADDED Requirements

### Requirement: The edit session knows the tested corpus facts
The edit session's prompt SHALL list every corpus fact the knowledge suite
tests (battery marker groups and retrieval evaluation markers), generated
at run time, with the instruction to keep them retrievable unless the live
release's source changes them.

#### Scenario: Prompt lists tested facts
- **WHEN** the job builds the edit-session prompt
- **THEN** the prompt contains every grounded battery marker group and
  every retrieval evaluation marker

## MODIFIED Requirements

### Requirement: Nothing reaches main unless every gate passes

The job SHALL push only after, in order: the goal gate passes, the scope
gate passes, the citation gate passes, the sandbox canary passes, every
`*/tests` suite in the repo passes inside the sandbox (including the
knowledge retrieval evaluation and the battery retrieval check, which fail
when an edited corpus no longer yields an expected fact), the chain-read probe
passes against the live chain inside the sandbox, corpus ingest into the
live store stages with no rejected unit, and the scope check on the
committed tree passes. The push SHALL be a fast-forward of `main`. The job
SHALL NOT force-push. Commits SHALL be authored as
`vaNlabs <vanlabs@pm.me>`, and the job SHALL verify the author before
pushing.

#### Scenario: A suite fails
- **WHEN** any test suite exits non-zero
- **THEN** nothing is pushed and the outcome is blocked or retrying, naming
  the suite

#### Scenario: Remote moved ahead
- **WHEN** the push is rejected as non-fast-forward
- **THEN** the job does not force-push, and the attempt fails with the
  reason recorded

#### Scenario: Corpus edit drops a battery fact
- **WHEN** the edited corpus no longer yields a grounded battery fact in
  the top 5 search results
- **THEN** the knowledge suite fails, nothing is pushed, and the staged
  run is not activated
