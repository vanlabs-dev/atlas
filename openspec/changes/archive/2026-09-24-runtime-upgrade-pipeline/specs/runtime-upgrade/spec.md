## Purpose

Brings Atlas up to date on the Pi, without an operator, when the live
runtime spec changes, with every gate enforced in code rather than in a
model prompt.

## ADDED Requirements

### Requirement: Upgrade runs start only from a live enactment

At the start of each run, the upgrade job SHALL read the live runtime
`spec_version` itself through the keyless live-data read. It SHALL start a
run only when that live spec differs from the corpus spec. A repository
spec that is ahead of the live spec SHALL NOT start a run. When corpus and
live agree, the job SHALL exit without calling the model and without a
report.

#### Scenario: Live spec moved
- **WHEN** the live spec is 451 and the corpus spec is 450
- **THEN** a run starts for spec 451

#### Scenario: Only the repo moved
- **WHEN** the repo spec is 452 and the live and corpus specs are 451
- **THEN** no run starts and no model session is used

### Requirement: Source clone must cover the live spec

Before any model session, the job SHALL fetch the tracked subtensor clone
and compare its `spec_version` with the live spec. When the clone is still
below the live spec, the state SHALL become `waiting`. A waiting run SHALL
NOT use an attempt or a model session, SHALL send one `waiting` report per
spec, and SHALL be checked again on each later timer run.

#### Scenario: Clone lags
- **WHEN** the live spec is 451 and the clone's `spec_version` is 450 after
  a fetch
- **THEN** the state is `waiting`, the attempt count is unchanged, no model
  session runs, and one `waiting` report is sent

### Requirement: The model only edits files inside the allowed scope

Each attempt SHALL use at most one headless model session, in a worktree
separate from the live tree, with read-only access to the subtensor clone.
After the session, the job SHALL compare the branch diff against a fixed
allowed-path list kept in code. The list SHALL admit only the knowledge
corpus, `knowledge/supersession-markers.json`, `docs/decisions.md`, and the
chain reader code and configs. Any change to tests, the chain-read probe
or its metadata decoder, the upgrade job itself, its prompt or
allowed-path list, any other file under `docs/`, `AGENTS.md`, systemd
units, or secrets SHALL block the attempt.

#### Scenario: Edit outside scope
- **WHEN** the session modifies a file under any `tests/` directory
- **THEN** the attempt fails at the scope gate, nothing is pushed, and the
  report names the file

#### Scenario: Probe edited
- **WHEN** the session modifies the probe or the metadata decoder
- **THEN** the attempt fails at the scope gate and nothing is pushed

#### Scenario: Live tree untouched during edits
- **WHEN** an attempt is editing
- **THEN** the live tree used by running services has no uncommitted
  change and stays on `origin/main`

### Requirement: The edit must reach the live spec

After the session, the job SHALL regenerate the corpus hash manifest
itself, taking the grounded spec from the corpus sources file. The attempt
SHALL fail when the grounded spec is not the live spec or when the branch
diff is empty. A pushed run SHALL leave the corpus spec equal to the live
spec.

#### Scenario: Empty edit
- **WHEN** the session changes no file
- **THEN** the attempt fails at the goal gate and nothing is pushed

#### Scenario: Spec not grounded
- **WHEN** the session edits the corpus but the sources file still states
  spec 450 while live is 451
- **THEN** the attempt fails at the goal gate, naming both specs

### Requirement: Nothing reaches main unless every gate passes

The job SHALL push only after, in order: the goal gate passes, the scope
gate passes, every `*/tests` suite in the repo passes, the chain-read probe
passes against the live chain, and corpus ingest into the live store stages
with no rejected unit. The push SHALL be a fast-forward of `main`. The job
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

### Requirement: Activation follows a confirmed push

The job SHALL activate the new corpus only after the remote `main` reads
back as the pushed commit and the live tree fast-forwards to it. When any
step before activation fails, the previously active corpus SHALL stay
active and the live tree SHALL equal `origin/main`.

#### Scenario: Push fails
- **WHEN** the push fails
- **THEN** the old corpus stays active and the live tree is unchanged

#### Scenario: Push confirmed
- **WHEN** the remote read-back matches the pushed commit
- **THEN** the live tree fast-forwards, and the new corpus is activated
  with the actor `atlas-upgrade`

### Requirement: Durable state with bounded retry

The job SHALL keep durable run state that survives a restart: spec,
attempt number, current step, timestamps, and last error. Each step SHALL
run under its own timeout, so the job records its own failures. A failed
attempt SHALL retry after 1 hour, then after 4 hours. After the third
failed attempt for one spec, the state SHALL become `blocked` and the job
SHALL NOT retry that spec until the operator clears it. Each attempt SHALL
use its own branch, and a failed attempt SHALL keep its branch for
inspection. A live spec newer than the one in state SHALL start at attempt
1, whatever the old state was.

#### Scenario: Third failure
- **WHEN** the third attempt for spec 451 fails
- **THEN** the state is `blocked`, a blocked report is sent, and later timer
  runs do not start spec 451

#### Scenario: Operator clears a block
- **WHEN** the operator clears spec 451 while it is `blocked`
- **THEN** the next timer run starts spec 451 at attempt 1

#### Scenario: Newer spec supersedes
- **WHEN** spec 451 is `blocked` and the live spec moves to 452
- **THEN** a run for spec 452 starts at attempt 1 and the spec 451 branches
  are kept

#### Scenario: Restart mid-run
- **WHEN** the Pi restarts or the service is killed while a run is in
  progress
- **THEN** the next timer run finds the saved `running` state with no live
  run holding the lock, and counts it as a failed attempt

### Requirement: Every run ends in exactly one reported outcome

Each run that starts an attempt or changes state SHALL end in exactly one
Telegram report: `updated` (spec, commit, summary of changes), `retrying`
(failing gate, next attempt time), `blocked` (failing gate, branch name),
`stalled` (an interrupted run, reported in place of `retrying` or
`blocked` for that attempt), or `waiting` (clone spec and live spec).

#### Scenario: Stalled run
- **WHEN** the next timer run finds an interrupted run
- **THEN** one `stalled` report is sent for that attempt and no other
  report for it

#### Scenario: Successful upgrade
- **WHEN** every gate passes and activation completes
- **THEN** one `updated` report is sent and no other report for that run
