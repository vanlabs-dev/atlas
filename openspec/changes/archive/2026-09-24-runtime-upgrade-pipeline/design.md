## Context

See proposal.md (Why), `docs/greenfield/runtime-upgrade-pipeline/01-brainstorm.md`,
and the review in `07-review.md`.

- Every chain read lives in `livedata/atlas_live.py`: pinned keys in
  `gate_signal.storage_keys` and `chain_params.items`, and derived reads
  (`Keys`, `TotalHotkeyAlpha`, root weights, subnet maps) built in code.
  `fleet/` has no chain RPC, so it is not in the edit scope.
- The repo is stdlib Python run by system `python3`. Tests use
  `python3 -m unittest discover -s .` per `*/tests` directory. `twox128`
  is already hand-rolled because `xxh64` is not installed on the Pi.
- The Pi has a subscription login in `~/.claude/`. `claude` is not on the
  non-login `PATH`.
- The Pi has `atlas-poll-chain-head.{service,timer}` installed in
  `~/.config/systemd/user/`, but the timer is disabled and inactive
  (checked 2026-09-24). Today spec detection runs only through the
  repotrack `ExecStartPost`. This change brings the units into the repo.
- `var/` is gitignored. The subtensor clone (`var/repotrack/subtensor`)
  and every store (`var/livedata/`, `var/knowledge/`, `var/telegram/`)
  exist only under `~/atlas`, never in a worktree.
- The Pi push path works from any worktree: `remote.origin.pushurl` is SSH
  and `core.sshCommand` names the Atlas deploy key.
- `telegram/atlas_telegram.py` resolves its credentials from
  `~/.hermes/.env` through `load_env`. Units need no `EnvironmentFile`.

## Goals / Non-Goals

**Goals:**
- Gates, ordering, and retry live in tested code, runnable off-device with
  fakes for `claude`, `git`, RPC, and Telegram.
- A failed run leaves the Pi exactly as it was.

**Non-Goals:**
- Provider schema checks (TaoSwap, TaoStats `github_repo`).
- Metadata versions older than V14.
- Pre-staging from the repo spec.
- Live decode checks of each reader (accepted for v1, see Risks).

## Decisions

1. **Orchestrator as a step list with a JSON state file.**
   `upgrade/atlas_upgrade.py` runs from `~/atlas` (trusted `origin/main`
   code, never the worktree) through `detect, preflight, prepare, edit,
   goal, scope, test, probe, ingest, push, activate, report`. State lives
   in `var/upgrade/state.json`, written atomically after each step. Each
   run holds an exclusive `flock` on `var/upgrade/lock`.
   Alternative: SQLite. Rejected, as one row of state does not need it.

2. **Worktree, not a clone.** `~/atlas-upgrade` is a `git worktree` of
   `~/atlas` on branch `upgrade/spec-<n>-a<k>` (spec, attempt), created
   from `origin/main` for each attempt. Earlier attempt branches are kept.
   The push is `git push origin HEAD:main`. Then
   `git -C ~/atlas pull --ff-only`, then read back `origin/main`.
   `~/atlas` never holds edits, so no reset is needed on failure.
   Alternative: edit in `~/atlas` and reset. Rejected: services read that
   tree while the model edits it.

3. **Model call.** One `claude -p` with the prompt in `upgrade/prompt.md`,
   `--allowedTools` limited to read, edit, and a read-only Bash allowlist
   with no network commands, `--max-turns` capped, cwd `~/atlas-upgrade`,
   and `--add-dir ~/atlas/var/repotrack/subtensor` for the spec-bump diff
   (read tools only). Before the call, the job runs
   `livedata/atlas_live.py read-knobs` at one finalized block and puts the
   output and block hash into the prompt, so the model cites live values
   without network access. The binary path comes from the unit's
   `Environment=ATLAS_CLAUDE_BIN=`. Preflight runs a trivial `claude -p`
   smoke call and fails the attempt on auth errors.

4. **Scope gate in code.** `upgrade/allowed_paths.py` holds the allowlist:
   `knowledge/corpus/**`, `knowledge/supersession-markers.json`,
   `docs/decisions.md`, `livedata/*.py`, `livedata/config.json`. Denied
   even if matched: `livedata/atlas_probe.py`, `livedata/scale_meta.py`,
   any `tests/` path, `upgrade/**`, `docs/**` other than
   `docs/decisions.md`, `AGENTS.md`, `**/systemd/**`, `.env*`. The gate
   reads `git diff --name-status origin/main...HEAD` plus untracked files.
   The job commits, not the model.

