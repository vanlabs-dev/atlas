# Design

## Context

`upgrade/atlas_upgrade.py` runs every 30 minutes on the Pi from `~/atlas`
(see proposal.md, Why). Current behaviour that shapes this design:

- `_run_locked` returns early when the corpus spec equals the live spec, and
  rewrites any non-idle state for that spec to `idle`. That line cleared the
  spec-486 post-push block.
- `step_preflight` runs after `attempt + 1`, and it checks the identity
  through `self.git`, which always sets `GIT_AUTHOR_*`.
- `commit` and `run_id` live only in the in-memory `ctx`, so a post-push
  failure cannot name them.
- The report key is `spec:attempt:kind`. The key `486:0:waiting` is already
  used by the clone-lag report.
- `flush_pending` is not followed by a save on the early-return paths. The
  Pi holds a `482:2:retrying` report since 22 Oct that the scrubber refuses
  because it quotes the raw Claude auth error.
- Run file hashes in `intake_runs.files_json` (`{name: {bytes, sha256}}`)
  use the same LF-normalised sha256 as `hashes.json` `files`. This was
  checked on the Pi for run `20261026T190458Z-0a28e3df`.
- `atlas_kb.py activate --actor atlas-upgrade` already refuses a run with
  rejected units.
- `~/.hermes/gateway_state.json` is written by Hermes about once a minute.
  It has the keys `gateway_state`, `active_agents`, `active_work` and
  `updated_at`. This is a foreign, unversioned schema.

## Goals / Non-Goals

**Goals:** close every path from "pushed" to "quiet with a stale knowledge
base", and restart the MCP servers after new code arrives.

**Non-Goals:**
- The Pi pre-commit hook and Hermes permissions (WP2).
- Scrubber rules (WP9).
- Unit-file sync and a general deploy step (WP14).
- Sandboxing the gates (WP5).

## Decisions

1. **Run the environment preflight before the attempt counter.**
   - `step_preflight` moves out of the step list into `_attempt`, after the
     clone check and before `attempt + 1`.
   - A failure raises a dedicated `Waiting(reason)`. The state becomes
     `waiting` with `wait_reason`, and the report kind is
     `waiting-<reason>` (`auth`, `identity`, `dirty`, `diverged`). This keeps
     each reason off the clone-lag key.
   - The wording is fixed per reason, and the raw output goes to stderr
     only. Fixed wording also gets past the scrubber.
   - Alternative rejected: keep preflight as a step and refund the attempt.
     That loses the retry and backoff accounting.

2. **Identity check uses a stripped environment.** It runs
   `git var GIT_AUTHOR_IDENT` with `os.environ` minus every `GIT_AUTHOR_*`
   and `GIT_COMMITTER_*` key.

3. **Ancestry check.**
   - Preflight runs `git fetch origin`, then
     `git merge-base --is-ancestor HEAD origin/main`. A tree that is behind
     passes.
   - `step_push` repeats the check before `git push`. Its failure is a
     `push` gate failure, which is pre-push, so it retries.

4. **Persist the post-push context.**
   - `step_push` writes `state["post_push"] = {commit, run_id, gate: None}`
     and saves before it pushes.
   - `fail()` records the gate in `post_push` for a post-push gate. The
     blocked message gives
     `git -C ~/atlas pull --ff-only origin main` and
     `python3 knowledge/atlas_kb.py activate --run <id>`, then states that
     the job clears the block itself.

5. **Recovery runs before the early return.** A new `reconcile(state)` runs
   on every timer run, after the flush and the interrupted-run check, and
   before the live-spec comparison. It runs these steps in order:
   1. **Pull.** When the state is blocked with `post_push`, the commit is
      not in `HEAD`, and the tree is clean and an ancestor, run
      `pull --ff-only`. A failure leaves the block in place, and nothing new
      is reported.
   2. **Knowledge currency.** When the tree is clean and an ancestor, and
      the active run's hashes differ from `hashes.json`, find a candidate.
      A candidate is a run with an `ingest` audit row by `atlas-upgrade`,
      equal hashes, and a clean validation report. Prefer the newest.
      Activate it through `atlas_kb.py activate --actor atlas-upgrade`.
      Report once under the key `kb:<sha8 of hashes.json>:activated`, or
      `kb:<sha8>:stale` with ingest and activate commands when there is no
      candidate.
   3. **Clear.** When `post_push` is set and the tree contains the commit
      (`merge-base --is-ancestor <commit> HEAD`), and the active run matches
      `hashes.json`, set status `idle` and drop `post_push`.
   4. **Restart.** Retry a pending gateway restart (decision 7).

   The early return no longer rewrites any state to `idle`. The only path
   back to `idle` is step 3. A pre-push `blocked` still needs `clear`, as
   before.

   The knowledge base is read with `sqlite3` in read-only URI mode. All
   writes go through `atlas_kb.py`.

