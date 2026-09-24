# root-weight-drift: approval

Approved: 2026-09-24, operator.

Change: `openspec/changes/root-weight-drift/` (validates `--strict`).

Brainstorm open questions, resolved in Session 2:

- `rotation_events` consumers (fleet ledger ingestion, Telegram
  `root-rotation` class): removed. Stored rows stay.
- Retired watch items: dropped silently. `docs/decisions.md` records it.
- Battery: revise `KB-EX-8` and `KB-CF-4`, add `KB-CF-6`.
- `BasketConcentrationCap`: plain `u16`, default 4096, explicit 4096 live
  at block 9133830. First observation seeds silently.

Spec note: the chain-parameter watch requirement is REMOVED and re-ADDED
under a new name, because `openspec validate` refuses a MODIFIED block that
drops the `RootWeightsCap` scenario.

Next: Session 3 (outside-voice, optional) or Session 4 (apply).
