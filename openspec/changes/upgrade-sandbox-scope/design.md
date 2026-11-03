# Design: upgrade-sandbox-scope

## Context

See proposal.md (Why). The facts below come from the read-only checks on 2026-11-03.

Pi state:
- `bwrap` is at `/usr/bin/bwrap`. The machine runs systemd 257 and Python 3.13.5.
- The job runs as `pi`, which is in the `sudo` and `docker` groups.
- The upgrade and repotrack timers both fired at 13:01:20.

Subtensor clone (`var/repotrack/subtensor`):
- It is a full clone, not blobless. `.git` is 356 MB and the HEAD tree is 150 MB.
- It has release tags `v<spec>` for every live spec from 473 to 486 except 485, and for 464 to 471.
- No `v472` tag exists, although 472 went live.
- `v486` is `72323e132`, the release-486 merge. That is the commit the 486 corpus already cites.
- HEAD is at 487 (`57a841029 bump spec`, 2026-10-27).

Upgrade history:
- The job has been able to run since 2026-09-24. Its 12 commits never touched `livedata/` and never added or renamed a file.

## Goals / Non-Goals

**Goals:**
- No model-written code is ever executed by the job or by a long-lived service.
- The gates cannot see secrets, sockets or `sudo`. The job proves this on the real call path in every attempt.
- The model sees only shipped source.

**Non-Goals:**
- A dedicated service account for the job. The bubblewrap sandbox covers the gate window, and the narrowed scope covers what happens after the push.
- The KB battery gate. It is deferred to WP13 (A6).
- Sandboxing ingest. It runs origin/main code over data files the job checks.
- Sandboxing the edit session process. Its tool scope is the control (see D5).

## Decisions

### D1. Scope narrows to data files

`ALLOWED` becomes:
- `knowledge/corpus/**`
- `knowledge/supersession-markers.json`
- `docs/decisions.md`

The scope gate parses `git status --porcelain=v1 -z -uall` with status codes. Any code other than ` M` or `M ` fails, so `??`, `A`, `R`, `C` and `D` all fail. A rename or copy names both sides.

`step_push` calls the same check on the worktree right before `add -A`, then compares the staged path list with the checked list.

Alternatives considered:
- Keep `livedata/` and freeze `CHAIN_READS`, the RPC client and the endpoints in a denied module, with a per-key allowlist on `config.json`. Rejected by the operator on 2026-11-03: a data-only scope is simpler to reason about, and history shows no need for reader edits.

### D2. The probe moves into preflight

The probe still runs from the live tree, as today in `step_edit`. It now runs before an attempt is counted.
- **Failure:** the job raises `Waiting("readers")` with fixed wording: "chain readers need an operator fix".
- **RPC failure:** the probe fails closed. A metadata fetch error also waits, as `Waiting("probe")`, so an RPC blip uses no attempt.

The gate probe after the edit still runs on the worktree, inside the sandbox. With `livedata/` out of scope it reads the same code. It stays as a check that the edited tree imports and runs.

The prompt drops task 6 (fix readers). It tells the model that chain readers are out of scope.

### D3. Sandbox builder (`upgrade/sandbox.py`)

`sandbox_cmd(worktree, network: bool, argv) -> List[str]` builds a `bwrap` command. Any reachable home, socket, secret or writable worktree counts as a failure.

Mounts:
- `--ro-bind` for `/usr`, `/etc`, and the `/bin`, `/lib`, `/lib64` and `/sbin` symlinks (`--symlink` where they are links)
- `--proc /proc`, `--dev /dev`
- `--tmpfs /tmp`, `--tmpfs /home`, `--dir /home/pi`, `--tmpfs /run`
- `--ro-bind <worktree> <worktree>`

Namespaces and process:
- `--unshare-all`, plus `--share-net` only when `network` is true
- `--die-with-parent`, `--new-session`
- `--clearenv`, then `--setenv` for `PATH`, `HOME=/home/pi`, `LANG=C.UTF-8`, `PYTHONDONTWRITEBYTECODE=1` and `TMPDIR=/tmp`
- `--chdir` to the target

Details:
- `/etc/resolv.conf` for the probe comes with the `/etc` bind.
- `/run` is a fresh tmpfs, so the D-Bus socket, the docker socket and `/run/user/1000` are absent.
- `/var` is not bound.
- bwrap sets `NO_NEW_PRIVS`, so `sudo` cannot gain privileges.

