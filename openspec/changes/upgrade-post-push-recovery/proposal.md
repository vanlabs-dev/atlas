# Proposal

## Why

From spec 483 to spec 486 the upgrade job pushed each corpus to `main`. Then
the live-tree pull failed, because an agent had committed into `~/atlas`, and
activation never ran. After a rebase, the job saw corpus equal to live and set
the blocked state to `idle`. Hermes served the spec-482 corpus for 11 days and
nothing paged (audit items A1, A2, A3, C12, C16, F2, F3). The job must never
again push, fail the pull, and go quiet with the knowledge base unactivated.

## What Changes

- Environment preflight runs before an attempt is counted. It checks Claude
  auth, the repo identity without the job's own overrides, a clean live tree,
  and a live tree with no local commits (an ancestor of `origin/main` after a
  fetch). A failed check sets `waiting` with a reason and sends one report in
  fixed wording. It uses no attempt.
- The ancestry check runs again right before the push.
- The pushed commit and the ingest run id are saved to state before the push.
- Every run compares the active knowledge run with `hashes.json` in the live
  tree. This happens before the "corpus equals live" exit.
- A post-push block never becomes `idle`. While the pull is the blocker, the
  job retries a fast-forward pull whenever the tree is clean and an ancestor.
  The block clears only when the live tree contains the pushed commit and the
  active run matches `hashes.json`.
- When the active run does not match `hashes.json`, the job activates the
  staged run that it ingested itself, whose files match, and whose validation
  report is clean. If no such run exists, it reports the exact ingest and
  activate commands once.
- A delivered pending report is always saved. A pending report for an older
  spec is dropped.
- The `updated` report lists the commits the pull brought in that touch code
  outside `knowledge/corpus` (capped).
- After a pull that brings in non-corpus code, the job restarts
  `hermes-gateway` when that is safe and confirms it is active. If the
  restart is not safe, or the restart fails, it sends one "restart needed"
  report and retries on later runs. A restart problem never blocks the spec.
- `knowledge_status` reports the active run's coverage and files, and names
  a newer staged run when one exists.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `runtime-upgrade`: preflight without attempts, recovery from a post-push
  block, a knowledge-currency check on every run, gateway restart after a
  code pull, and new report outcomes.
- `knowledge-base`: `knowledge_status` reports the active run and flags a
  newer staged run.

## Impact

- Code: `upgrade/atlas_upgrade.py`, `knowledge/atlas_kb_server.py`, and their
  tests.
- Docs: `docs/runtime-upgrade.md`, `upgrade/README.md`, and the main specs at
  archive time.
- Pi: the job gains `systemctl --user restart hermes-gateway` (user scope, no
  sudo). It reads `~/.hermes/gateway_state.json` only. It runs
  `atlas_kb.py activate` outside a gated attempt, but only for a run it
  ingested itself.
- Deploy: the code reaches the Pi only through a manual `git pull` in
  `~/atlas` and a manual gateway restart. Both need operator approval.
