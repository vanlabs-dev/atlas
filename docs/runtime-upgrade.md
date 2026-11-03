# Runtime upgrades

Atlas updates itself on the Pi when the live chain moves to a new runtime
spec. Code enforces every gate. The model only edits data files: the
corpus, the supersession markers and the decision log. The job never runs
model-written code (change `upgrade-sandbox-scope`, 2026-11-03).

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
  type. For each item whose unset value Atlas substitutes, the runtime
  default must equal `EXPECTED_DEFAULTS` in `livedata/atlas_live.py`
  (exact SCALE bytes). `watch` pages `probe-drift` once per new failing
  set and once when it clears. `check` is the upgrade preflight and gate.

## The upgrade job

Each run holds `var/upgrade/lock` and keeps its state in
`var/upgrade/state.json`. It runs from `~/atlas` (trusted `origin/main`
code) and never edits that tree.

0. **Recover.** Runs first, on every run (see Recovery below).
1. **Detect.** Read the live spec through keyless RPC. Stop silently when
   it equals `grounded_spec` in `knowledge/corpus/hashes.json`. The repo
   spec never starts a run.
2. **Clone and source.** Under the clone lock
   (`var/repotrack/subtensor.lock`, shared with the repotrack timer, wait
   up to 15 min), run `repotrack/atlas_repo.py update`. If the clone is
   still below the live spec, the state is `waiting`. Otherwise resolve
   the release anchor of the live spec and of the corpus spec: the
   `v<spec>` tag, else the commit that introduced `spec_version: <spec>,`.
   The runtime at the anchor must state that spec, and the anchor must be
   on HEAD. Without one, the state is `waiting` (`anchor`); the diff never
   runs to HEAD. The job writes the diff and log between the two anchors
   to `var/upgrade/spec-<n>.diff` and exports the source at the live
   anchor to `var/upgrade/source-<n>/` (`git archive`, reused while the
   anchor is unchanged). The model reads only that export, never the
   clone, so it never sees code that has not shipped.
3. **Preflight.** These checks run before an attempt is counted:
   - The repo's own author identity is `vaNlabs <vanlabs@pm.me>`. It is
     read without the job's `GIT_AUTHOR_*` overrides.
   - `~/atlas` is clean.
   - After a fetch, `~/atlas` HEAD is an ancestor of `origin/main`, so it
     holds no local commits.
   - A trivial `claude -p` call works.
   - `livedata/atlas_probe.py check` passes on `~/atlas`. Chain readers
     are out of the model's scope, so drift is an operator fix.

   A failed check sets `waiting` with a reason (`identity`, `dirty`,
   `diverged`, `auth`, `readers`, `probe`; `anchor` comes from step 2). It
   uses no attempt and sends one fixed-wording report per reason, and each
   run checks again.
4. **Prepare.** Worktree `~/atlas-upgrade` on a new branch
   `upgrade/spec-<n>-a<k>` from `origin/main`.
5. **Edit.** One `claude -p --restricted` session in the worktree, with no
   Bash and no web tools. Its prompt (`upgrade/prompt.md`) carries the
   `read-knobs` output at one finalized block, the preflight probe result,
   the anchor and the log between the two releases. File reads (Read,
   Grep, Glob) are `Read(path)` rules over the worktree, the source
   export and `var/upgrade` only; `~/.ssh`, `~/.hermes`, `~/.claude` and every `.env` are denied.
   The model follows `knowledge/corpus/SOURCES.md` and updates the
   live-chain entry in `docs/decisions.md`.
6. **Goal.** The diff must not be empty, and `SOURCES.md` must ground the
   live spec. The job then regenerates `hashes.json` itself.
7. **Scope.** Every changed path must be in `upgrade/allowed_paths.py`:
   `knowledge/corpus/**`, `knowledge/supersession-markers.json`,
   `docs/decisions.md`. All of `livedata/` and every `tests/` path are
   denied. Only modifications of existing files pass: an added, renamed,
   copied or deleted file fails. HEAD must not move, and `~/atlas` must
   stay clean.
