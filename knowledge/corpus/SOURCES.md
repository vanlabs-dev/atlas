# Corpus snapshot provenance

The three grounding files Atlas retrieves from. Machine-readable hashes in
[hashes.json](hashes.json); ingest verifies them before creating any unit.

| field | value |
|---|---|
| Source of truth | `D:\Coding\Bittensor\IntoOps\intoops-routines\references\` |
| Sync date | 2026-09-20 |
| Coverage date | 2026-09-20 |
| Grounded at | Finney `spec_version` **467** |
| Files | `ground-truth.md`, `fact-patterns.md`, `negative-claim-rules.md` |

## Live facts this snapshot states

Verified 2026-09-20 against Finney RPC (`https://entrypoint-finney.opentensor.ai`,
finalized ~9104590) and TaoSwap `/v2/subnets/`:

- Spec **467**. Atlas `spec_upgrades` on the Pi recorded 455→467 (456–459
  share-pool/baskets, 464 security/torsion, 466 fee cap, 467 fee halve).
  This corpus does not describe unverified 456–467 internals.
- Emission bar is **rank-pinned**: `EmissionBarRank` unset (default 32),
  `EmissionBarQuantile` 0.75 explicit and inert, `EmissionGateExponent`
  unset (default 3).
- `SubnetEmissionEnabled` is live. 128 keys; **29, 35, 36 off**; SN1 on.
  TaoSwap `emission_is_enabled` matches.
- `RootWeightSettingEnabled` is **false** (unset). Basket curation is off.
  `RootWeightsCap` unset (default 4096), inert while the switch is off.

[../supersession-markers.json](../supersession-markers.json) is empty. Add
a marker if a corpus claim goes stale before the next re-sync.

## Re-sync procedure

When the live grounding changes:

1. Edit the three files so they state current chain facts, not history.
2. Regenerate `hashes.json` (sha256 per file, newline-normalized LF;
   update `sync_date` and `coverage_date`).
3. Review `supersession-markers.json`.
4. Commit, `git pull` on the Pi, `ingest`, review the validation report,
   `activate` the new run.

The originals in `intoops-routines` are never modified or deleted from this
repo (ATLAS-KB-007 closed as not-applicable).
