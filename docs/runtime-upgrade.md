# Runtime upgrades

Atlas updates itself on the Pi when the live chain moves to a new runtime
spec. Code enforces every gate. The model only edits files.

## Parts

| Part | Where | Schedule |
|---|---|---|
| Spec poll | `livedata/atlas_live.py poll-chain-head` (`atlas-poll-chain-head`) | hourly |
| Chain-read probe | `livedata/atlas_probe.py watch` (`atlas-probe`) | hourly |
| Upgrade job | `upgrade/atlas_upgrade.py run` (`atlas-upgrade`) | every 30 min |

All three are user units under `~/.config/systemd/user/` (linger is on).

- **Spec poll.** Reads `spec_version` through keyless finney RPC at the
  finalized head. Falls back to TaoStats only when every RPC endpoint
  fails. Records upgrade events in `var/livedata/livedata.db` with their
  source. It no longer depends on the repotrack update.
- **Probe.** Checks every storage item in `CHAIN_READS`
  (`livedata/atlas_live.py`) against live runtime metadata at one
  finalized block: the item exists, with the declared hashers and value
  type. `watch` pages `probe-drift` once per new failing set and once when
  it clears. `check` is the upgrade merge gate.

## The upgrade job

Each run holds `var/upgrade/lock` and keeps its state in
`var/upgrade/state.json`. It runs from `~/atlas` (trusted `origin/main`
code) and never edits that tree.

0. **Recover.** Runs first, on every run (see Recovery below).
1. **Detect.** Read the live spec through keyless RPC. Stop silently when
   it equals `grounded_spec` in `knowledge/corpus/hashes.json`. The repo
   spec never starts a run.
2. **Clone lag.** Run `repotrack/atlas_repo.py update`. If the subtensor
   clone is still below the live spec, the state is `waiting`: no attempt
   is used, one `waiting` report is sent, and each run checks again.
3. **Preflight.** These checks run before an attempt is counted:
   - The repo's own author identity is `vaNlabs <vanlabs@pm.me>`. It is
     read without the job's `GIT_AUTHOR_*` overrides.
   - `~/atlas` is clean.
   - After a fetch, `~/atlas` HEAD is an ancestor of `origin/main`, so it
     holds no local commits.
   - A trivial `claude -p` call works.

   A failed check sets `waiting` with a reason (`identity`, `dirty`,
   `diverged`, `auth`). It uses no attempt and sends one fixed-wording
   report per reason, and each run checks again.
4. **Prepare.** Worktree `~/atlas-upgrade` on a new branch
   `upgrade/spec-<n>-a<k>` from `origin/main`.
5. **Edit.** One `claude -p --restricted` session in the worktree, with no
   Bash and no web tools. Its prompt (`upgrade/prompt.md`) carries the
   `read-knobs` output at one finalized block, the probe result, and the
   spec-bump log. The full diff is in `var/upgrade/spec-<n>.diff`. The
   subtensor clone is readable through `--add-dir`. The model follows
   `knowledge/corpus/SOURCES.md` and updates the live-chain entry in
   `docs/decisions.md`.
6. **Goal.** The diff must not be empty, and `SOURCES.md` must ground the
   live spec. The job then regenerates `hashes.json` itself.
7. **Scope.** Every changed path must be in `upgrade/allowed_paths.py`:
   `knowledge/corpus/**`, `knowledge/supersession-markers.json`,
   `docs/decisions.md`, `livedata/*.py`, `livedata/config.json`. The probe,
   its metadata decoder (`livedata/scale_meta.py`), and every `tests/`
   path are denied. HEAD must not move, and `~/atlas` must stay clean.
8. **Test.** Every `*/tests` suite with system `python3`.
9. **Probe.** `livedata/atlas_probe.py check` from the worktree.
10. **Ingest.** Stage the corpus into `~/atlas/var/knowledge/knowledge.db`.
    A duplicate unit id or a secret-scan finding fails the attempt.
11. **Push.** Commit as vaNlabs. Check again that `~/atlas` is clean and
    has no local commits. Save the commit and run id to state, then
    `git push origin HEAD:main` (never forced). Read back the remote
    `main`, then `git -C ~/atlas pull --ff-only`.
