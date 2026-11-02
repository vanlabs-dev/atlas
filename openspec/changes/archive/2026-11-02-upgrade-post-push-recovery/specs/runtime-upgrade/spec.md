## ADDED Requirements

### Requirement: Environment preflight uses no attempt

Before it counts an attempt, the job SHALL check the environment:
- Claude auth works.
- The repo's author identity, read without the job's own identity
  overrides, is `vaNlabs <vanlabs@pm.me>`.
- The live tree has no uncommitted changes.
- After a fetch, the live tree's `HEAD` is an ancestor of `origin/main`.

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

### Requirement: The active knowledge run matches the live corpus

On every timer run, before deciding that no upgrade is needed, the job SHALL
compare the active knowledge run's file hashes with `hashes.json` in the
live tree. On a mismatch, when the live tree is clean and has no local
commits, the job SHALL activate a staged run that meets all three of these
conditions:
- The job ingested it (actor `atlas-upgrade`).
- Its file hashes equal `hashes.json`.
- Its validation report has no rejected units.

The job SHALL report that activation once. When no such run exists, the job
SHALL send one report with the exact commands to ingest and activate. It
SHALL NOT report again for the same `hashes.json`.

#### Scenario: Pushed corpus never activated
- **WHEN** the live tree carries the spec-486 corpus, the active run is
  spec 482, and a clean staged run ingested by `atlas-upgrade` matches
- **THEN** the job activates that run and sends one report naming it

#### Scenario: No matching staged run
- **WHEN** the active run differs from `hashes.json` and no staged run
  qualifies
- **THEN** nothing is activated and one report gives the ingest and
  activate commands

### Requirement: Gateway restarts after new code

After a run's pull brings in commits that change files other than the
corpus, the supersession markers or `docs/`, the job SHALL restart `hermes-gateway`, so that its MCP
servers load the new code. It SHALL restart only when the restart is safe:
- The unit is active.
- The gateway's state file is fresh.
- The state file shows no active agent and no active work.

After a restart, the job SHALL confirm the unit is active again. When the
restart is unsafe or fails, the job SHALL send one "restart needed" report
and SHALL retry on later timer runs until a restart succeeds. A pending or
failed restart SHALL NOT change the upgrade outcome. The `updated` report
SHALL list those code commits, capped at a fixed
number with a count of the rest.

#### Scenario: Pull brings code
- **WHEN** an upgrade's pull brings in a `livedata/` change and the gateway
  is idle
- **THEN** the gateway is restarted, and the `updated` report lists that
  commit

#### Scenario: Gateway busy
- **WHEN** the gateway shows an active agent
- **THEN** no restart happens, one "restart needed" report is sent, and a
  later run restarts the gateway once it is idle

#### Scenario: Corpus-only pull
- **WHEN** the pull brings in only the upgrade's corpus and
  `docs/decisions.md` commit
- **THEN** the gateway is not restarted

## MODIFIED Requirements

### Requirement: Activation follows a confirmed push

The job SHALL activate the new corpus only after the remote `main` reads
back as the pushed commit and the live tree fast-forwards to it. When any
step before activation fails, the previously active corpus SHALL stay
active and the live tree SHALL equal `origin/main`. Before the push, the
job SHALL save the commit and the staged run id in its durable state. A
failure at the read-back, pull, or activate gate SHALL block the spec at
once. That report SHALL give the exact commands to pull the live tree and
activate the run. Such a block SHALL NOT clear to `idle` when the corpus
spec reaches the live spec. While the pull is what blocks, each timer run
SHALL retry a fast-forward pull when the live tree is clean and has no
local commits. The block SHALL clear only when the live tree contains the
pushed commit and the active knowledge run matches `hashes.json`.

#### Scenario: Push fails
- **WHEN** the push fails
- **THEN** the old corpus stays active and the live tree is unchanged

#### Scenario: Push confirmed
- **WHEN** the remote read-back matches the pushed commit
- **THEN** the live tree fast-forwards, and the new corpus is activated
  with the actor `atlas-upgrade`

#### Scenario: Pull fails after the push
- **WHEN** the push lands and the live-tree pull fails
- **THEN** the spec is `blocked`, and one report names the commit and run
  with the pull and activate commands

#### Scenario: Corpus catches up while blocked
- **WHEN** a post-push block is in place and `hashes.json` now grounds the
  live spec, but the active run differs
- **THEN** the state stays `blocked` until the active run matches

#### Scenario: Live tree repaired
- **WHEN** the operator removes the local commit that broke the pull
- **THEN** the next run fast-forwards the live tree, activates the
  matching run, and clears the block

### Requirement: Every run ends in exactly one reported outcome

Each run that starts an attempt or changes state SHALL end in exactly one
Telegram report:
- `updated`: spec, commit, summary of changes, and code commits pulled.
- `retrying`: failing gate and next attempt time.
- `blocked`: failing gate and branch name, or, after the push, the pull and
  activate commands.
- `stalled`: an interrupted run, reported in place of `retrying` or
  `blocked` for that attempt.
- `waiting`: clone spec and live spec, or the failed environment check.

Knowledge activation and gateway restart reports are separate, and each is
sent once. A report that is delivered SHALL be recorded durably in the same
run. A report still undelivered for a spec older than the one in state
SHALL be dropped, not sent.

#### Scenario: Stalled run
- **WHEN** the next timer run finds an interrupted run
- **THEN** one `stalled` report is sent for that attempt and no other
  report for it

#### Scenario: Successful upgrade
- **WHEN** every gate passes and activation completes
- **THEN** one `updated` report is sent and no other report for that run

#### Scenario: Pending report delivered on an idle run
- **WHEN** a pending report is delivered on a run that then finds nothing
  to do
- **THEN** the report is recorded, and later runs do not send it again

#### Scenario: Stale pending report
- **WHEN** state holds an undelivered report for spec 482 and the state
  spec is 486
- **THEN** that report is dropped and never sent
