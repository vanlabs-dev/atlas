## Why

The Hermes cron job "Atlas runtime upgrade" (`fb98152a3fa1`) enforces its
gates only through its prompt, exists only on the Pi, and has no retry, no
watchdog, and no tests. Spec detection depends on TaoStats and on the
repotrack update succeeding, and renamed storage items read silently as
defaults. See `docs/greenfield/runtime-upgrade-pipeline/01-brainstorm.md`
and the review in `07-review.md`.

## What Changes

- Add `upgrade/atlas_upgrade.py`: a coded orchestrator with durable state
  (detect, preflight, prepare branch, edit, goal, scope, test, probe,
  ingest, push, activate, report), on its own systemd timer.
- The model step is one `claude -p` session per attempt. It only edits
  files, in a worktree at `~/atlas-upgrade`, with read-only access to the
  subtensor clone. Code enforces every gate.
- Code checks the diff against an allowed-path list. A change outside
  `knowledge/corpus/`, `knowledge/supersession-markers.json`,
  `docs/decisions.md`, or the `livedata/` reader code and configs blocks
  the run. The probe and its metadata decoder are denied.
- Goal gate: the job regenerates `knowledge/corpus/hashes.json` itself, and
  the corpus must state the live spec as its grounded spec.
- Merge gate: every `*/tests` suite, then the live chain-read probe.
- Push with `git push origin HEAD:main` (never force), then
  `git -C ~/atlas pull --ff-only`, then activate the corpus. Activation
  runs only after the remote read-back matches.
- Retry: 3 attempts per spec, backoff 1h then 4h, then `blocked`. A newer
  live spec supersedes a blocked or retrying one. A subtensor clone that
  lags the live spec puts the run in `waiting` without using an attempt.
  Every run ends in one Telegram outcome. A run found interrupted at the
  next start counts as a failed attempt and reports `stalled`.
- Add a live chain-read probe: `livedata/atlas_live.py` exposes one
  `CHAIN_READS` table that the readers use. The probe checks each entry
  against live runtime metadata at one finalized block. It runs hourly as a
  health check and again as the merge gate.
- Spec detection moves to keyless `state_getRuntimeVersion` at a finalized
  block, with TaoStats as fallback, on its own hourly timer. It no longer
  runs as an `ExecStartPost` of `atlas-repotrack-update.service`. The
  upgrade job's detect step uses the same keyless read.
- **BREAKING** (operator process): corpus activation no longer always
  needs the operator. The upgrade job may activate after every gate passes.
- Retire Hermes cron job `fb98152a3fa1` and
  `~/.hermes/scripts/atlas_live_spec.py` after acceptance. Rewrite
  `docs/runtime-upgrade.md` and align `knowledge/corpus/SOURCES.md`.

## Capabilities

### New Capabilities
- `runtime-upgrade`: the orchestrator, edit scope, goal and merge gates,
  push and activation order, retry, interruption handling, and outcome
  reporting.
- `chain-read-probe`: the `CHAIN_READS` table, the metadata probe, and the
  hourly drift health check.

### Modified Capabilities
- `knowledge-base`: "Validation report and operator activation gate" allows
  gated automatic activation by the upgrade job, audited as
  `atlas-upgrade`.
- `live-data`: "Live runtime spec_version changes are recorded" reads the
  spec from keyless RPC first, with TaoStats as fallback, on its own timer.

## Impact

- New: `upgrade/` (orchestrator, prompt, allowed paths, tests, systemd
  units), `livedata/atlas_probe.py`, a stdlib-only SCALE metadata decoder
  (`livedata/scale_meta.py`), a read-only `read-knobs` subcommand in
  `livedata/atlas_live.py`.
- Changed: `livedata/atlas_live.py` (`CHAIN_READS`, keyless spec read),
  `repotrack/systemd/atlas-repotrack-update.service` (drop spec
  `ExecStartPost`), `knowledge/atlas_kb.py` (activation actor),
  `docs/runtime-upgrade.md`, `knowledge/corpus/SOURCES.md`.
- Pi: new worktree `~/atlas-upgrade`, new user timers, `claude` binary
  path in the unit, Hermes cron job removed.
- No new credential beyond the existing `claude` login.
