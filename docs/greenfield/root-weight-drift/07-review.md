# root-weight-drift: outside-voice review

Session 3, 2026-09-24. Cold read of `openspec/changes/root-weight-drift/`
plus the code it touches.

## Verified

- `BasketConcentrationCap` pinned key
  `0x658f...0454b` equals `twox128("SubtensorModule") ++
  twox128("BasketConcentrationCap")` from `atlas_live.twox128`.
- The re-ADDED watch requirement differs from the old one only in the cap
  item, the retired-items rule, and three scenarios. No rule was lost.
- No reader of `Weights`, `Keys`, or `TotalHotkeyAlpha` exists outside the
  root read code. Dropping them from `CHAIN_READS` is safe.
- Fleet ingestion skips a missing table (`if table not in tables`), and no
  other living spec (`fleet-signals`, `signal-effectiveness-gate`,
  `pulse-briefing`, `chain-read-probe`) names root-rotation.
- `upgrade/prompt.md` does not cite the retired items. The upgrade job feeds
  `read-knobs` output into its prompt, so the knob swap reaches it.

## Findings

| ID | Severity | Finding | Proposed resolution |
|---|---|---|---|
| R1 | Major | The Pi keeps serving the old corpus. `git pull` does not re-ingest; `knowledge/atlas_kb.py` needs `ingest` then `activate --run <id>`. The migration plan says pull is enough. | Add an operator step to the migration plan and a task: on the Pi, after pull, run ingest and activate. |
| R2 | Minor | `fleet/README.md:209` says root-rotation events enter the ledger. Task 6.1 omits it. | Add `fleet/README.md` to task 6.1. |
| R3 | Minor | The probe checks only `CHAIN_READS`, not the pinned config key. A typo in the 1.3 key would pass the probe and read null as `assumed-default` 4096 forever. | Task 4.1: assert the config key equals the `twox128` derivation. |
| R4 | Minor | The `RootWeightSettingEnabled` next-action branch is deleted and nothing replaces it, so a cap transition pages with no next-action line. | Add a `BasketConcentrationCap` branch in `telegram/atlas_telegram.py` next to the others. |
| R5 | Minor | Task 1.3 `governs` text for the cap has no scale. The old gloss said "4096/65535 = 1/16". There is no upstream clone on the workstation to confirm that `swap_basket` uses the same u16 normalization. | Confirm the scale in upstream `swap_basket` during apply. If it is not confirmed, state the raw value and leave the ratio out. |
| R6 | Accepted | After removal, no watch item uses a hasher. The netuid-keyed derivation scenario now covers a mechanism with no configured item. | Keep it (design decision 4). Tests use a fixture. No change. |

## Resolution

Operator accepted R1 to R5 as proposed on 2026-09-24. They were folded in with
`/opsx:update`: design decision 6 and the migration plan, the proposal
Impact, and tasks 1.3, 3.2, 3.3, 4.1, 6.1, and a new 6.5. The specs are
unchanged. R6 is accepted as-is. `openspec validate --strict` passes.

Next: Session 4 (apply).
