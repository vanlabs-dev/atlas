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

1. **Detect.** Read the live spec through keyless RPC. Stop silently when
   it equals `grounded_spec` in `knowledge/corpus/hashes.json`. The repo
   spec never starts a run.
2. **Clone lag.** Run `repotrack/atlas_repo.py update`. If the subtensor
   clone is still below the live spec, the state is `waiting`: no attempt
   is used, one `waiting` report is sent, and each run checks again.
3. **Preflight.** Author identity is `vaNlabs <vanlabs@pm.me>`, `~/atlas`
   is clean, and a trivial `claude -p` call works.
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
11. **Push.** Commit as vaNlabs, `git push origin HEAD:main` (never
    forced), read back the remote `main`, then `git -C ~/atlas pull
    --ff-only`.
12. **Activate.** `knowledge/atlas_kb.py activate --actor atlas-upgrade`,
    only after the read-back matches.
13. **Report.** One Telegram outcome per run.

## Outcomes and retry

| Outcome | Meaning |
|---|---|
| `updated` | Spec, commit, and the model's summary of changes |
| `retrying` | Failing gate and next attempt time (1 h, then 4 h) |
| `blocked` | Failing gate and kept branch. The third failure blocks. A failure after the push landed blocks at once |
| `stalled` | A run that was killed or interrupted, found by the next run. Replaces `retrying` or `blocked` for that attempt |
| `waiting` | Clone spec and live spec |
| `probe-drift` | From the hourly probe, not the job |

- A failed attempt commits its edits to its branch, which is never pushed.
  `~/atlas` and the active corpus are unchanged.
- A newer live spec starts again at attempt 1. Old branches are kept.
- Release a blocked spec:

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
