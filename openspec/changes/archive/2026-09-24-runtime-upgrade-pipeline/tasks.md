## 1. Preconditions (operator, on the Pi)

- [x] 1.1 Find the `claude` binary path and confirm `claude -p "reply ok"` works headless as `pi` from a non-login shell
- [x] 1.2 Record a live metadata fixture (`state_getMetadata` at a finalized block) for decoder tests

## 2. Chain reads and probe

- [x] 2.1 Add `CHAIN_READS` to `livedata/atlas_live.py` and route pinned and derived key builders through it
- [x] 2.2 Add the `livedata/tests` coverage test that fails on an undeclared storage read
- [x] 2.3 Add `livedata/scale_meta.py` (stdlib V14+ metadata decoder) with fixture tests
- [x] 2.4 Add `livedata/atlas_probe.py` with `check` and `watch`, fail-closed on fetch or decode errors, with tests for rename, hasher change, and missing pallet
- [x] 2.5 Add `probe-drift` paging with dedupe on the failing set
- [x] 2.6 Add a read-only `read-knobs` subcommand to `livedata/atlas_live.py` that prints every corpus-stated live knob at one finalized block, with its block hash

## 3. Spec detection

- [x] 3.1 Read `spec_version` through keyless `state_getRuntimeVersion` at the finalized head, TaoStats fallback, record the source
- [x] 3.2 Add `livedata/systemd/atlas-poll-chain-head.{service,timer}` (hourly, matching the disabled units now on the Pi) and `atlas-probe.{service,timer}` (hourly)
- [x] 3.3 Remove the spec `ExecStartPost` lines from `repotrack/systemd/atlas-repotrack-update.service`

## 4. Knowledge activation

- [x] 4.1 Let `knowledge/atlas_kb.py` activate with actor `atlas-upgrade`, refusing runs with rejected units, with tests

## 5. Orchestrator

- [x] 5.1 Add `upgrade/atlas_upgrade.py` step runner (runs from `~/atlas`) with atomic `var/upgrade/state.json`, an exclusive `flock`, per-step timeouts, and the detect step using the keyless spec read directly
- [x] 5.2 Add preflight: author identity, clean `~/atlas`, subtensor clone fetch and lag check (`waiting`, no attempt used), `claude` smoke call, worktree on `upgrade/spec-<n>-a<k>` from `origin/main`
- [x] 5.3 Add the edit step: `read-knobs` output in the prompt, then one `claude -p` call with `upgrade/prompt.md`, tool allowlist without network, `--add-dir` on the subtensor clone, turn cap, timeout
- [x] 5.3a Add the goal gate: regenerate `knowledge/corpus/hashes.json` in the job, fail on an empty diff or a grounded spec that is not live
- [x] 5.4 Add `upgrade/allowed_paths.py` (with `docs/decisions.md` and `knowledge/supersession-markers.json`, denying `livedata/atlas_probe.py` and `livedata/scale_meta.py`) and the scope gate
- [x] 5.5 Add the test gate (discover every `*/tests`) and the probe gate
- [x] 5.6 Add ingest into `~/atlas/var/knowledge/knowledge.db`, commit as vaNlabs, `git push origin HEAD:main`, read-back, `pull --ff-only`, activate
- [x] 5.7 Add retry (1h, 4h, then `blocked`), newer-spec supersession, interrupted-run handling (`stalled`), and `atlas_upgrade.py clear --spec <n>`
- [x] 5.8 Add reporting (`updated`, `retrying`, `blocked`, `stalled`, `waiting`) through the telegram send path and `load_env` with dedupe
- [x] 5.9 Add `upgrade/tests` covering every gate failure (goal and scope included), clone lag, supersession, clear, push rejection, interrupted run, and a full pass with fakes
- [x] 5.10 Add `upgrade/systemd/atlas-upgrade.{service,timer}` (30 min, `RuntimeMaxSec=45min`, `ATLAS_CLAUDE_BIN`)

## 6. Docs

- [x] 6.1 Rewrite `docs/runtime-upgrade.md` for the new pipeline, keeping the `docs/decisions.md` live-chain entry step
- [x] 6.2 Align `knowledge/corpus/SOURCES.md` step order and the subtensor-lag rule (`waiting`) with it, and state that the job regenerates `hashes.json`
- [x] 6.3 Update `AGENTS.md` upgrade paragraph

## 7. Rollout (operator, on the Pi)

- [ ] 7.1 Pull, create `~/atlas-upgrade` worktree, run `atlas_upgrade.py --dry-run`
- [ ] 7.2 Enable the chain-head and probe timers, reload repotrack unit
- [ ] 7.3 Enable `atlas-upgrade.timer`, disable Hermes cron `fb98152a3fa1`
- [ ] 7.4 After the first real upgrade, delete `~/.hermes/scripts/atlas_live_spec.py` and the Hermes job
