# Corpus snapshot provenance

The three grounding files Atlas retrieves from. Machine-readable hashes in
[hashes.json](hashes.json); ingest verifies them before creating any unit.

| field | value |
|---|---|
| Source of truth | `D:\Coding\Bittensor\IntoOps\intoops-routines\references\` |
| Sync date | 2026-09-23 |
| Coverage date | 2026-09-23 |
| Grounded at | Finney `spec_version` **469** |
| Files | `ground-truth.md`, `fact-patterns.md`, `negative-claim-rules.md` |

## Live facts this snapshot states

Verified 2026-09-23 against Finney RPC (`https://entrypoint-finney.opentensor.ai`):

- Spec **469**. Knob read at finalized block 9125891. Emission-switch map at
  finalized block 9125893. Dust-floor storage at finalized block 9125904.
  Tracked clone `370bac46f` (`runtime/src/lib.rs` `spec_version: 469`).
- Emission bar is **rank-pinned**: `EmissionBarRank` unset (default 32),
  `EmissionBarQuantile` 0.75 explicit and inert, `EmissionGateExponent`
  unset (default 3).
- `SubnetEmissionEnabled` is live. 128 keys; **29, 35, 36, 108 off**; SN1 on.
- `RootWeightSettingEnabled` is **false** (unset). Basket curation is off.
  `RootWeightsCap` unset (default 4096), inert while the switch is off.
- `BasketTradingEnabled` is **true** (explicit). It gates `swap_basket`.
  It is not the curation switch. A hotkey can still be frozen.
- Claim dust floors are unset on chain. Code defaults apply: row floor
  min(1 TAO, 10 bps of anchored NAV); slice floor 0.0001 TAO. Cash-first
  claims are not live.

[../supersession-markers.json](../supersession-markers.json) is empty. Add
a marker if a corpus claim goes stale before the next re-sync.

## Re-sync procedure

The shortcut hourly Finney spec-sync job is retired from automatic writes.
Its version comparison is diagnostic only; matching versions do not establish
health, publication, source identity, or completed activation. The guarded
`maintenance/` controller owns future automated changes after commissioning.
See `maintenance/README.md` for its completion gate. Until that gate passes,
automatic publication and activation remain disabled.

For a separately authorized manual refresh, apply these evidence rules:

1. Confirm the tracked clone's `spec_version` is at least the live spec.
   If the clone lags, stop. Do not rewrite from a lagging tree.
2. Read the spec-bump commits in the clone. State only mechanics that are
   still in the live spec. A path that was added and then dropped before
   the spec shipped is not live.
3. Re-read every live knob the corpus states, at one finalized block, and
   cite that block. Code defaults are not live values.
4. Edit the three files so they state current chain facts, not history.
5. Regenerate `hashes.json` (sha256 per file, newline-normalized LF;
   update `sync_date`, `coverage_date`, and `grounded_spec`).
6. Review `supersession-markers.json`.
7. Stage ingestion and review the validation report. Do not activate before
   the controller's tests, independent exact-tree review, publication, and
   deployment acceptance gates pass.
8. Publish only through `maintenance/` with its explicit external operator
   config and signed receipt. `knowledge/atlas_spec_publish.py` now refuses
   every invocation; it cannot bypass validation or deployment recovery.
   Do not force-push. Do not use the subnt deploy key.

The originals in `intoops-routines` are never modified or deleted from this
repo (ATLAS-KB-007 closed as not-applicable).
