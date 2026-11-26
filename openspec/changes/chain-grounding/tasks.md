# Tasks

## 1. Inspection (2026-11-27)

- [x] 1.1 Read the upgrade, livedata, repotrack and telegram code, the Pi timers and the clone. Verify: plan approved by the operator with decisions 1A, 2A and 3.
- [x] 1.2 Confirm the tag to spec mapping and the working RPC endpoint. Verify: design.md "Facts checked".

## 2. Deterministic parts

- [x] 2.1 Call decoding in `livedata/scale_meta.py`. Verify: livedata suite passes (391 tests).
- [x] 2.2 `grounding/snapshot.py` with diff and DIFF.md. Verify: live snapshot at spec 497; unit tests for decode and diff.
- [x] 2.3 `grounding/yamlsub.py`, `ledger.py`, `history.py`, `render.py`, `grounding_scope.py`. Verify: unit tests.

## 3. Verification

- [x] 3.1 `verify.py` and the worker and critic prompts. Verify: unit tests with faked model runs.
- [ ] 3.2 Bootstrap every section through worker and critic at v497. Verify: operator reviews GROUNDING.md and the UNVERIFIED list before the first push.

## 4. Operations

- [x] 4.1 `atlas-grounding.{service,timer}`. Verify: unit-file test.
- [x] 4.2 gitleaks 8.30.1 on the Pi and the workstation, run by `tools/git-hooks/pre-commit`. Verify: hook tests, including a real-scanner test.
- [ ] 4.3 README, `grounding/README.md`, `docs/decisions.md`. Verify: `tools/tests` passes.
- [ ] 4.4 Install the timer on the Pi after the push. Verify: `systemctl --user list-timers` shows it, one run exits 0.
- [ ] 4.5 Forced end-to-end run `force --from v495 --to v497`. Verify: the log lists the stale claims, and the result is pushed.