The canary (`upgrade/sandbox_canary.py`, run with `python3 -I`) checks from inside and prints JSON. A check passes only when the property holds:
- `~/.ssh`, `~/.hermes`, `~/.claude`, `/home/pi/atlas/.env` and the deploy key path are all absent.
- `/run/user/1000/bus`, `/run/dbus/system_bus_socket` and `/var/run/docker.sock` are absent.
- `/proc/self/status` shows `NoNewPrivs: 1`.
- `sudo -n true` fails, or `sudo` is missing.
- Writing a file in the worktree fails with `EROFS` or `EACCES`.
- A TCP connect to 1.1.1.1:443 fails when network is off.
- The environment has no `TELEGRAM`, `ANTHROPIC`, `HERMES`, `GIT_SSH` or `SSH_AUTH` keys.

The canary runs twice per attempt, once per network mode. Its source lives in `upgrade/` (denied) and is read from the live tree, then bound read-only.

Tests write only to `/tmp` (tmpfs). Some git-based tests need an identity: with an empty HOME they get none. Tests that need one must set it explicitly (WP7 tests already do). Running the full suite in the sandbox on the Pi is a deploy check.

The WP7 residual is that `_default_disk_free` reads the tmpfs. Tests that rely on real free disk inject a probe already; any that do not show up in the Pi sandbox run.

Alternatives considered:
- `systemd-run --user -p ProtectHome=tmpfs -p PrivateNetwork=yes`. User managers apply `PrivateNetwork` only with user namespaces and are harder to assert. bwrap is explicit per call and testable as a pure command builder.

### D4. Release anchor and source export

`anchor(spec)` resolves the release anchor:
1. If `git rev-parse --verify -q refs/tags/v<spec>^{commit}` succeeds, the anchor is that tag (kind `tag`).
2. Otherwise it is the oldest commit from `git log --reverse --format=%H -S "spec_version: <spec>," -- runtime/src/lib.rs` (kind `spec-bump`).
3. Either way, `git show <anchor>:runtime/src/lib.rs` must state `<spec>`, and the anchor must be an ancestor of HEAD.
4. If none of that holds, the job raises `Waiting("anchor")`.

The diff is `git diff <corpus-anchor> <live-anchor>` and the log is `<corpus-anchor>..<live-anchor>`. The `-n 50` fallback is removed.

The source export:
- `git archive <live-anchor> | tar -x -C var/upgrade/source-<spec>/`, cleared first, reused while its `.atlas-anchor` marker matches. It is not chmod'ed: the model's write rules cover the worktree only, and the scope gate runs on the worktree.
- Size is about 150 MB, against 98 GB free.
- The model gets `--add-dir` for the export instead of the clone.

`atlas_repo.py update`, anchor resolution, diff and export all run under the clone lock (D6).

### D5. Edit-session read scope

`--allowedTools` keeps `Read`, `Grep` and `Glob` only as path rules over the worktree, the export and `var/upgrade`, for example `Read(//home/pi/atlas-upgrade/**)`. Absolute paths come from the job at run time.

`--disallowedTools` adds:
- `Read(~/.ssh/**)`, `Read(~/.hermes/**)`, `Read(~/.claude/**)` and `Read(**/.env*)`
- the same patterns for `Grep` and `Glob`

The session already has `--tools Read,Grep,Glob,Edit,Write`, so no Bash and no web tools.

End-to-end check: one approved canary session on the Pi with this exact command builder. The prompt asks it to read a planted file under `~/.hermes` and one under the export. The deny must show in the stream-json tool result. It is a deploy step, not a per-run check, because it costs a model call.

### D6. Clone lock

`repotrack/atlas_repo.py` gets `clone_lock(clone_dir, wait_s)`. It is a context manager that flocks `var/repotrack/update.lock`, polling `LOCK_NB` every 2 s up to `wait_s`.
- `cmd update` holds it for the whole update. A timeout records the run as `busy` and exits 2.
- The upgrade job imports the same helper. It holds the lock with `wait_s=900` around `update`, `clone_spec`, anchors, diff and export.
- The job runs the update as a child process while it holds the lock, and names the clone in `ATLAS_REPO_LOCK_HELD` so the child does not wait on its parent. A crash in the update cannot take the job down. (Changed from in-process during apply.)

The job still treats a failed update as "clone may lag" and reads `clone_spec`, as today.

### D7. Run deadline

`RUN_BUDGET = 50 * 60` from `run_once` start, with `PUSH_RESERVE = 15 * 60` covering git push, readback, pull and activate.

`Job.budget(name)` returns `min(TIMEOUT[name], deadline - PUSH_RESERVE - now)` and raises `StepFailed("deadline")` when the result is under 30 s. Every pre-push call to `self.run` and `self.py` passes `self.budget(...)`.

Before `step_push` starts, the job checks that `deadline - now >= PUSH_RESERVE`. Post-push steps keep their own timeouts.

`TimeoutStartSec` becomes `60min`. A test parses the unit and asserts that `RUN_BUDGET + 5 min <= TimeoutStartSec`.

