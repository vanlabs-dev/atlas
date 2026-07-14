## 1. Chain identity source (live-data)

- [x] 1.1 Extended `livedata/discover_taostats.py` with identity probes (`/api/subnet/identity/v1`, limit=2, page 1+2) + a proposed envelope; a focused 2-call off-device sample confirmed the real shape (the on-device full run remains the operator's ratification step)
- [ ] 1.2 Operator gate (pending operator): a **PROPOSED** entry recording the sample findings is drafted in `docs/decisions.md` — the operator ratifies it via the on-device discovery run (their action)
- [x] 1.3 Pinned `livedata/schemas/taostats/subnet-identity.v1.schema.json` from the real sample: `{pagination, data}`, per-item `netuid` required, `github_repo`/`subnet_name` nullable; owner absent from this endpoint (documented in the schema `_source`)
- [x] 1.4 Added `subnet_identity_taostats` to `livedata/config.json` (path, `limit=200`, schema, envelope) and `_pp_subnet_identity_taostats` returning `netuid → { github_repo, subnet_name, owner_ss58=None }` (endpoint carries no owner)
- [x] 1.5 Pagination handling via `run_subnet_identity`: pages to completion, exposes `complete`; a failed/unfinished pagination is reported degraded (feeds the mass-discard guard). At `limit=200` the 129-subnet map is one call. Fleet `_fetch_identity` wired to it
- [x] 1.6 Tests (off-device): valid page extracts the map (null + real `github_repo`, owner None); pagination metadata surfaced; schema drift (missing netuid) → schema-drift, no exposure; aggregator single-page-complete, multi-page aggregate, failed-page degraded

## 2. Registry + fleet store

- [x] 2.1 Create `fleet/` module with `var/fleet/` (clones) and `var/fleet/fleet.db` (gitignored); confirm `.gitignore` covers `var/fleet/` (covered by wholesale `var/`)
- [x] 2.2 Define the registry schema: `slots` (`netuid` PK, `github_repo` normalized, `owner_ss58`, `fingerprint`, `epoch`, `default_branch`, `status`, `local_sha`, `clone_size_bytes`, `first_seen_block`, `last_reconciled`, `last_fetch_success`), epoch-scoped `change_ranges` (repotrack range shape + `netuid` + `epoch`), `epochs` (`netuid`, `epoch`, `fingerprint`, `github_repo`, `owner_ss58`, opened/closed + block), and an `audit` table — all created by `open_store`, exercised by the driver
- [x] 2.3 URL normalization + validation helper: canonicalize the free-text on-chain `github_repo` (`org/repo`, trailing `.git`, scheme, host); return canonical clone URL or an `invalid-url` verdict
- [x] 2.4 Fingerprint helper: `hash(owner_ss58 ‖ normalized_github_repo)` (excludes subnet name so a rename does not repoint)

## 3. Reconciler (desired vs actual → bounded plan)

- [x] 3.1 Implement the plan builder: compare the validated desired map to the registry and emit per-slot actions CLONE / UPDATE / REPOINT / DISCARD / NO-REPO exactly per the design's action table
- [x] 3.2 Implement the **mass-discard guard**: DISCARD and REPOINT are produced only when the identity fetch is `status: ok`, schema-valid, within freshness, and paginated to completion; on any degradation the pass makes no destructive change and preserves last good state (`build_plan(fetch_ok=False)` → registry-only work)
- [x] 3.3 Bound the pass: cap CLONE/REPOINT to `max_new_clones_per_pass`; UPDATE all active slots; make execution idempotent and resumable via the `status` field (`pending`→`active`, `no-repo`/`invalid-url`/`quarantined`/`unreachable`) — plan-level `apply_bound` + `pending`→resume, with the driver persisting transitions (bounded-then-converges test proves it)
- [x] 3.4 Record every reconcile decision to the `audit` table with actor/action/detail (redacted) — the driver audits every action

## 4. Fleet clone + update (reuse repotrack primitives)

- [x] 4.1 Fleet `setup_clone(netuid, url)`: `git clone --filter=blob:none --no-checkout --no-recurse-submodules <url> var/fleet/<netuid>/`, checkout is the remote default branch (no GitHub API call), record the resolved branch, disable the push URL; verify non-executed (no build/test/hook step exists in the path). `--no-checkout` lets the file-count cap gate the tree before any blob is fetched
- [x] 4.2 Enforce per-repo size + file-count caps during/after clone; on breach abort, clean up (Windows-safe rmtree), mark `quarantined`, continue
- [x] 4.3 Fleet `update_clone(netuid)`: reuse repotrack primitives for clean-tree check → fetch → fast-forward-or-reset (never merge) → recorded change range via `collect_range`; `record-failed` degradation preserves the advance and reports it. The driver persists the range scoped to `(netuid, epoch)` (`_record_range`)
- [x] 4.4 Promoted repotrack's private `_collect_range` to a documented public reuse surface (`collect_range` alias); no copy-paste duplication; subtensor `update()`/`setup()` control flow unchanged, repotrack suite green (38)
- [x] 4.5 Optional `GITHUB_TOKEN`: injected via `GIT_CONFIG_*` env (`http.extraHeader`) per invocation, so it reaches the request but never lands in argv (ps-safe) or the clone's on-disk config (test-verified); registered for redaction; `GIT_TERMINAL_PROMPT=0` prevents auth hangs; anonymous still works

## 5. Churn handling (repoint / discard / epochs)

- [x] 5.1 REPOINT: on fingerprint change for a slot, discard `var/fleet/<netuid>/`, close the current epoch, open a new epoch (`fingerprint`, opened block), then CLONE the new repo (rename-only does NOT repoint — tested)
- [x] 5.2 DISCARD: on a validated absence from the desired map, remove the clone and delete the slot row; keep the `epochs`/`change_ranges` rows for provenance (closed epochs). Guarded so a degraded fetch never discards
- [x] 5.3 NO-REPO: a slot present on-chain but with no usable `github_repo` is recorded (`no-repo`/`invalid-url`) without a clone
- [x] 5.4 Verify change history never mixes epochs: `change_ranges` are keyed by `(netuid, epoch)`; a re-point's new ranges land under the new epoch while the prior epoch's rows are preserved (tested)

## 6. Scheduling

- [x] 6.1 Add `fleet/systemd/atlas-fleet.service` (runs one bounded reconcile pass) and `atlas-fleet.timer` (every 6h, offset :20), independent of the repotrack timer; sudo install steps documented in `fleet/README.md`. Plus `fleet/config.json` and a CLI entrypoint (`status` / `reconcile [--identity-file] [--max-new]`); the auto identity source fails closed until §1
- [x] 6.2 Fleet `status` CLI: registry summary (counts by status, total clone bytes, last reconcile, stalest active slot) for operator inspection
- [x] 6.3 Disk ceiling: `min_free_bytes` stops new CLONEs/REPOINTs and records a `disk-limited` status (resumed on a later pass) rather than filling the disk

## 7. Tests (off-device)

- [x] 7.1 Reconcile plan: fixtures for CLONE (new), UPDATE (unchanged fp), REPOINT (changed fp), DISCARD (absent), NO-REPO — exact action set asserted (test_reconciler)
- [x] 7.2 Mass-discard guard: a degraded identity fetch produces **zero** DISCARD/REPOINT and preserves the registry (test_reconciler + test_driver)
- [x] 7.3 Bounded + resumable: a pass capped at N leaves the rest `pending`; a second pass converges; a converged re-run is a no-op (test_reconciler + test_driver)
- [x] 7.4 Clone policy on fixture git repos: blobless (partial, not shallow), remote-default-branch checkout, push URL disabled, **submodule content not fetched**, size/file-cap breach → quarantined (test_clone)
- [x] 7.5 Epoch segmentation: a REPOINT closes the old epoch and starts a new one; `(netuid, epoch)`-scoped ranges never blend the two projects (test_driver)
- [x] 7.6 URL normalization/validation: `org/repo`, `.git`, scheme/case variants canonicalize; non-GitHub / junk → `invalid-url` skip (test_registry + test_driver)
- [x] 7.7 Redaction: `GITHUB_TOKEN` never appears in the clone's on-disk config (test_clone) nor in an audit line (test_clone); `redact` strips registered secrets
- [x] 7.8 Full `fleet` suite green off-device (76 tests); `repotrack` suite still green (38, singleton untouched). `livedata` unchanged (no adapter yet — §1)

## 8. Close-out

- [x] 8.1 `fleet/README.md`: architecture, the once-off tracking-policy decision, discovery-gate step, commands, systemd install, and the never-execute / blobless / mass-discard-guard invariants
- [x] 8.2 Update root `README.md` to add the fleet component (capability status row + repo-layout line) alongside repotrack/livedata
- [ ] 8.3 On-device acceptance on the Pi (pending operator sign-off + timer install; technical acceptance driven 2026-07-14/15 over SSH): live identity fetch works — **129 subnets, 114 with a public `github_repo`, 15 without**; bounded reconciles seeded **4 active blobless clones** (verified `blob:none`, non-shallow, push URL DISABLED, real checkout, **GITHUB_TOKEN absent from `.git/config`**); per-slot fail-closed proven with real data (dead `username/repo` → `unreachable`, junk → `invalid-url`, neither blocks); exit 0 with a dead repo present (after the errors→per-slot-bucket fix, commit 3b09127); epochs recorded per netuid. **Full seed complete 2026-07-14** (`reconcile --max-new 200`): **104 active clones** (~851 MB blobless), 10 unreachable (backed off), 1 invalid-url, 14 no-repo = 129 total; `deferred: 0`, exit 0. Backoff verified at scale (a backed-off dead repo was skipped: `planned` 128 not 129). **Remaining (operator):** install the systemd timer (sudo), ratify the discovery gate (1.2), and sign off acceptance. No change range captured yet (initial clones; ranges appear when a tracked repo next advances)
