# Tasks

## 1. Read-only preparation (workstation)

- [x] 1.1 Read live Finney metadata from the workstation with a throwaway script in the session scratchpad. Record the modifier and default bytes for every item in `CHAIN_READS` that Atlas assumes a default for. Note any configured default that differs from the chain. Verify: the table of item, chain default and Atlas default is pasted into the session notes, and any difference is raised with the operator before 4.x.
- [x] 1.2 Extract the corpus diffs of the 12 historical upgrade commits (`git log --grep='ground Atlas'`) as citation-gate fixtures under `upgrade/tests/fixtures/`. Verify: the fixture files exist and each has its base-corpus block set.

## 2. Scope (B2)

- [x] 2.1 Narrow `upgrade/allowed_paths.py` `ALLOWED` to the corpus, `knowledge/supersession-markers.json` and `docs/decisions.md`. Add `livedata/**` to `DENIED`. Verify: a test asserts `livedata/atlas_live.py`, `livedata/config.json` and `livedata/json.py` are out of scope.
- [x] 2.2 Make the scope gate read porcelain status codes and fail on anything other than a modification (`??`, `A`, `R`, `C`, `D`), also under allowed paths. Verify: tests for a new corpus file, a rename and a deletion each fail at `scope`.
- [x] 2.3 Re-run the scope check in `step_push` right before `add -A`, and compare the staged paths with the checked set. Verify: a test where the `test` step writes a new file into the worktree ends at `scope` with nothing pushed.
- [x] 2.4 Add an import-closure test: every module `atlas_upgrade` and `atlas_probe` import from the repo has `is_allowed()` false. Verify: the test passes, and fails when `livedata/*.py` is re-added to `ALLOWED`.
- [x] 2.5 Rewrite `upgrade/prompt.md` task 6: chain readers are out of scope, and a drift is reported in the final message. Verify: a test checks that the prompt names no `livedata/` path as editable.

## 3. Preflight waits and the release anchor (B2, A4)

- [x] 3.1 Move the base-tree probe into `check_environment`. A failure raises `Waiting("readers")` and a fetch error raises `Waiting("probe")`, each with fixed wording in `WAIT_REASONS`. Pass the probe JSON on to the prompt. Verify: tests show no attempt used, no model call, and one report per reason.
- [x] 3.2 Add `clone_lock` to `repotrack/atlas_repo.py` and hold it for the whole of `cmd update`. A wait timeout records `busy` and exits 2. Verify: a test with a held lock shows `update` waits and then reports busy without touching the tree, and a second test shows two updates serialize.
- [x] 3.3 Implement `anchor(spec)` (tag, then spec-bump commit; the spec at the anchor must match; the anchor must be an ancestor of HEAD), plus `Waiting("anchor")`. Remove the `-n 50` HEAD fallback. Verify: tests on a temp git repo with tags `v1`, `v3`, a bump-only spec 2 and HEAD at 4 cover the diff ending at `v3`, the fallback for 2, and a wait for a missing anchor.
- [x] 3.4 Export the source at the live anchor (`git archive` into `var/upgrade/source-<spec>`, made read-only) under the clone lock, and pass it to the model instead of the clone. Call the repotrack update in-process under the same lock. Verify: a test shows the export holds no file added after the anchor and the claude command has no clone `--add-dir`.

## 4. Expected defaults (A17)

- [x] 4.1 Keep `modifier` and `default` bytes in `scale_meta._storage_entry`. Verify: the decoder test on the stored metadata fixture returns default bytes for a known item.
- [x] 4.2 Add `EXPECTED_DEFAULTS` to `livedata/atlas_live.py` from the 1.1 read, and derive `SUBNET_OWNER_CUT_DEFAULT` from it. Verify: a livedata test asserts that `gate_signal.assumed_defaults`, every `chain_params` default, `SUBNET_PARAM_DEFAULTS` and `SUBNET_OWNER_CUT_DEFAULT` equal the table, with fixed point compared by encoded bits.
- [x] 4.3 Make the probe compare default bytes and add the plain-English "default changed" reason. Verify: a probe test with a fixture whose `SubnetOwnerCut` default differs fails, naming both values. The live probe from the workstation passes.

