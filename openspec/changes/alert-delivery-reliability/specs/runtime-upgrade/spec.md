## ADDED Requirements

### Requirement: Failure reports use fixed wording

A `retrying`, `blocked` or `stalled` report SHALL describe the failing
gate with a fixed phrase for that gate. It SHALL NOT quote raw command
output, error text or model output. The raw detail SHALL stay in local
state and on stderr.

#### Scenario: Auth error during an attempt
- **WHEN** an attempt fails at the edit gate with "Failed to authenticate:
  OAuth token has expired"
- **THEN** the `retrying` report names the edit gate in fixed words, and
  the scrubber passes it

#### Scenario: Unknown gate
- **WHEN** a gate with no fixed phrase fails
- **THEN** the report uses a generic fixed phrase that names the gate

### Requirement: Exit status reflects unexpected errors only

A run that ends in a recorded outcome SHALL exit 0. This includes a
reported failure, a wait, or a live spec that cannot be read. Only an
unexpected error SHALL exit non-zero, so a unit failure means the job
itself is broken.

#### Scenario: Live spec unavailable
- **WHEN** the chain RPC fails while reading the live spec
- **THEN** the run prints the reason and exits 0

#### Scenario: Attempt failed and reported
- **WHEN** an attempt fails at the test gate and the `retrying` report is
  sent or kept for retry
- **THEN** the run exits 0

#### Scenario: Crash
- **WHEN** an unhandled exception ends the run
- **THEN** the run exits non-zero and the unit failure notifier pages