6. **Key the reports by `hashes.json` content.** `report()` takes an
   optional explicit key, so knowledge and restart reports are not keyed by
   `spec:attempt`. This gives one report per corpus content, whatever the
   spec state.

7. **Gateway restart.**
   - **When:** in `step_push`, record `pre_pull = HEAD` before the pull.
     After the pull, list `pre_pull..commit` minus the upgrade commit, with
     `-- . ':!knowledge/corpus'`. Store it as `ctx["code_commits"]` and put
     up to 10 in the `updated` report, with "and N more".
   - **Restart:** when the list is not empty, set
     `state["restart"] = {"commit": ..., "reported": False}` after the
     activation. The success path then attempts the restart once.
   - **Safe means:** `systemctl --user is-active hermes-gateway` is
     `active`. The state file parses. `gateway_state == "running"`.
     `updated_at` is under 10 minutes old. `active_agents == 0`.
     `active_work` is null. Anything missing, or any other value, counts
     as unsafe.
   - **Success:** after `systemctl --user restart hermes-gateway`, poll
     `is-active` for up to 30 s. Success drops `state["restart"]`.
   - **Unsafe or failed:** send one "restart needed" report, keyed
     `restart:<commit8>`. Keep `state["restart"]` so later runs retry
     quietly through `reconcile` step 4.
   - The restart is never part of the gate list, so it cannot change the
     upgrade's outcome.
   - Alternative rejected: `ExecReload` (USR1). Its semantics are
     undocumented in the repo.
   - The Hermes home is `HERMES_HOME`, with `~/.hermes` as the fallback.

8. **Flush and save.**
   - `flush_pending` returns `True` when it changed state.
   - `_run_locked` saves whenever the flush, the reconcile, or the
     early-return path changed state.
   - A pending report whose key spec is below `state["spec"]` is dropped,
     with a note on stderr.

9. **`knowledge_status`.**
   - Select the active `run_id` from `units`, then join
     `intake_runs WHERE run_id = ?` for the coverage date and files.
   - `staged_newer_run` is the newest `intake_runs` row whose `intake_date`
     is later than the active run's, given as `{run_id, coverage_date}`, or
     null.

## Risks / Trade-offs

- [Self-activation outside a gated attempt] → It is limited to runs the job
  itself ingested, whose hashes equal the committed `hashes.json` in a
  clean tree with no local commits. `activate` re-checks for rejected units.
  The gates already passed when the job ingested the run.
- [Hermes renames state-file keys] → Unknown or missing keys count as
  unsafe. The cost is a "restart needed" report, never a forced restart.
- [Restart cuts off a chat that starts between the check and the restart]
  → The window is a few seconds. Hermes restarts in about 5 s, and the
  next message retries.
- [The first pull after deploy carries 54+ commits] → The commit list is
  capped. This change only takes effect after the operator's manual pull.
  The operator restarts the gateway by hand for that pull.
- [The fetch in preflight adds about 1 s per run when live is ahead] → It
  is only reached when an upgrade is needed.

## Migration Plan

1. Merge, then the operator pushes.
2. The operator runs `git pull --ff-only` in `~/atlas` on the Pi, then
   `systemctl --user restart hermes-gateway`.
3. Next timer run:
   - The `482:2:retrying` pending report is dropped.
   - `reconcile` finds that run 486 is active and matches `hashes.json`, so
     nothing is reported.
   - The state stays `idle`.
4. Rollback: revert the commits and pull. The state keys `post_push`,
   `restart` and `wait_reason` are ignored by the old code.