## 5. Sandbox (B2)

- [x] 5.1 Add `upgrade/sandbox.py` (`sandbox_cmd`) and `upgrade/sandbox_canary.py` as in design D3. Verify: unit tests on the built argv (no `/home` or `/run` bind, worktree read-only, `--clearenv`, net only when asked), and a local run of the canary in both modes reports every check passed.
- [x] 5.2 Add `step_sandbox` before `test`. It runs the canary in both modes and fails closed at `sandbox` on any failed check, a missing bwrap, or unparseable output. Verify: tests with a fake canary output for each failed property, and with bwrap missing.
- [x] 5.3 Route `step_test` and `step_probe` through `sandbox_cmd` (tests without network, probe with network). Verify: tests assert the argv of each suite and probe call. Locally, every suite passes through the sandbox builder.

## 6. Edit session reads (B2)

- [x] 6.1 Replace bare `Read`, `Grep` and `Glob` with path rules for the worktree, the export and `var/upgrade`, and add the explicit denies. Verify: a test asserts the exact `--allowedTools` and `--disallowedTools` lists and that no bare `Read` remains.

## 7. Citation gate (A4)

- [x] 7.1 Add `step_citation` after `goal`. It checks blocks against run and base blocks, and future specs stated as live. Verify: the 12 historical fixtures from 1.2 pass, and synthetic lines with an invented block and with "spec 487 is live" at live 486 each fail at `citation`.

## 8. Deadline (C17)

- [x] 8.1 Add `RUN_BUDGET`, `PUSH_RESERVE` and `Job.budget()`. Cap every pre-push run with it, and check the reserve before `step_push`. Verify: tests with a fake clock fail at `deadline` before the push, with nothing pushed.
- [x] 8.2 Set `TimeoutStartSec=60min` in `upgrade/systemd/atlas-upgrade.service`. Verify: a test parses the unit and asserts that `RUN_BUDGET + 300 <= TimeoutStartSec`.
- [x] 8.3 Add `GATE_PHRASES` entries for `sandbox`, `citation` and `deadline`. Verify: the existing fixed-phrase test covers them.

## 9. Docs and full verification

- [x] 9.1 Update `docs/runtime-upgrade.md`, `upgrade/README.md` and `livedata/README.md` (scope, sandbox, anchor, defaults, lock, deadline) and the AGENTS.md scope sentence. Add a `docs/decisions.md` entry for the scope narrowing. Run `python3 tools/readme_sync.py`. Verify: `tools/tests` passes.
- [x] 9.2 Run every Python suite with the handover loop, then `openspec validate upgrade-sandbox-scope`. Verify: all pass.
- [x] 9.3 Commit in logical pieces as `vanlabs-dev`. Verify: `git var GIT_AUTHOR_IDENT` is checked before each commit.

## 10. Deploy (each step needs operator approval)

- [x] 10.1 Push. Stop `atlas-upgrade.timer` and confirm no `atlas-*` service is active. Run `git pull --ff-only` on the Pi. Copy `atlas-upgrade.service` and run `daemon-reload`. The operator runs `/restart` in Telegram. Verify: Pi HEAD equals origin, and `systemctl --user show atlas-upgrade.service -p TimeoutStartUSec` reads 1h.
- [x] 10.2 On the Pi, run the canary through the deployed `sandbox_cmd` in both modes, and every suite through the sandbox. Verify: all canary checks pass and every suite passes.
- [x] 10.3 Run one edit-session read canary with the deployed command builder (one claude call). Verify: the stream-json shows the `~/.hermes` read denied and the export read allowed.
- [x] 10.4 Run one `python3 upgrade/atlas_upgrade.py run --dry-run` on the Pi. Start `atlas-upgrade.timer`. Verify: the dry run report passes, and the next timer run exits idle.
- [x] 10.5 Archive the change and update the handover tracker and session log.
