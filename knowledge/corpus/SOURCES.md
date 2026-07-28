# Corpus snapshot provenance

Verbatim snapshot of the confirmed July 2026 Bittensor corpus (decision
2026-07-12, PRD §21 Q12–15). Machine-readable hashes in
[hashes.json](hashes.json); ingest verifies them before creating any unit.

| field | value |
|---|---|
| Source of truth | `D:\Coding\Bittensor\IntoOps\intoops-routines\references\` |
| Sync date | 2026-07-28 |
| Coverage date | 2026-07-28 (last upstream edit) |
| Files | `ground-truth.md`, `fact-patterns.md`, `negative-claim-rules.md` |

## Known staleness at snapshot time

None. The 2026-07-28 re-sync absorbed the prior conviction marker (the
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
