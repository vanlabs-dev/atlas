# runtime-upgrade-pipeline: brainstorm

Session 1, 2026-09-24. Input: the workstation audit of atlas `19c5617`
and subnt `ede5698` (see "Audit findings" below).

## Goal

When the live Finney runtime spec changes, the Pi brings Atlas up to date
without an operator: it re-grounds the corpus, fixes readers the upgrade broke,
proves the result against the live chain, pushes to `main`, and reports.
It replaces the Hermes cron job "Atlas runtime upgrade" (`fb98152a3fa1`).

## Success signals

- A spec change is detected within one hour, even when GitHub, TaoStats or
  the repotrack update is failing.
- A renamed or removed storage item Atlas reads pages the operator within
  one hour, whether or not the spec number moved.
- Every upgrade run ends in exactly one Telegram outcome: updated, blocked
  (with the failing gate), or retrying. A run that does not finish pages too.
- Nothing reaches `main` unless all test suites and the live probe pass.
- A failed run leaves the Pi's `main` equal to `origin/main`, with the old
  corpus still active.
- The model step costs one `claude -p` session per upgrade attempt.

## Constraints

- Engine: Claude Code headless (`claude -p`) on the Pi. Hermes only reports
  and chats.
- Trigger: live enactment only. No pre-staging from the repo spec.
- Merge gate: every `*/tests` suite (fleet and subnt included), then a live
  probe that checks every pinned storage item against the live runtime
  metadata at one finalized block.
- Edit scope: `knowledge/corpus/`, chain reader code and its configs
  (`livedata/`, the chain-read parts of `fleet/`). The job may not edit
  tests, `docs/runtime-upgrade.md`, `AGENTS.md`, systemd units, the
  orchestrator, or secrets. A fix that needs those pages the operator.
- Code enforces the gates. The model only edits files.
- Commits as `vaNlabs <vanlabs@pm.me>`, never force-push, Conventional
  Commits.
- Keyless RPC first. No new credential, except what `claude -p` needs.

## Non-goals

- The subnt v2 JSON export (separate change).
- Moving the MCP reader wrapper back into the repo (separate change).
- Pi cleanup and doc drift outside this pipeline (separate change).
- Any upgrade work before live enactment.

## Options considered

1. **Coded orchestrator, one model step (chosen).** A script in the repo,
   `upgrade/atlas_upgrade.py`, on its own systemd timer. The script
   detects the change, runs preflight, calls `claude -p` for edits only,
   checks the diff against the allowed paths, runs the tests and the probe,
   pushes, activates the corpus after the push lands, keeps durable state,
   retries with backoff, and pages. Cost: more code. Gain: the model
   cannot skip or weaken a gate, and the logic is testable off-device.
2. **The model runs the runbook.** `claude -p` follows a prompt kept in
   the repo from start to finish, with hooks blocking edits to disallowed
   paths. Less code, but the gates live in the prompt. Rejected.
3. **Keep the Hermes agent and harden its prompt.** Rejected: slow and
   costly, and the gates would still be enforced by the prompt.

## Chosen direction

Option 1, with these parts:

- **Detection.** A keyless `state_getRuntimeVersion` poll at a finalized
  block, falling back to TaoStats, on its own hourly timer. It no longer
  runs as an `ExecStartPost` of the repotrack update.
- **Live probe.** One module that fetches runtime metadata and asserts
  that every storage item Atlas reads exists with the expected hasher and
  value type. It runs hourly as a health check that pages on drift, and
  again as the merge gate.
- **Orchestrator.** A state machine with durable state:
  detect, preflight, prepare branch, edit (`claude -p`), check scope,
  test, probe, ingest, push, activate, report.
  - The edits happen on a branch. The branch fast-forwards `main` only
    after every gate passes.
  - Activation runs only after the remote read-back matches.
  - A failure keeps the branch, resets `main` to `origin/main`, pages,
    and retries with backoff up to a cap. A heartbeat alerts when a run
    stalls.
- **Model prompt and tool allowlist** live in the repo next to the
  orchestrator. The scope check runs in code, so the model cannot edit
  its own prompt into a wider scope.
- **Retire** Hermes cron job `fb98152a3fa1` and
  `~/.hermes/scripts/atlas_live_spec.py` once the new timer is accepted.

## Open questions (for propose)

1. How `claude -p` authenticates on the Pi as `pi` (subscription login or
   API key), and whether headless runs work there today.
2. The accepted `knowledge-base` spec requires operator activation. The
   change must amend that spec to allow gated automatic activation.
3. Probe coverage: derive the storage-item list from the reader configs
   (`livedata/config.json` pinned keys), or keep a separate manifest?
4. Where to run the edits: a dedicated worktree (for example
   `~/atlas-upgrade`), so the live tree is never mid-edit.
5. Retry cap and backoff, and what "stalled" means for the heartbeat.
6. Whether the probe should also verify provider schemas (TaoSwap, TaoStats
   `github_repo`), or leave that to a later change.

## Audit findings this change addresses

- Spec detection runs only through TaoStats, and only as an
  `ExecStartPost` of `atlas-repotrack-update.service`. A failed update
  silences detection and every alert.
- Renamed or removed storage items read as their defaults, and nothing
  checks runtime metadata.
- The upgrade job and its monitor exist only on the Pi. They have no retry,
  no watchdog, and no tests.
- The corpus is activated before the push. A failed push diverges the
  Pi's `main`.
- The test gate leaves out fleet and subnt. Every suite uses offline
  fixtures.
- The job may edit its own tests and runbook.
- `docs/runtime-upgrade.md` and `knowledge/corpus/SOURCES.md` contradict
  each other on step order and on what to do when the subtensor clone lags.
