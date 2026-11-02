# Tasks

## 1. Report and state plumbing

- [ ] 1.1 Make `flush_pending` return whether it changed state. Drop a pending report whose spec is below `state["spec"]`. Save on every `_run_locked` path that changed state. Verify: tests `test_pending_delivered_on_idle_run_is_saved` and `test_stale_pending_report_dropped` pass.
- [ ] 1.2 Give `report()` an optional explicit key for reports that are not keyed by `spec:attempt`. Verify: the existing `ReportTest` still passes.

## 2. Environment preflight before the attempt (C12, A2)

- [ ] 2.1 Move the environment checks ahead of the attempt counter. Add the `waiting-<reason>` state and fixed report wording for `auth`, `identity`, `dirty` and `diverged`. Verify: tests show the auth, dirty and diverged cases leave `attempt == 0`, send one report each, and quote no raw output.
- [ ] 2.2 Check the identity with the `GIT_AUTHOR_*` and `GIT_COMMITTER_*` keys stripped. Make `FakeJob` return a wrong identity whenever those overrides are absent and the repo identity is set wrong. Verify: the test fails against the old `self.git` check.
- [ ] 2.3 Add a fetch and `merge-base --is-ancestor HEAD origin/main` to preflight, and repeat the ancestry check in `step_push` before the push. Verify: tests show a tree that is behind passes, and divergence just before the push fails at `push` with no push call.

## 3. Post-push recovery and knowledge currency (A1)

- [ ] 3.1 Save `post_push` (`commit`, `run_id`, `gate`) before the push. Give the blocked message the pull and activate commands. Verify: test `test_pull_failure_blocks_with_commands`.
- [ ] 3.2 Add `reconcile()` before the early return:
  - Retry the pull.
  - Check knowledge currency against `hashes.json` and self-activate a qualifying run.
  - Clear a post-push block only when it is verified.
  - Stop the early return from rewriting the state to `idle`.

  Verify: tests show:
  - A corpus that catches up while blocked stays blocked.
  - A repaired tree clears after the pull and activation.
  - A stale run is activated once.
  - With no candidate, one stale report is sent.
  - A run from the operator's actor or a different hash is not activated.
- [ ] 3.3 Make the `FakeJob` knowledge base a real temporary SQLite store with the `atlas_kb` schema, so the currency check runs real SQL. Verify: the tests in 3.2 use it.

## 4. Pulled-commit report and gateway restart (F2, F3)

- [ ] 4.1 Record the pre-pull `HEAD`, list the non-corpus commits pulled, and cap them at 10 in the `updated` report. Verify: test `test_updated_lists_code_commits`.
- [ ] 4.2 Add the gateway restart: a safety check from `systemctl` and `gateway_state.json`, a restart, then confirmation with `is-active`. Unsafe or failed sends one "restart needed" report, and later runs retry. It also runs after a `reconcile` pull that brought in code. Verify: tests cover the idle restart, the busy gateway (report once, then restart later), a stale or missing state file treated as unsafe, a corpus-only pull with no restart, and a restart failure that leaves the status `updated`.

## 5. knowledge_status (A3)

- [ ] 5.1 Join `kb_status` on the active `run_id` and add `staged_newer_run`. Verify: a new test in `knowledge/tests/test_server.py` with an older active run and a newer staged run.

## 6. Docs and close-out

- [ ] 6.1 Update `docs/runtime-upgrade.md` and `upgrade/README.md` for the waiting reasons, the post-push recovery, self-activation and the gateway restart. Verify: a read-through, and `python3 tools/readme_sync.py --check` passes.
- [ ] 6.2 Run every Python suite with the loop in the handover. Verify: all suites pass.