5. **Goal gate.** After the edit, the job regenerates
   `knowledge/corpus/hashes.json` (sha256 per file, LF-normalized, dates,
   and `grounded_spec` taken from the "Grounded at" line in `SOURCES.md`).
   The gate fails when that grounded spec is not the live spec, or when
   the diff is empty. Because the job writes `grounded_spec` only after a
   pass, a pushed run always leaves corpus equal to live, so no pass can
   start another run for the same spec.

6. **Test gate.** Discover every `*/tests` directory at runtime and run
   each with system `python3`. No hard-coded suite list, so a new suite is
   covered automatically.

7. **`CHAIN_READS` in `atlas_live.py`.** A tuple of entries (pallet, item,
   hashers, value type name). The key builders and pinned-key checks take
   items from it. A test in `livedata/tests` scans reader call sites for
   item names and fails on any undeclared one. Alternative: a separate
   manifest. Rejected: it can drift from the code.

8. **Probe.** `livedata/atlas_probe.py` calls `state_getMetadata` at the
   finalized head, decodes V14+ with a small stdlib SCALE decoder
   (`livedata/scale_meta.py`: compact ints, the type registry, pallet
   storage entries), and resolves each value type to its path or
   primitive name for comparison. Subcommands: `check` (exit code for the
   merge gate) and `watch` (hourly, pages on a new failing set). The merge
   gate runs the probe from the worktree, and the scope gate keeps both
   files unedited.
   Alternative: `substrate-interface`. Rejected: new dependency on the Pi.

9. **Spec detection.** `poll-chain-head` calls `state_getRuntimeVersion`
   at `chain_getFinalizedHead`, over `gate_signal.rpc_endpoints`, then
   falls back to TaoStats. It gets a repo unit, `atlas-poll-chain-head`,
   hourly. The `ExecStartPost` spec lines leave the repotrack unit. The
   upgrade detect step calls the same read function directly, so
   detection is bounded by the 30-minute upgrade timer, not by the poll.

10. **Timers and interruption.** `atlas-upgrade.timer` runs every 30
    minutes; the service has `RuntimeMaxSec=45min` as a backstop only.
    Every subprocess has its own timeout (for example `claude -p` 25 min,
    each test suite 5 min, git and RPC 2 min), so the job records its own
    failures. At start, a saved state of `running` with no lock holder
    means the last run was interrupted: it counts as a failed attempt and
    its one report is `stalled`. `atlas-probe.timer` runs hourly.

11. **Spec supersession and clone lag.** A live spec newer than the one in
    state starts fresh at attempt 1, whatever the old state was. Preflight
    fetches the subtensor clone. If the clone's `spec_version` is still
    below the live spec, the state becomes `waiting`: no attempt is used,
    no model session runs, one `waiting` report is sent, and each timer
    run checks again.

12. **Reporting.** Reuse the telegram module's send path, `load_env`, and
    scrubber. Outcomes: `updated`, `retrying`, `blocked`, `stalled`,
    `waiting`, and `probe-drift` (from the probe `watch`). Delivery dedupes
    on (spec, attempt, outcome). `upgrade/atlas_upgrade.py clear --spec <n>`
    lets the operator release a blocked spec.

## Risks / Trade-offs

- [Subscription token expires headless] → preflight smoke call fails fast
  and reports `blocked: claude auth`. The operator re-logs in.
- [SCALE decoder bug gives a false pass] → decoder tests use a recorded
  live metadata fixture, and the probe asserts it found every pallet named
  in `CHAIN_READS` before checking items.
- [Model edits a reader to stop reading an item] → frozen tests and the
  `CHAIN_READS` coverage test catch lost reads. The operator reads the diff
  in the `updated` report.
- [Probe checks declared shape, not decoding] → accepted for v1. When a
  value type changes, the model updates the type name in `CHAIN_READS`
  and the probe passes even if reader decode code is wrong. The operator
  reads the diff in the `updated` report.
- [Remote moved ahead during a run] → non-fast-forward fails the attempt.
  The retry builds a new worktree from the new `origin/main`.
- [Live chain state changes between probe and push] → accepted. The hourly
  probe catches later drift.
- [Clone lags for days] → the run stays `waiting` with one report. The
  hourly probe still pages on any drift in the meantime.

## Migration Plan

1. Land code with the timers disabled. Run the orchestrator once with
   `--dry-run` (no push, no activate) on the Pi.
2. Enable `atlas-poll-chain-head` and `atlas-probe` timers. Remove the
   spec `ExecStartPost` lines from repotrack.
3. Enable `atlas-upgrade.timer`. Disable Hermes cron `fb98152a3fa1`.
4. After the first real upgrade passes, delete
   `~/.hermes/scripts/atlas_live_spec.py` and the Hermes job.

Rollback: disable `atlas-upgrade.timer` and re-enable the Hermes job. The
probe and chain-head timers stay.
