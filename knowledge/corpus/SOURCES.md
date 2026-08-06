# Corpus snapshot provenance

Verbatim snapshot of the confirmed July 2026 Bittensor corpus (decision
2026-07-12, PRD §21 Q12–15). Machine-readable hashes in
[hashes.json](hashes.json); ingest verifies them before creating any unit.

| field | value |
|---|---|
| Source of truth | `D:\Coding\Bittensor\IntoOps\intoops-routines\references\` |
| Sync date | 2026-08-06 |
| Coverage date | 2026-08-06 (last upstream edit) |
| Files | `ground-truth.md`, `fact-patterns.md`, `negative-claim-rules.md` |

## Known staleness at snapshot time

None. The **2026-08-06 re-sync** (change: network-drift-443) brought the
corpus from spec 440 to spec 443, verified against the merged subtensor code
at tag v443 (`pallets/subtensor/src/coinbase/subnet_emissions.rs`,
`pallets/subtensor/src/lib.rs`) and live Finney chain reads taken the same
day. Two substantive changes:

- **The emission gate bar is rank-pinned** (spec 441, PR #3014, live
  2026-08-03). `EmissionBarRank` (N) pins theta to the Nth-largest positive
  demand share; q-mass survives only as the N = 0 fallback, so a live
  `EmissionBarQuantile` of 0.75 is inert. Chain-verified 2026-08-06: rank
  unset, so the v443 code default of 32 applies and rank mode is active.
  The v441 release notes state the default is 64 and are wrong. The prior
  snapshot's q-mass description is superseded, not merely qualified, so it
  was rewritten rather than marked.
- **Root Reborn is live but curation-gated** (spec 441, live 2026-08-03).
  Root dividends now flow into per-validator beta baskets, only
  root-registered hotkeys earn them, and calls 122/123 are retired — but
  `RootWeightSettingEnabled` is false on chain, so every fund runs the null
  strategy and dividends accumulate in place.

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