12. **Activate.** `knowledge/atlas_kb.py activate --actor atlas-upgrade`,
    only after the read-back matches.
13. **Report.** One Telegram outcome per run. `updated` lists the commits
    the pull brought in that touch code outside `knowledge/corpus` (up to
    10).
14. **Restart.** When the pull brought in code, restart `hermes-gateway`
    so its MCP servers load it (see Gateway restart below).

## Recovery

Each run starts by finishing what an earlier run left undone. This runs
before the "corpus equals live" exit, so it also covers specs that look
current.

- **Post-push block.** A failure at read-back, pull or activate blocks at
  once. The report names the commit and run, with the pull and activate
  commands. The block never turns `idle` because the corpus caught up.
  While the commit is missing from `~/atlas`, each run retries
  `pull --ff-only`, but only while the tree is clean and has no local
  commits. The block clears once `~/atlas` holds the commit and the active
  run matches `hashes.json`.
- **Knowledge currency.** When `~/atlas` is clean, has no local commits,
  and the active run's file hashes differ from `hashes.json`, the job
  activates a staged run that meets all three of these conditions:
  - The job ingested it itself (actor `atlas-upgrade` in the audit log).
  - Its hashes equal `hashes.json`.
  - Its validation report has no rejected units.

  It reports that activation once. When no run qualifies, it reports once
  with the ingest and activate commands. Either report is sent once per
  `hashes.json` content.
- **Pending reports.** A delivered pending report is saved at once. One
  left over for an older spec is dropped unsent.

## Gateway restart

The `hermes-gateway` MCP servers are long-lived, so pulled code reaches
them only after a restart. After a pull that brings in non-corpus code,
the job restarts the gateway only when the restart is safe:
- `systemctl --user is-active hermes-gateway` is `active`.
- `~/.hermes/gateway_state.json` is under 10 minutes old.
- That file shows `gateway_state` `running`, `active_agents` 0, and no
  `active_work`.

Anything else counts as unsafe, including a missing or unreadable file.
The job never starts a gateway that the operator stopped. After a restart
it waits for `is-active`. When the restart is unsafe or fails, it sends
one "restart needed" report and retries on each later run. A restart
never changes the upgrade outcome.

A manual `git pull` in `~/atlas` is not covered: restart the gateway by
hand after one.

## Outcomes and retry

| Outcome | Meaning |
|---|---|
| `updated` | Spec, commit, and the model's summary of changes |
| `retrying` | Failing gate and next attempt time (1 h, then 4 h) |
| `blocked` | Failing gate and kept branch. The third failure blocks. A failure after the push landed blocks at once and gives the pull and activate commands |
| `stalled` | A run that was killed or interrupted, found by the next run. Replaces `retrying` or `blocked` for that attempt |
| `waiting` | Clone spec and live spec, or a failed preflight check (`identity`, `dirty`, `diverged`, `auth`). Uses no attempt |
| knowledge | A self-activated run, or a stale-corpus notice with commands |
| restart needed | The gateway could not be restarted safely after a code pull |
| `probe-drift` | From the hourly probe, not the job |

- A failed attempt commits its edits to its branch, which is never pushed.
  `~/atlas` and the active corpus are unchanged.
- A newer live spec starts again at attempt 1. Old branches are kept.
- Release a blocked spec. A post-push block clears by itself once it is
  repaired; `clear` also drops it:

  ```
  python3 upgrade/atlas_upgrade.py clear --spec <n>
  ```

- Inspect the state: `python3 upgrade/atlas_upgrade.py status`.
- Dry run (no push, no activation, reports printed). When corpus equals
  live, it checks the machinery on an unedited worktree:

  ```
  python3 upgrade/atlas_upgrade.py run --dry-run
  ```

## Rules

Only the live spec drives an update. The repo spec moves ahead when a
release merges before enactment. Never force-push. A fix that needs a path
outside the scope blocks the attempt and waits for the operator.

Rollback: disable `atlas-upgrade.timer`. Hermes cron job `fb98152a3fa1`
was removed on 2026-09-24, so no fallback job exists: upgrades are then
manual. The spec poll and probe timers stay.
