# runtime-upgrade-pipeline: ship

Session 4, 2026-09-24. Verify PASS (`08-verify.md`). Change archived at
`openspec/changes/archive/2026-09-24-runtime-upgrade-pipeline/`. Specs
merged: `runtime-upgrade` and `chain-read-probe` (new), `knowledge-base`
and `live-data` (modified).

## What shipped

- `upgrade/atlas_upgrade.py`: the orchestrator, with state, lock, retry,
  reports, `clear`, `status`, and `run --dry-run`. Also
  `upgrade/allowed_paths.py`, `upgrade/prompt.md`, and 36 tests.
- `livedata/atlas_probe.py` (`check`, `watch`) and `livedata/scale_meta.py`
  (stdlib V14/V15 metadata decoder), with a recorded spec-469 fixture.
- `livedata/atlas_live.py`: `CHAIN_READS` (enforced in `storage_prefix`),
  a keyless `read_live_spec` with TaoStats fallback, a `source` column on
  `spec_upgrades`, and `read-knobs`.
- `knowledge/atlas_kb.py`: activation as `atlas-upgrade` refuses rejected
  units.
- User units: `atlas-poll-chain-head`, `atlas-probe` (hourly),
  `atlas-upgrade` (30 min). The spec poll left the repotrack unit.
- Docs: `docs/runtime-upgrade.md` rewritten. `SOURCES.md`, `AGENTS.md`,
  `README.md`, the component READMEs, and `docs/decisions.md` updated.

Deviations from the plan are recorded in `docs/decisions.md` (runtime
upgrade entry): `TimeoutStartSec` in place of `RuntimeMaxSec`, post-push
failures block at once, the model gets no Bash, and the fixture was
recorded from the workstation.

## Operator follow-ups (tasks 7.1 to 7.4, open at archive)

Run these as `pi` on the Pi. Units are user-level.

1. `git -C ~/atlas pull --ff-only`, then run
   `ATLAS_CLAUDE_BIN=~/.local/bin/claude python3 ~/atlas/upgrade/atlas_upgrade.py run --dry-run`.
   The job creates the `~/atlas-upgrade` worktree itself. Expect the dry
   run to fail at the probe gate until finding 1 is fixed.
2. Copy `livedata/systemd/atlas-{poll-chain-head,probe}.*` to
   `~/.config/systemd/user/`, `daemon-reload`, enable both timers. Copy the
   repotrack unit the same way and reload it.
3. Copy `upgrade/systemd/atlas-upgrade.*`, enable the timer, and disable
   Hermes cron `fb98152a3fa1`.
4. After the first real upgrade, delete
   `~/.hermes/scripts/atlas_live_spec.py` and the Hermes job.

## Findings to act on

1. **Live drift:** `RootWeightSettingEnabled` and `RootWeightsCap` are
   absent from the spec-469 metadata. The gate pass still reads both as
   unset defaults, and the corpus and `docs/decisions.md` state them as
   live facts. The probe fails on them, so the hourly watch will page as
   soon as it is enabled, and every upgrade attempt fails the probe gate
   unless the model fixes the reads. Needs a small reader and corpus fix.
2. The Pi's existing units are user-level, but the repotrack and subnt
   install comments still say `sudo cp` to `/etc/systemd/system/`.

## Still planned (separate changes)

The subnt v2 JSON export, moving the reader wrapper back into the repo,
and Pi cleanup.
