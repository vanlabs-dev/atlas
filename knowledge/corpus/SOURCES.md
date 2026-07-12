# Corpus snapshot provenance

Verbatim snapshot of the confirmed July 2026 Bittensor corpus (decision
2026-07-12, PRD §21 Q12–15). Machine-readable hashes in
[hashes.json](hashes.json); ingest verifies them before creating any unit.

| field | value |
|---|---|
| Source of truth | `D:\Coding\Bittensor\IntoOps\intoops-routines\references\` |
| Sync date | 2026-07-12 |
| Coverage date | 2026-06-25 (last upstream edit) |
| Files | `ground-truth.md`, `fact-patterns.md`, `negative-claim-rules.md` |

## Known staleness at snapshot time

`ground-truth.md` states conviction ownership transfer is "NOT yet active" —
**verified still true on-chain 2026-07-12** (Phase 3 repo evidence + Phase 4
chain evidence: mainnet runs spec 424; the enforcement code is spec 425,
unreleased; activation was announced 2026-07-02 but enactment is pending —
see the decision log's chain-evidence entry). Ingest marks the affected
units `conflicting` via
[../supersession-markers.json](../supersession-markers.json) so retrieval
surfaces the announced-but-pending status; the marker (and eventually the
corpus itself) updates when the chain head reports spec_version ≥ 425.

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