`GATE_PHRASES` gains entries for `deadline`, `sandbox` and `citation`. `WAIT_REASONS` gains `readers`, `probe` and `anchor`.

### D8. Citation gate

The gate reads `git diff -U0 <base> -- knowledge/corpus` in the worktree and checks added lines (`+`, not `+++`).

Block citations:
- Pattern: `(?i)(finalized\s+)?block\s+([\d,]{6,})`.
- Each number, without commas, must be in `run_blocks ∪ base_blocks`.
- `run_blocks` holds the knobs block and the preflight probe block. Both are parsed from their JSON, which the job already captures.
- `base_blocks` holds every block number in the base corpus.

Future specs:
- Pattern: `(?i)\bspec(?:_version)?\b[^0-9\n]{0,12}?(\d{3})\b`.
- Any number above live fails. The model sees nothing past the live anchor, so a later spec can only come from unshipped code. (The 472 run named its clone at 473; under the new prompt there is no clone spec to name.)

Fixture tuning: a test replays the 12 historical upgrade commits. Each added exactly two blocks not in its base corpus: the knobs read and the probe read, so the block rule has no false positive. The 472 commit names spec 473 (its clone) and fails the future-spec rule, which is intended. A synthetic line covers each failure mode.

Known limit: the gate cannot tell an unshipped mechanic stated without a number. D4 removes the source of that error. The gate is a backstop.

### D9. Expected defaults

`scale_meta._storage_entry` keeps `modifier` (`0` Optional, `1` Default) and `default` (bytes).

`atlas_live.EXPECTED_DEFAULTS` maps `(pallet, item)` to hex SCALE bytes, read once from live metadata at spec 486 and recorded with the block. Constants derive from it, for example `SUBNET_OWNER_CUT_DEFAULT` decodes from the table.

The probe compares exact bytes. A mismatch adds a failure with reason `default <chain hex> (<decoded>), expected <hex> (<decoded>)` and a `_REASON_RE` plain line: "default changed (chain X, Atlas assumes Y)".

Decoding for display uses the existing codecs:
- `u16`, `u64`, `bool`
- U64F64 shown as an exact fraction rounded to 6 places

A test in `livedata/tests` asserts that these all equal the decoded table, and that every item they name has a table entry:
- `config.json` `gate_signal.assumed_defaults`
- every `chain_params` watch `default`
- `SUBNET_PARAM_DEFAULTS`
- `SUBNET_OWNER_CUT_DEFAULT`

Fixed-point values compare by encoding the configured float with the runtime's conversion (`round(x * 2**64)`). The comparison does not decode to a float.

Before the table is written, a workstation read of live metadata must show what the chain defaults are today. If any configured default already differs (for example the EmissionBarQuantile 0.61 code default), the operator decides whether to fix the config or record the difference, before deploy.

## Risks / Trade-offs

- **[Rename blocks the job]** An item rename now waits for the operator instead of self-fixing. It has happened 0 times in 12 upgrades. The hourly probe already pages on drift.
- **[Sandbox breaks a suite]** A test that depends on HOME, git identity or real disk fails in the sandbox and blocks upgrades. Mitigation: run every suite through the sandbox builder on the Pi before re-enabling the timer.
- **[No tag for a live spec]** The 472 case falls back to the spec-bump commit. That commit can predate other same-spec commits. The prompt names the anchor kind, so the model knows the anchor is approximate.
- **[Default check pages on deploy]** If a runtime default already moved, the first hourly probe pages. Mitigation: the workstation read before deploy (D9).
- **[Citation regex false positives]** Tuned on the 12 historical commits. A false positive costs one attempt and a readable `citation` report.
- **[Read path rules]** Claude Code permission-rule semantics may change across CLI updates. The deploy canary (D5) is the proof. Re-run it after a Claude Code update, as for WP10.

## Migration Plan

1. Implement and test on the workstation. Commit locally.
2. Do the read-only workstation reads:
   - live metadata defaults (D9)
   - the citation replay
   - the sandbox builder against local suites
3. Get approvals and deploy:
   1. Push.
   2. On the Pi, `systemctl --user stop atlas-upgrade.timer`. Confirm no `atlas-*` service is active.
   3. `git pull --ff-only`.
   4. Copy `atlas-upgrade.service` and run `daemon-reload`.
   5. The operator runs `/restart` in Telegram (the MCP servers import `atlas_live`).
   6. Run the sandbox canary through the deployed builder, both modes.
   7. Run every suite through the sandbox on the Pi.
   8. Run one edit-session read canary (one claude call).
   9. Run one `atlas_upgrade.py run --dry-run` (prepare, sandbox, test, probe).
   10. `systemctl --user start atlas-upgrade.timer`.
4. Rollback: revert the commits and pull. `TimeoutStartSec=60min` is harmless with the old code.
