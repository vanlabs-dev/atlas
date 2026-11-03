## MODIFIED Requirements

### Requirement: The model only edits files inside the allowed scope

Each attempt SHALL use at most one headless model session, in a worktree
separate from the live tree. After the session, the job SHALL compare the
worktree changes against a fixed allowed-path list kept in code. The list
SHALL admit only the knowledge corpus,
`knowledge/supersession-markers.json`, and `docs/decisions.md`. Chain
reader code and configs SHALL NOT be in the list. Only modifications of
files that exist in the base commit SHALL pass: an added, renamed, copied
or deleted file SHALL block the attempt, even under an allowed path. Any
change to tests, the chain-read probe, chain reader code or configs, the
upgrade job itself, its prompt or allowed-path list, any other file under
`docs/`, `AGENTS.md`, systemd units, or secrets SHALL block the attempt.
The job SHALL repeat the scope check on the exact tree it commits,
immediately before the commit, so a file written after the first check
blocks the push.

#### Scenario: Edit outside scope
- **WHEN** the session modifies a file under any `tests/` directory
- **THEN** the attempt fails at the scope gate, nothing is pushed, and the
  report names the file

#### Scenario: Probe edited
- **WHEN** the session modifies the probe or the metadata decoder
- **THEN** the attempt fails at the scope gate and nothing is pushed

#### Scenario: Chain reader edited
- **WHEN** the session modifies `livedata/atlas_live.py` or
  `livedata/config.json`
- **THEN** the attempt fails at the scope gate and nothing is pushed

#### Scenario: New file under an allowed path
- **WHEN** the session creates a new file under `knowledge/corpus/`
- **THEN** the attempt fails at the scope gate and nothing is pushed

#### Scenario: File written during the gates
- **WHEN** a file appears in the worktree after the scope gate passed and
  before the commit
- **THEN** the commit is not made, the attempt fails at the scope gate, and
  nothing is pushed

#### Scenario: Live tree untouched during edits
- **WHEN** an attempt is editing
- **THEN** the live tree used by running services has no uncommitted
  change and stays on `origin/main`

### Requirement: Nothing reaches main unless every gate passes

The job SHALL push only after, in order: the goal gate passes, the scope
gate passes, the citation gate passes, the sandbox canary passes, every
`*/tests` suite in the repo passes inside the sandbox, the chain-read probe
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

### Requirement: Durable state with bounded retry

The job SHALL keep durable run state that survives a restart: spec,
attempt number, current step, timestamps, and last error. Each step SHALL
run under its own timeout, so the job records its own failures. Each run
SHALL also have one overall deadline that ends before the service unit's
start timeout. Every step before the push SHALL run under the smaller of
its own timeout and the time left before the deadline, less a reserve for
the push, readback, pull and activation. The job SHALL NOT start the push
when less than that reserve remains; it SHALL fail the attempt at a
`deadline` gate instead. A failed attempt SHALL retry after 1 hour, then
after 4 hours. After the third failed attempt for one spec, the state
SHALL become `blocked` and the job SHALL NOT retry that spec until the
operator clears it. Each attempt SHALL use its own branch, and a failed
attempt SHALL keep its branch for inspection. A live spec newer than the
one in state SHALL start at attempt 1, whatever the old state was.

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

#### Scenario: Deadline before the push
- **WHEN** the steps before the push leave less time than the push reserve
- **THEN** nothing is pushed, the attempt fails at the `deadline` gate, and
  the report uses that gate's fixed wording

#### Scenario: Deadline inside the unit timeout
- **WHEN** the tests read the service unit
- **THEN** the run deadline is shorter than its `TimeoutStartSec`

### Requirement: Environment preflight uses no attempt

Before it counts an attempt, the job SHALL check the environment:
- Claude auth works.
- The repo's author identity, read without the job's own identity
  overrides, is `vaNlabs <vanlabs@pm.me>`.
- The live tree has no uncommitted changes.
- After a fetch, the live tree's `HEAD` is an ancestor of `origin/main`.
- The chain-read probe passes on the live tree's chain readers.
- The tracked clone has a release anchor for the live spec and for the
  corpus spec.

When a check fails, the state SHALL become `waiting` with that reason. The
attempt count SHALL stay unchanged and no model session SHALL run. One
report per spec and reason SHALL be sent, in fixed wording that does not
quote raw command output. Later timer runs SHALL check again. The job SHALL
repeat the ancestry check immediately before the push. A failure at that
point SHALL fail the attempt at the push gate, and nothing SHALL be pushed.