8. **Citation.** Corpus lines the edit adds may cite only the two blocks
   this run read (knobs and probe) or blocks the base corpus already
   cites, and may name no spec above live.
9. **Sandbox.** A canary (`upgrade/sandbox_canary.py`) runs through the
   gate sandbox (`upgrade/sandbox.py`, bubblewrap) with and without
   network. It must find no secret path, no bus or docker socket, no
   working `sudo`, `NoNewPrivs` set, a read-only worktree, a clean
   environment, and no network when none was asked for. Any miss, or no
   `bwrap`, fails the attempt.
10. **Test.** Every `*/tests` suite with system `python3`, inside the
    sandbox without network.
11. **Probe.** `livedata/atlas_probe.py check` from the worktree, inside
    the sandbox with network.
12. **Ingest.** Stage the corpus into `~/atlas/var/knowledge/knowledge.db`.
    A duplicate unit id or a secret-scan finding fails the attempt.
13. **Push.** The scope check runs again on the exact tree, and the staged
    paths must equal the checked ones. Commit as vaNlabs. Check again that `~/atlas` is clean and
    has no local commits. Save the commit and run id to state, then
    `git push origin HEAD:main` (never forced). Read back the remote
    `main`, then `git -C ~/atlas pull --ff-only`.
    Only this push gets the deploy key (`GIT_SSH_COMMAND` with
    `~/.ssh/atlas_maintenance_ed25519`). The live tree has no
    `core.sshCommand`, so no other push from the Pi can use it. The Pi's
    `core.hooksPath` points at `tools/git-hooks`, whose `pre-commit`
    rejects any author or committer other than `vaNlabs <vanlabs@pm.me>`.
14. **Activate.** `knowledge/atlas_kb.py activate --actor atlas-upgrade`,
    only after the read-back matches.
15. **Report.** One Telegram outcome per run. `updated` lists the commits
    the pull brought in that touch code, not only the corpus, the
    supersession markers or `docs/` (up to 10).
16. **Restart.** When the pull brought in code, restart `hermes-gateway`
    so its MCP servers load it (see Gateway restart below).

Every run has one deadline, 50 minutes from its start (`RUN_BUDGET`).
Each step before the push runs under the smaller of its own timeout and
the time left less a 15-minute push reserve. The push does not start
without that reserve; the attempt then fails at the `deadline` gate. The
unit's `TimeoutStartSec` (60 min) is a backstop above the deadline.

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
them only after a restart. After a pull that brings in code (anything but the corpus, the
supersession markers and `docs/`),
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
| `waiting` | Clone spec and live spec, or a failed preflight check (`identity`, `dirty`, `diverged`, `auth`, `readers`, `probe`, `anchor`). Uses no attempt |
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

- Reports name the failing gate in fixed words. The raw error never goes
  to Telegram; it stays in `last_error` and on stderr.
- Reports go through the Telegram ledger and retry queue. A queued report
  counts as sent.
- Exit codes: a run that ends in a recorded outcome exits 0. That includes
  a failed attempt that was reported and a live spec that could not be
  read. Only an unexpected error exits non-zero, which pages through the
  unit failure notifier.
- Inspect the state: `python3 upgrade/atlas_upgrade.py status`.
- Dry run (no push, no activation, reports printed). When corpus equals
  live, it checks the machinery on an unedited worktree:

  ```
  python3 upgrade/atlas_upgrade.py run --dry-run
  ```

## Rules

Only the live spec drives an update. The repo spec moves ahead when a
release merges before enactment. Never force-push. A fix that needs a path
outside the scope blocks the attempt and waits for the operator. That
includes every chain reader fix: since 2026-11-03 the job may not edit
`livedata/` (none of the 12 upgrades from spec 470 to 486 needed to).

After a Claude Code update on the Pi, re-run the edit-session read check
(one `claude -p` call with the job's own rules) to confirm the read
denials still hold.

Rollback: disable `atlas-upgrade.timer`. Hermes cron job `fb98152a3fa1`
was removed on 2026-09-24, so no fallback job exists: upgrades are then
manual. The spec poll and probe timers stay.
