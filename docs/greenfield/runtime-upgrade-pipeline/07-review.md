# runtime-upgrade-pipeline: outside-voice review

Session 3, 2026-09-24. Inputs: `01-brainstorm.md`, `02-approval.md`, the
OpenSpec change, the repo at `19c5617`, and read-only checks on the Pi.

Status: all findings resolved or accepted by the operator on 2026-09-24.
Resolutions folded into the change with `/opsx:update` on 2026-09-24
(`openspec validate --strict` passes).

## Verified facts

- Pi push path works from a worktree: `remote.origin.pushurl` is
  `git@github.com:vanlabs-dev/atlas.git` and `core.sshCommand` uses
  `~/.ssh/atlas_maintenance_ed25519`. Worktrees share this config.
- `atlas-poll-chain-head.timer` is installed on the Pi but `disabled` and
  `inactive`. Today spec detection runs only through the repotrack
  `ExecStartPost`. The design's Context line is wrong on this point.
- `var/` is gitignored. The subtensor clone
  (`var/repotrack/subtensor`), `var/livedata/livedata.db`, and
  `var/knowledge/knowledge.db` exist only under `~/atlas`.

## Critical

- **C1. Scope gate blocks the documented procedure.** `docs/runtime-upgrade.md`
  step 4 edits the live-chain entry in `docs/decisions.md` (denied by
  `docs/**`). `SOURCES.md` step 6 reviews `knowledge/supersession-markers.json`
  (not under `knowledge/corpus/`). A faithful run fails its own scope gate.
- **C2. The model can weaken the probe.** `livedata/*.py` admits
  `livedata/atlas_probe.py` and `livedata/scale_meta.py`. The merge gate
  runs worktree code, so an edit there can turn a fail into a pass.
- **C3. The worktree has no `var/`.** The model cannot read the spec-bump
  diff in the subtensor clone. `atlas_kb.py ingest` defaults to a relative
  `var/knowledge/knowledge.db`, so a worktree ingest stages into the wrong
  store. Nothing checks that the clone has caught up with the live spec
  (`SOURCES.md` rule 1) before a model session is spent.
- **C4. No gate checks that the goal was met.** An empty or partial edit
  can pass scope, tests, and probe. If `grounded_spec` in `hashes.json`
  does not move to the live spec, the job pushes, and the next timer run
  sees corpus != live and starts again. This loops without a cap, because
  every attempt "succeeded".

## Important

- **I1. Stall and restart overlap.** `RuntimeMaxSec=45min` kills a run
  before the 60-minute heartbeat can ever see it, and "restart counts as a
  failed attempt" reports the same run again. That breaks "exactly one
  outcome". No per-step timeouts exist, so a hung `claude -p` is only
  stopped by systemd, and the failure is never recorded.
- **I2. A newer live spec is unspecified.** Blocked on 451 while live moves
  to 452: does 452 start fresh, or stay blocked?
- **I3. Branch name reuse.** `upgrade/spec-<n>` is rebuilt every attempt,
  which conflicts with "keep the failed branch for inspection".
- **I4. Detection latency exceeds the signal.** An hourly poll plus a
  30-minute upgrade timer can take about 95 minutes, which misses "detected
  within one hour".
- **I5. The probe checks declared shape, not decoding.** If a value type
  changes, the model updates the `CHAIN_READS` type name and the probe
  passes. Reader decode code can still be wrong, and offline fixtures do
  not catch it.

## Minor

- **M1.** The spec lists outcomes `updated`, `retrying`, `blocked`. The
  design adds `stalled` and `probe-drift`. Align them.
- **M2.** Task 5.7 has an operator clear command, but no requirement does.
- **M3.** `SOURCES.md` step 3 requires live knob reads. A read-only Bash
  allowlist must name the read tool, or the job must supply the values.
- **M4.** `hashes.json` regeneration is deterministic. The job, not the
  model, should do it.
- **M5.** The upgrade unit needs the Telegram `EnvironmentFile`.
- **M6.** Fix the design Context line about `atlas-poll-chain-head`.

## Proposed resolutions

| ID | Resolution |
|---|---|
| C1 | Allow the exact paths `docs/decisions.md` and `knowledge/supersession-markers.json`. Keep `docs/**` denied otherwise. |
| C2 | Deny `livedata/atlas_probe.py` and `livedata/scale_meta.py`. |
| C3 | Run `claude -p` with read-only `--add-dir ~/atlas/var/repotrack/subtensor`. Ingest with `--db ~/atlas/var/knowledge/knowledge.db`. Preflight runs a repotrack fetch. A clone that still lags sets the state to `waiting`, uses no attempt, and is reported once. |
| C4 | Add a goal gate after the edit: the job regenerates `hashes.json`, and `grounded_spec` must equal the live spec. An empty diff fails the attempt. |
| I1 | Per-step subprocess timeouts under `RuntimeMaxSec`. Take an exclusive `flock`. A `running` state found at start with no lock holder is interrupted: it counts as a failed attempt and reports `stalled` in place of `retrying`. Drop the 60-minute threshold. |
| I2 | A new live spec supersedes: fresh attempt count, and the old branch is kept. |
| I3 | Branch `upgrade/spec-<n>-a<k>`. |
| I4 | The detect step reads the live spec itself through the keyless RPC function, so detection time is bounded by the 30-minute timer. |
| I5 | Accept for v1. Record it under Risks. |
| M1-M6 | Fold in as written. M5 needs no `EnvironmentFile`: `telegram/atlas_telegram.py` `load_env` reads `~/.hermes/.env`. M3: the job runs a new `read-knobs` subcommand and puts its output in the prompt. |

## Operator decisions

2026-09-24, operator: every proposed resolution accepted as written,
including the C1 exact-path allowlist, the C3 `waiting` state, and
accepting I5 for v1.
