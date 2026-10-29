# Open items

Carried over from the old README when it was rewritten on 2026-10-30. These
were last confirmed between 2026-09-24 and 2026-10-22. Check each before
acting on it.

## Operator steps

- **Hermes script cleanup.** After the first real runtime upgrade, delete
  `atlas_live_spec.py` from the Hermes scripts directory (task 7.4 of the
  runtime upgrade).
- **Stale units.** Old disabled copies of the repotrack and fleet units remain
  in `/etc/systemd/system/`. Cleanup is a planned separate change, together
  with moving the reader wrapper back into the repository.

## Before the next proposal

- **`mining.budget_band`.** It is `null` in `fleet/config.json` while
  `mining.enabled` is `true`. Pick a band, or set `enabled` to false.
- **Voice calibration.** Run one week of real Telegram traffic against
  [`telegram/docs/voice.md`](../telegram/docs/voice.md). Acceptance ran
  through the CLI only.

## Blocked

- **Phase 6**, the operator monitoring frontend, waits on PRD section 21
  questions 36 to 40.

## Standing debts

Recorded in [`decisions.md`](decisions.md): backup restore test, a dedicated
service account, a service unit for boot persistence (which also gates the
deferred service-failure alerts), and the PRD section 21 Q19 gating decision.