#### Scenario: Claude login expired
- **WHEN** the Claude auth check fails for spec 451
- **THEN** the state is `waiting`, the attempt count is unchanged, and one
  report says the Claude login needs renewing

#### Scenario: Local commit in the live tree
- **WHEN** the live tree has a commit that `origin/main` does not contain
- **THEN** no attempt is used, nothing is pushed, and one report names the
  live tree as diverged

#### Scenario: Live tree behind origin
- **WHEN** the live tree is behind `origin/main` with no local commits
- **THEN** preflight passes

#### Scenario: Chain readers drifted
- **WHEN** the live runtime renamed a storage item Atlas reads
- **THEN** the state is `waiting`, no attempt or model session is used, and
  one report says the chain readers need an operator fix

#### Scenario: No release anchor
- **WHEN** the clone has neither a `v<live>` tag nor a commit that
  introduced the live `spec_version`
- **THEN** the state is `waiting`, no attempt is used, and the diff is never
  taken to the clone HEAD

## ADDED Requirements

### Requirement: Gates run in a sandbox without secrets

The job SHALL run every test suite and the chain-read probe on the edited
tree inside an unprivileged sandbox. In the sandbox:
- the worktree SHALL be read-only;
- the home directory and temporary directory SHALL be private and empty;
- the operator's SSH keys, Hermes home, Claude home, the repo `.env`, the
  user and system bus, and the container runtime socket SHALL NOT be
  reachable;
- the environment SHALL be cleared to a fixed minimal set;
- privilege escalation SHALL NOT be possible;
- test suites SHALL have no network; the probe SHALL have network.

Before the gates, the job SHALL run a canary through the same sandbox
builder. The canary SHALL check each of those properties from inside. Any
property that does not hold, or a canary that cannot run, SHALL fail the
attempt at a `sandbox` gate. Nothing SHALL be pushed.

#### Scenario: Secret reachable
- **WHEN** the canary can open a file under the Hermes home
- **THEN** the attempt fails at the `sandbox` gate and no suite runs

#### Scenario: Sandbox unavailable
- **WHEN** the sandbox tool is missing or fails to start
- **THEN** the attempt fails closed at the `sandbox` gate; the gates never
  run unsandboxed

#### Scenario: Test reaches the network
- **WHEN** a test suite opens a network connection
- **THEN** the connection fails inside the sandbox

### Requirement: Edit session reads only its inputs

The model session SHALL be able to read only the upgrade worktree, the
live-spec source export, and the job's own working directory. The session
configuration SHALL deny reads of SSH keys, the Hermes home, the Claude
home, and any `.env` file. The session SHALL have no shell and no web
tools.

#### Scenario: Secret read attempted
- **WHEN** the session tries to read a file under `~/.hermes`
- **THEN** the read is denied

### Requirement: Spec diff ends at the live release

The diff and commit log given to the model SHALL run from the release
anchor of the corpus spec to the release anchor of the live spec. A spec's
release anchor SHALL be its `v<spec>` tag when that tag exists in the
tracked clone. Otherwise it SHALL be the commit that introduced
`spec_version: <spec>` in the runtime source. The runtime source at an
anchor SHALL state that spec, and the live anchor SHALL be an ancestor of
the clone HEAD. The model SHALL read the subtensor source as exported at
the live anchor, not the clone working tree. The job SHALL take the clone
lock while it resolves anchors, builds the diff and exports the source.

#### Scenario: Clone ahead of live
- **WHEN** the live spec is 486, the clone HEAD is at 487, and tag `v486`
  exists
- **THEN** the diff ends at `v486`, and the source the model reads contains
  no change made after `v486`

#### Scenario: No tag for the live spec
- **WHEN** the live spec is 472 and no `v472` tag exists
- **THEN** the anchor is the commit that introduced `spec_version: 472`,
  and the report or prompt names that anchor kind

### Requirement: Corpus citations match this run's reads

After the goal gate, the job SHALL check every corpus line the edit adds or
changes. A finalized block number cited in such a line SHALL be a block the
job read in this run, or a block the base corpus already cites. No such
line SHALL name a spec number above the live spec: the model is given no
source past the live release, so such a number can only be unshipped
code. A violation SHALL fail the attempt at a `citation` gate, naming the
line.

#### Scenario: Invented block
- **WHEN** an added corpus line cites finalized block 9999999, which this
  run did not read
- **THEN** the attempt fails at the `citation` gate

#### Scenario: Future spec stated as live
- **WHEN** live is 486 and an added line says spec 487 is live
- **THEN** the attempt fails at the `citation` gate
