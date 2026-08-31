# Corpus snapshot provenance

Verbatim snapshot of the confirmed July 2026 Bittensor corpus (decision
2026-07-12, PRD §21 Q12–15). Machine-readable hashes in
[hashes.json](hashes.json); ingest verifies them before creating any unit.

| field | value |
|---|---|
| Source of truth | `D:\Coding\Bittensor\IntoOps\intoops-routines\references\` |
| Sync date | 2026-08-31 |
| Coverage date | 2026-08-31 (last upstream edit) |
| Files | `ground-truth.md`, `fact-patterns.md`, `negative-claim-rules.md` |

## Known staleness at snapshot time

None. The **2026-08-31 re-sync** (change: network-drift-452) brought the
corpus from spec 443 to spec 452, verified against the merged subtensor code
at tag v452 (`pallets/subtensor/src/staking/lock.rs`,
`pallets/subtensor/src/migrations/migrate_enable_root_weight_setting.rs`,
`pallets/subtensor/src/subnets/weights.rs`,
`pallets/subtensor/src/staking/beta_pricing.rs`,
`pallets/subtensor/src/macros/dispatches.rs`) and live Finney reads at
finalized block 8963841 the same day. Three substantive changes:

- **The takeover gate is a single hotkey** (spec 447, PR #3083, live
  2026-08-14). One hotkey's own rolled conviction must exceed 18% of
  eligible alpha; the aggregate 10% gate is gone. Rewritten in the
  conviction section and the mistakes list.
- **Root Reborn curation is live** (spec 449, PR #3109, enacted 2026-08-27,
  transition observed at block 8938705). `RootWeightSettingEnabled` read
  true and explicit; `RootWeightsCap` read 4096/65535 (1/16) at the root
  entry, the map's only entry. The "installed but dormant" text and the
  negative-claim instruction that denied curation were rewritten, not
  marked, because they instructed the model to deny a live mechanism.
  `stake_into_basket` is open at v452 (the spec-443 `CallDisabled` gate is
  gone).
- **Beta pricing is on-chain** (spec 450, PR #3117, live 2026-08-27):
  baseline, basket index, display price and display beta, `BasketTwr`.
  New section content; the corpus states the convention and never a value.

Spec 448 (staking additions) and 451 (claim hardening) entered as factual
lines. The v443 re-sync (2026-08-06) had brought the rank-pinned bar and
the Root Reborn launch; its text survives where still true.

The prior re-sync (2026-07-28) absorbed the conviction marker (the
2026-07-12 snapshot said ownership transfer was "NOT yet active"; the
enforcement went live with spec 432 on 2026-07-16, and the corpus now says
so) and added the July 2026 emission-model changes, each verified against
the merged subtensor code (tags v432/v440) and the live Finney runtime
(spec_version 440 confirmed via RPC on 2026-07-28): root_prop removed from
the emission share (spec 432, live 2026-07-16) and the Hill emission gate
(spec 440, live 2026-07-27, defaults q = 0.61 / h = 3, both sudo-settable).
[../supersession-markers.json](../supersession-markers.json) is empty; add
new markers there if a corpus claim goes stale before the next re-sync.

## Re-sync procedure

When the upstream grounding changes:

1. Copy the three files from the source of truth into this directory.
2. Regenerate `hashes.json` (sha256 per file, update `sync_date` and
   `coverage_date`).
3. Review `supersession-markers.json` — remove markers the new corpus has
   absorbed, add new known-stale claims.
4. Commit, `git pull` on the Pi, re-run `ingest`, review the validation
   report, `activate` the new run (prior runs deactivate automatically).

The originals in `intoops-routines` are never modified or deleted from this
repo (ATLAS-KB-007 closed as not-applicable).
